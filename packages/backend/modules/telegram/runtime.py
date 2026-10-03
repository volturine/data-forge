from __future__ import annotations

import asyncio
import contextvars
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC, datetime
from functools import partial

import httpx
import psycopg
from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError

from backend_core.api_execution_budget import run_bootstrap_settings_db
from backend_core.database import run_settings_db
from backend_core.live_hubs import KeyedVersionHub, VersionHub
from modules.telegram import bot, store
from modules.telegram.domain import TelegramDetectionClaim, TelegramSettings

logger = logging.getLogger(__name__)

_TELEGRAM_BASE_URL = 'https://api.telegram.org'
_POLL_TIMEOUT_SECONDS = 5
_HTTP_TIMEOUT = httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=3.0)
_RECOVERY_SECONDS = 5.0
_DATABASE_RETRY_INITIAL_SECONDS = 0.25
_DATABASE_RETRY_MAX_SECONDS = 5.0
_TRANSIENT_DATABASE_ERRORS = (SQLAlchemyOperationalError, psycopg.OperationalError)
_DETECTION_RESULT_HUB = KeyedVersionHub()
_COORDINATOR_DATABASE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='telegram-coordinator-database')


class TelegramDetectionFailed(RuntimeError):
    pass


class TelegramDetectionTimedOut(TimeoutError):
    pass


async def request_chat_detection(*, token: str, request_user_id: str, namespace: str) -> dict[str, object]:
    try:
        async with asyncio.timeout(store.DETECTION_TIMEOUT_SECONDS):
            return await _wait_chat_detection(token=token, request_user_id=request_user_id, namespace=namespace)
    except TimeoutError as exc:
        raise TelegramDetectionTimedOut('Telegram detection deadline expired') from exc


async def _wait_chat_detection(*, token: str, request_user_id: str, namespace: str) -> dict[str, object]:
    request_id = await _run_detection_database(
        store.enqueue_detection,
        token=token,
        request_user_id=request_user_id,
        namespace=namespace,
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + store.DETECTION_TIMEOUT_SECONDS
    while True:
        wake_version = _DETECTION_RESULT_HUB.version(request_id)
        result = await _run_detection_database(
            store.get_detection_result,
            request_id=request_id,
            request_user_id=request_user_id,
        )
        if result is None:
            raise TelegramDetectionFailed('Telegram detection request was not found')
        if result.status == 'completed' and result.result is not None:
            return result.result
        if result.status == 'failed':
            raise TelegramDetectionFailed(result.error or 'Telegram detection failed')
        if result.status == 'timed_out':
            raise TelegramDetectionTimedOut(result.error or 'Telegram detection timed out')
        remaining = deadline - loop.time()
        if remaining <= 0:
            await _run_detection_database(store.time_out_detection, request_id=request_id, request_user_id=request_user_id)
            raise TelegramDetectionTimedOut('Telegram detection timed out')
        with suppress(TimeoutError):
            await asyncio.wait_for(
                _DETECTION_RESULT_HUB.wait(request_id, last_seen=wake_version),
                timeout=min(_RECOVERY_SECONDS, remaining),
            )
            # PostgreSQL notifications are a fast path. This bounded reread is
            # the recovery path if this API process missed a notification.


async def _run_public_database[T](function: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Run one coordinator DB operation; its single actor awaits each call."""
    loop = asyncio.get_running_loop()
    context = contextvars.copy_context()
    work = partial(run_settings_db, function, *args, **kwargs)
    return await loop.run_in_executor(_COORDINATOR_DATABASE_EXECUTOR, context.run, work)


async def _run_detection_database[T](function: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Run HTTP-waiter DB work through the API's bounded protected lane."""
    return await run_bootstrap_settings_db(function, *args, **kwargs)


def notify_detection_result(request_id: str) -> None:
    """Wake local HTTP waiters; the durable row remains authoritative."""
    _DETECTION_RESULT_HUB.publish(request_id)


class TelegramIntegrationRuntime:
    """Single coordinator-owned Telegram poller and serialized detection actor."""

    def __init__(self, generation: int) -> None:
        self.generation = generation
        self._wake_hub = VersionHub()

    def wake(self) -> None:
        """Interrupt the current poll so settings and detection work reload promptly."""
        self._wake_hub.publish(None)

    async def run(self, stop_event: asyncio.Event) -> None:
        wake_version = self._wake_hub.version()
        retry_delay = _DATABASE_RETRY_INITIAL_SECONDS
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            while not stop_event.is_set():
                try:
                    wake_version = await self._run_cycle(client, stop_event, wake_version)
                except asyncio.CancelledError:
                    raise
                except store.TelegramOwnerFenced:
                    raise
                except _TRANSIENT_DATABASE_ERRORS:
                    logger.warning(
                        'Telegram actor database operation failed; retrying in %.2fs',
                        retry_delay,
                        exc_info=True,
                    )
                    with suppress(TimeoutError):
                        await asyncio.wait_for(stop_event.wait(), timeout=retry_delay)
                    if stop_event.is_set():
                        return
                    retry_delay = min(retry_delay * 2, _DATABASE_RETRY_MAX_SECONDS)
                else:
                    retry_delay = _DATABASE_RETRY_INITIAL_SECONDS

    async def _run_cycle(
        self,
        client: httpx.AsyncClient,
        stop_event: asyncio.Event,
        wake_version: int,
    ) -> int:
        await self._database(store.recover_detection_requests, generation=self.generation)
        claim = await self._database(store.claim_detection, generation=self.generation)
        if claim is not None:
            await self._process_detection(client, claim)
            wake_version = self._wake_hub.version()
            if stop_event.is_set():
                return wake_version

        settings = await self._database(store.read_settings)
        current_version = self._wake_hub.version()
        if current_version != wake_version:
            return current_version
        if not settings.enabled or not settings.token:
            return await self._wait_for_signal(stop_event, wake_version, timeout=1.0)

        fingerprint = store.token_fingerprint(settings.token)
        offset = await self._database(store.get_next_update_id, fingerprint)
        response, wake_version = await self._get_updates_or_wake(
            client,
            stop_event,
            wake_version,
            token=settings.token,
            offset=offset,
            poll_timeout=_POLL_TIMEOUT_SECONDS,
        )
        if response is None:
            return wake_version
        handled = await self._process_poll_response(client, settings, fingerprint, response)
        if not handled:
            return await self._wait_for_signal(stop_event, wake_version, timeout=_RECOVERY_SECONDS)
        return wake_version

    async def _process_poll_response(
        self,
        client: httpx.AsyncClient,
        settings: TelegramSettings,
        fingerprint: str,
        response: httpx.Response,
    ) -> bool:
        if response.status_code == 409:
            logger.warning('Telegram getUpdates conflict; clearing webhook before retry')
            await self._clear_webhook(client, settings.token)
            await asyncio.sleep(0)
            return False
        if response.status_code == 401:
            logger.error('Telegram bot token was rejected; waiting for a settings change')
            return False
        if response.status_code != 200:
            logger.warning('Telegram getUpdates returned HTTP %s', response.status_code)
            return False
        try:
            payload = response.json()
        except ValueError:
            logger.warning('Telegram getUpdates returned invalid JSON')
            return False
        if not isinstance(payload, dict) or not isinstance(payload.get('result'), list):
            logger.warning('Telegram getUpdates returned an invalid result payload')
            return False

        offset = await self._database(store.get_next_update_id, fingerprint)
        await self._database(store.require_generation, self.generation)
        for update in payload['result']:
            if not isinstance(update, dict):
                continue
            update_id = update.get('update_id')
            if not isinstance(update_id, int) or isinstance(update_id, bool):
                logger.warning('Skipping Telegram update without an integer update_id')
                continue
            if update_id < offset:
                continue
            try:
                await bot.handle_update(client, token=settings.token, update=update, generation=self.generation)
                await self._database(
                    store.advance_update_id,
                    fingerprint=fingerprint,
                    next_update_id=update_id + 1,
                    generation=self.generation,
                    chats=_detected_chats([update]),
                )
                offset = update_id + 1
            except httpx.HTTPError:
                logger.warning('Telegram command response failed; update offset was not advanced')
                return False
            except store.TelegramOwnerFenced:
                raise
            except _TRANSIENT_DATABASE_ERRORS:
                raise
            except Exception:
                logger.warning('Telegram update handling failed; update offset was not advanced')
                return False
        return True

    async def _process_detection(self, client: httpx.AsyncClient, claim: TelegramDetectionClaim) -> None:
        if claim.deadline_at <= datetime.now(UTC):
            await self._complete_detection(claim, {'success': False, 'message': 'Telegram chat detection timed out', 'chats': []})
            return
        try:
            offset = await self._database(store.get_next_update_id, claim.token_sha256)
            async with asyncio.timeout(min(10.0, max((claim.deadline_at - datetime.now(UTC)).total_seconds(), 0.01))):
                response = await client.get(
                    f'{_TELEGRAM_BASE_URL}/bot{claim.token}/getUpdates',
                    params={'limit': 10, 'timeout': 0, 'offset': offset},
                    timeout=_HTTP_TIMEOUT,
                )
            if response.status_code != 200:
                message = _redact_token(_telegram_error_message(response), claim.token)
                await self._complete_detection(
                    claim,
                    {'success': False, 'message': message, 'chats': []},
                )
                return
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get('result'), list):
                raise ValueError('Telegram API returned an invalid result payload')
            previous = await self._database(store.observed_chats, claim.token_sha256)
            by_chat = {chat['chat_id']: chat for chat in previous}
            by_chat.update({chat['chat_id']: chat for chat in _detected_chats(payload['result'])})
            chats = list(by_chat.values())
            await self._complete_detection(
                claim,
                {'success': True, 'message': f'Found {len(chats)} chat(s)', 'chats': chats},
            )
        except store.TelegramOwnerFenced:
            raise
        except _TRANSIENT_DATABASE_ERRORS:
            raise
        except Exception as exc:
            error = _redact_token(str(exc), claim.token)
            await self._database(store.fail_detection, claim=claim, error=error)

    async def _complete_detection(self, claim: TelegramDetectionClaim, result: dict[str, object]) -> None:
        await self._database(store.complete_detection, claim=claim, result=result)

    async def _clear_webhook(self, client: httpx.AsyncClient, token: str) -> None:
        try:
            await client.post(
                f'{_TELEGRAM_BASE_URL}/bot{token}/deleteWebhook',
                json={'drop_pending_updates': False},
                timeout=_HTTP_TIMEOUT,
            )
        except httpx.HTTPError:
            logger.warning('Failed to clear Telegram webhook')

    async def _get_updates_or_wake(
        self,
        client: httpx.AsyncClient,
        stop_event: asyncio.Event,
        wake_version: int,
        *,
        token: str,
        offset: int,
        poll_timeout: int,
    ) -> tuple[httpx.Response | None, int]:
        request_task = asyncio.create_task(
            _poll_request(
                client,
                f'{_TELEGRAM_BASE_URL}/bot{token}/getUpdates',
                params={'offset': offset, 'timeout': poll_timeout},
            )
        )
        wake_task = asyncio.create_task(self._wake_hub.wait(last_seen=wake_version))
        stop_task = asyncio.create_task(stop_event.wait())
        tasks = {request_task, wake_task, stop_task}
        try:
            done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            pending = {task for task in tasks if not task.done()}
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if stop_task in done:
            return None, self._wake_hub.version()
        if wake_task in done:
            if request_task in done:
                await asyncio.gather(request_task, return_exceptions=True)
            return None, wake_task.result()
        if request_task in done:
            try:
                return request_task.result(), self._wake_hub.version()
            except httpx.HTTPError, TimeoutError:
                logger.warning('Telegram getUpdates transport failed')
                version = await self._wait_for_signal(stop_event, self._wake_hub.version(), timeout=_RECOVERY_SECONDS)
                return None, version
        if wake_task in done:
            return None, wake_task.result()
        return None, self._wake_hub.version()

    async def _wait_for_signal(self, stop_event: asyncio.Event, wake_version: int, *, timeout: float) -> int:
        wake_task = asyncio.create_task(self._wake_hub.wait(last_seen=wake_version))
        stop_task = asyncio.create_task(stop_event.wait())
        timer_task = asyncio.create_task(asyncio.sleep(timeout))
        tasks = {wake_task, stop_task, timer_task}
        try:
            done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if wake_task in done:
            return wake_task.result()
        return self._wake_hub.version()

    @staticmethod
    async def _database[T](function: Callable[..., T], *args: object, **kwargs: object) -> T:
        return await _run_public_database(function, *args, **kwargs)


async def _poll_request(client: httpx.AsyncClient, url: str, *, params: dict[str, int]) -> httpx.Response:
    async with asyncio.timeout(10.0):
        return await client.get(url, params=params, timeout=_HTTP_TIMEOUT)


def _detected_chats(updates: list[object]) -> list[dict[str, str]]:
    seen: dict[str, str] = {}
    for update in updates:
        if not isinstance(update, dict):
            continue
        payload = update.get('message')
        if not isinstance(payload, dict):
            payload = update.get('channel_post')
        if not isinstance(payload, dict):
            continue
        chat = payload.get('chat')
        if not isinstance(chat, dict) or chat.get('id') is None:
            continue
        chat_id = str(chat['id'])
        if chat_id not in seen:
            seen[chat_id] = str(chat.get('first_name') or chat.get('title') or chat.get('username') or chat_id)
    return [{'chat_id': chat_id, 'title': title} for chat_id, title in seen.items()]


def _telegram_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f'Telegram API error: HTTP {response.status_code}'
    if isinstance(payload, dict) and isinstance(payload.get('description'), str):
        return f'Telegram API error: {payload["description"]}'
    return f'Telegram API error: HTTP {response.status_code}'


def _redact_token(message: str, token: str) -> str:
    if token:
        message = message.replace(token, '[REDACTED]')
    return message[:500]
