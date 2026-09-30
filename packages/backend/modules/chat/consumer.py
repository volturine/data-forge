"""Fenced coordinator consumer for durable chat turns."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

from fastapi import FastAPI

from backend_core.namespace import normalize_namespace
from modules.chat.sessions import session_store
from modules.chat.store import ConfirmationPending, TurnClaim, chat_turn_store
from modules.mcp.models import MCPToolDefinition
from modules.mcp.registry import build_tool_registry

_MAX_ACTIVE_TURNS = 4
_CLAIM_BATCH_SIZE = 4
_RECOVERY_SECONDS = 1.0
_CONTROL_POLL_SECONDS = 0.5
_DATABASE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix='chat-database')
_PROVIDER_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix='chat-provider')
logger = logging.getLogger(__name__)


class TurnRuntime:
    """Mutable state for one consumer-owned turn, backed by fenced writes."""

    def __init__(self, claim: TurnClaim, app: FastAPI, registry: tuple[MCPToolDefinition, ...], messages: list[dict[str, Any]]) -> None:
        self.claim = claim
        self.app = app
        self.registry = registry
        self.id = claim.session_id
        self.turn_id = claim.id
        self.user_id = claim.user_id
        self.provider = claim.provider
        self.model = claim.model
        self.api_key = claim.api_key
        self.system_prompt = claim.system_prompt
        self.session_token = claim.session_token
        self.namespace = normalize_namespace(claim.namespace)
        self.tool_ids = list(claim.tool_ids)
        self.messages = ([{'role': 'system', 'content': claim.system_prompt}] if claim.system_prompt else []) + [
            message for message in messages if message.get('role') != 'system'
        ]
        self.checkpoint = dict(claim.checkpoint)
        self.provider_turn = int(self.checkpoint.get('provider_turn', 0))
        self.use_text_format = bool(self.checkpoint.get('use_text_format', True))
        self.turn_usage = dict(self.checkpoint.get('usage', {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}))
        self.claim_token = claim.claim_token
        self.coordinator_generation = claim.coordinator_generation
        self.confirmation_decision = claim.confirmation_decision
        self.owner_stopping = False
        self.stop_requested = False
        self.failed = False
        self._finished = False

    async def _db[**P, T](self, function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_DATABASE_EXECUTOR, partial(function, *args, **kwargs))

    async def append_message(self, message: dict[str, Any]) -> None:
        await self._db(
            chat_turn_store.append_message,
            turn_id=self.turn_id,
            claim_token=self.claim_token,
            generation=self.coordinator_generation,
            message=message,
        )
        self.messages.append(message)
        _trim_messages(self.messages)

    async def push_event(self, event: dict[str, Any]) -> int:
        return await self._db(
            chat_turn_store.append_event,
            turn_id=self.turn_id,
            claim_token=self.claim_token,
            generation=self.coordinator_generation,
            payload=event,
        )

    async def set_checkpoint(
        self,
        checkpoint: dict[str, Any],
        *,
        status: str | None = None,
        clear_confirmation: bool = False,
    ) -> None:
        checkpoint = {**checkpoint, 'provider_turn': self.provider_turn, 'usage': dict(self.turn_usage), 'use_text_format': self.use_text_format}
        await self._db(
            chat_turn_store.set_checkpoint,
            turn_id=self.turn_id,
            claim_token=self.claim_token,
            generation=self.coordinator_generation,
            checkpoint=checkpoint,
            status=status,
            clear_confirmation=clear_confirmation,
        )
        self.checkpoint = checkpoint

    async def control_state(self) -> tuple[bool, bool | None]:
        return await self._db(
            chat_turn_store.control_state,
            turn_id=self.turn_id,
            claim_token=self.claim_token,
            generation=self.coordinator_generation,
        )

    async def wait_for_confirm(self) -> bool:
        while True:
            stop_requested, decision = await self.control_state()
            if stop_requested:
                self.stop_requested = True
                raise asyncio.CancelledError
            if decision is not None:
                self.confirmation_decision = decision
                await self.set_checkpoint(
                    {**self.checkpoint, 'phase': 'tool_ready' if decision else 'provider_request'},
                    status='running',
                    clear_confirmation=True,
                )
                return decision
            await self._db(
                chat_turn_store.release_confirmation,
                turn_id=self.turn_id,
                claim_token=self.claim_token,
                generation=self.coordinator_generation,
            )
            raise ConfirmationPending

    async def run_sync_provider[**P, T](self, function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(_PROVIDER_EXECUTOR, partial(function, *args, **kwargs))
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            if not self._finished:
                interrupted = self.owner_stopping
                await self.push_event({'type': 'error', 'content': 'Generation interrupted by coordinator restart' if interrupted else 'Generation stopped'})
                await self.finish('interrupted' if interrupted else 'failed')
            # Keep the admission slot until the bounded HTTP request exits;
            # cancelling a thread future cannot terminate its provider I/O.
            while not future.done():
                try:
                    await asyncio.shield(future)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            raise

    @property
    def finished(self) -> bool:
        return self._finished

    async def finish(self, status: str) -> None:
        if self._finished:
            return
        await self._db(
            chat_turn_store.finish,
            turn_id=self.turn_id,
            claim_token=self.claim_token,
            generation=self.coordinator_generation,
            status=status,
        )
        self._finished = True


def _trim_messages(messages: list[dict[str, Any]]) -> None:
    from modules.chat.sessions import MAX_MESSAGES

    if len(messages) <= MAX_MESSAGES:
        return
    system = [message for message in messages if message.get('role') == 'system']
    other = [message for message in messages if message.get('role') != 'system']
    messages[:] = system + other[-(MAX_MESSAGES - len(system)) :]


async def _load_turn(claim: TurnClaim, app: FastAPI, registry: tuple[MCPToolDefinition, ...]) -> TurnRuntime:
    messages = await asyncio.get_running_loop().run_in_executor(_DATABASE_EXECUTOR, session_store.messages, claim.session_id)
    return TurnRuntime(claim, app, registry, messages)


class ChatTurnConsumer:
    """Run bounded chat work under the active runtime coordinator generation."""

    def __init__(self, app: FastAPI, generation: int) -> None:
        self.app = app
        self.generation = generation
        self._wake_event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopping = False
        # Build once from route metadata. The consumer does not clone app.state or
        # hold API-owned session objects; ASGI tool calls use the injected app.
        self.registry = tuple(build_tool_registry(app))

    def wake(self) -> None:
        loop = self._loop
        event = self._wake_event
        if loop is not None and event is not None:
            loop.call_soon_threadsafe(event.set)

    async def run(self, stop_event: asyncio.Event) -> None:
        self._loop = asyncio.get_running_loop()
        self._wake_event = asyncio.Event()
        await self._database(chat_turn_store.recover, generation=self.generation)
        active: set[asyncio.Task[None]] = set()
        self._stopping = False
        try:
            while not stop_event.is_set():
                completed = {task for task in active if task.done()}
                active.difference_update(completed)
                for task in completed:
                    task.result()
                capacity = _MAX_ACTIVE_TURNS - len(active)
                if capacity:
                    claims = await self._database(
                        chat_turn_store.claim_batch,
                        generation=self.generation,
                        limit=min(capacity, _CLAIM_BATCH_SIZE),
                    )
                    for claim in claims:
                        task = asyncio.create_task(self._run_claim(claim), name=f'chat-turn-{claim.id}')
                        active.add(task)
                if active and len(active) >= _MAX_ACTIVE_TURNS:
                    await self._wait_for_work(stop_event, active)
                    continue
                await self._wait_for_work(stop_event, active, timeout=_RECOVERY_SECONDS)
        finally:
            self._stopping = True
            for task in active:
                task.cancel()
            if active:
                await asyncio.gather(*active, return_exceptions=True)
            self._loop = None
            self._wake_event = None

    async def _database[**P, T](self, function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_DATABASE_EXECUTOR, partial(function, *args, **kwargs))

    async def _run_claim(self, claim: TurnClaim) -> None:
        try:
            runtime = await _load_turn(claim, self.app, self.registry)
            stop_requested, _decision = await runtime.control_state()
            if stop_requested:
                runtime.stop_requested = True
                await runtime.push_event({'type': 'error', 'content': 'Generation stopped'})
                await runtime.finish('failed')
                return
            from modules.chat.routes import _run_agent_turn

            turn_task = asyncio.create_task(
                _run_agent_turn(
                    runtime,
                    self.app,
                    claim.content,
                    list(claim.tool_ids) or None,
                    {'headers': {'X-Session-Token': claim.session_token, 'X-Namespace': runtime.namespace}},
                    self.registry,
                ),
                name=f'chat-agent-{claim.id}',
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('Could not start durable chat turn id=%s', claim.id)
            await self._database(
                chat_turn_store.append_event,
                turn_id=claim.id,
                claim_token=claim.claim_token,
                generation=claim.coordinator_generation,
                payload={'type': 'error', 'content': 'Chat turn could not be resumed'},
            )
            await self._database(
                chat_turn_store.finish,
                turn_id=claim.id,
                claim_token=claim.claim_token,
                generation=claim.coordinator_generation,
                status='failed',
            )
            return
        watcher = asyncio.create_task(self._watch_stop(runtime, turn_task), name=f'chat-stop-{claim.id}')
        try:
            await asyncio.shield(turn_task)
        except asyncio.CancelledError:
            runtime.owner_stopping = self._stopping
            turn_task.cancel()
            await asyncio.gather(turn_task, return_exceptions=True)
        finally:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher

    async def _watch_stop(self, runtime: TurnRuntime, turn_task: asyncio.Task[None]) -> None:
        while not turn_task.done():
            try:
                stop_requested, _decision = await runtime.control_state()
            except RuntimeError:
                return
            if stop_requested:
                runtime.stop_requested = True
                turn_task.cancel()
                return
            await asyncio.sleep(_CONTROL_POLL_SECONDS)

    async def _wait_for_work(
        self,
        stop_event: asyncio.Event,
        active: set[asyncio.Task[None]],
        *,
        timeout: float | None = None,
    ) -> None:
        waiters: set[asyncio.Task[Any]] = {asyncio.create_task(stop_event.wait())}
        wake = self._wake_event
        wake_task: asyncio.Task[Any] | None = None
        if wake is not None:
            wake_task = asyncio.create_task(wake.wait())
            waiters.add(wake_task)
        waiters.update(task for task in active if not task.done())
        done, pending = await asyncio.wait(
            waiters,
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            if task not in active:
                task.cancel()
        if pending:
            await asyncio.gather(*(task for task in pending if task not in active), return_exceptions=True)
        if wake is not None and wake_task in done:
            wake.clear()
