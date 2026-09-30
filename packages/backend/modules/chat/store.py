"""PostgreSQL ownership, transcript, and event operations for chat turns."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, text
from sqlmodel import Session

from backend_core.database import RuntimeCoordinatorFenced, run_settings_db
from backend_core.live_hubs import KeyedVersionHub
from backend_core.secrets import decrypt_secret, encrypt_secret
from backend_core.sqlmodel_typing import col
from modules.chat.models import ChatEvent, ChatMessage, ChatSession, ChatTurn
from modules.chat.sessions import ACTIVE_TURN_STATUSES, MAX_EVENTS, MAX_MESSAGES, normalize_epoch_milliseconds

CHAT_TURN_WAKE_KIND = 'chat_turn'
CHAT_EVENT_WAKE_KIND = 'chat_event'
_RUNTIME_CHANNEL = 'runtime_events'
logger = logging.getLogger(__name__)


class ConfirmationPending(Exception):
    """The durable turn is suspended until an API child records a decision."""


class ChatClaimRevoked(Exception):
    """The turn was removed, finished, or reassigned within this epoch."""


@dataclass(frozen=True, slots=True)
class TurnClaim:
    id: str
    session_id: str
    user_id: str
    content: str
    tool_ids: tuple[str, ...]
    namespace: str
    session_token: str
    provider: str
    model: str
    api_key: str
    system_prompt: str
    checkpoint: dict[str, Any]
    claim_token: str
    coordinator_generation: int
    confirmation_decision: bool | None


def _notify(db: Session, payload: dict[str, Any]) -> None:
    if db.get_bind().dialect.name != 'postgresql':
        return
    db.execute(
        text('SELECT pg_notify(:channel, :payload)'),
        {'channel': _RUNTIME_CHANNEL, 'payload': json.dumps(payload, separators=(',', ':'))},
    )


def _verify_claim(db: Session, turn_id: str, claim_token: str, generation: int) -> ChatTurn:
    turn = db.execute(select(ChatTurn).where(col(ChatTurn.id) == turn_id).with_for_update()).scalar_one_or_none()
    if turn is None:
        raise ChatClaimRevoked('Chat turn was removed')
    if turn.coordinator_generation is not None and turn.coordinator_generation != generation:
        raise RuntimeCoordinatorFenced(f'Chat turn generation {generation} was fenced by generation {turn.coordinator_generation}')
    if turn.coordinator_generation != generation or turn.claim_token != claim_token or turn.status not in ('running', 'awaiting_confirmation'):
        raise ChatClaimRevoked('Chat turn claim was revoked or is no longer active')
    return turn


def _append_event(db: Session, *, session_id: str, turn_id: str | None, payload: dict[str, Any]) -> int:
    db.execute(select(col(ChatSession.id)).where(col(ChatSession.id) == session_id).with_for_update()).scalar_one()
    event = dict(payload)
    timestamp = normalize_epoch_milliseconds(event.get('ts'))
    event['ts'] = timestamp if timestamp is not None else round(time.time() * 1000)
    next_sequence = int(db.execute(select(func.max(col(ChatEvent.sequence))).where(col(ChatEvent.session_id) == session_id)).scalar_one_or_none() or 0) + 1
    row = ChatEvent(sequence=next_sequence, session_id=session_id, turn_id=turn_id, payload=event)
    db.add(row)
    db.flush()
    sequence = int(row.sequence)
    old_events = select(col(ChatEvent.sequence)).where(col(ChatEvent.session_id) == session_id).order_by(col(ChatEvent.sequence).desc()).offset(MAX_EVENTS)
    db.execute(delete(ChatEvent).where(col(ChatEvent.session_id) == session_id, col(ChatEvent.sequence).in_(old_events)))
    _notify(db, {'kind': CHAT_EVENT_WAKE_KIND, 'session_id': session_id, 'sequence': sequence})
    return sequence


def _append_message(db: Session, *, session_id: str, turn_id: str | None, message: dict[str, Any]) -> None:
    db.add(ChatMessage(session_id=session_id, turn_id=turn_id, message=message))
    db.flush()
    rows = db.execute(
        select(col(ChatMessage.sequence), col(ChatMessage.message)).where(col(ChatMessage.session_id) == session_id).order_by(col(ChatMessage.sequence))
    ).all()
    systems = [int(sequence) for sequence, item in rows if item.get('role') == 'system']
    other = [int(sequence) for sequence, item in rows if item.get('role') != 'system']
    limit = max(MAX_MESSAGES - len(systems), 0)
    recent = other[-limit:] if limit else []
    retained = systems + recent
    db.execute(
        delete(ChatMessage).where(
            col(ChatMessage.session_id) == session_id,
            col(ChatMessage.sequence).not_in(retained),
        )
    )


def _enqueue(
    db: Session,
    *,
    session_id: str,
    user_id: str,
    content: str,
    tool_ids: list[str],
    namespace: str,
    session_token: str,
) -> str:
    session = db.execute(
        select(ChatSession).where(col(ChatSession.id) == session_id, col(ChatSession.user_id) == user_id).with_for_update()
    ).scalar_one_or_none()
    if session is None:
        raise LookupError('Session not found')
    active = db.execute(
        select(col(ChatTurn.id)).where(col(ChatTurn.session_id) == session_id, col(ChatTurn.status).in_(ACTIVE_TURN_STATUSES))
    ).scalar_one_or_none()
    if active is not None:
        raise RuntimeError('Agent busy')
    turn_id = secrets.token_urlsafe(18)
    turn = ChatTurn(
        id=turn_id,
        session_id=session_id,
        user_id=user_id,
        content=content,
        tool_ids=tool_ids,
        namespace=namespace,
        session_token_encrypted=encrypt_secret(session_token),
        status='queued',
        checkpoint={},
    )
    db.add(turn)
    db.flush()
    _append_message(db, session_id=session_id, turn_id=turn_id, message={'role': 'user', 'content': content})
    _append_event(db, session_id=session_id, turn_id=turn_id, payload={'type': 'message', 'role': 'user', 'content': content})
    _notify(db, {'kind': CHAT_TURN_WAKE_KIND, 'session_id': session_id, 'turn_id': turn_id})
    db.commit()
    return turn_id


def _claim_batch(db: Session, *, generation: int, limit: int) -> list[TurnClaim]:
    rows = db.execute(
        select(ChatTurn, ChatSession)
        .join(ChatSession, col(ChatSession.id) == col(ChatTurn.session_id))
        .where(
            or_(
                col(ChatTurn.status) == 'queued',
                and_(
                    col(ChatTurn.status) == 'awaiting_confirmation',
                    or_(col(ChatTurn.confirmation_decision).is_not(None), col(ChatTurn.stop_requested).is_(True)),
                ),
            ),
            col(ChatTurn.claim_token).is_(None),
        )
        .order_by(col(ChatTurn.created_at), col(ChatTurn.id))
        .limit(limit)
        .with_for_update(of=ChatTurn, skip_locked=True)
    ).all()
    claims: list[TurnClaim] = []
    for turn, session in rows:
        claim_token = secrets.token_urlsafe(24)
        turn.claim_token = claim_token
        turn.coordinator_generation = generation
        turn.updated_at = datetime.now(UTC)
        if turn.status == 'queued':
            turn.status = 'running'
        claims.append(
            TurnClaim(
                id=turn.id,
                session_id=turn.session_id,
                user_id=turn.user_id,
                content=turn.content,
                tool_ids=tuple(turn.tool_ids),
                namespace=turn.namespace,
                session_token=decrypt_secret(turn.session_token_encrypted),
                provider=session.provider,
                model=session.model,
                api_key=decrypt_secret(session.api_key),
                system_prompt=session.system_prompt,
                checkpoint=dict(turn.checkpoint),
                claim_token=claim_token,
                coordinator_generation=generation,
                confirmation_decision=turn.confirmation_decision,
            )
        )
    db.commit()
    return claims


def _recover(db: Session, *, generation: int) -> int:
    turns = (
        db.execute(
            select(ChatTurn)
            .where(
                col(ChatTurn.status).in_(ACTIVE_TURN_STATUSES),
                (col(ChatTurn.coordinator_generation).is_(None)) | (col(ChatTurn.coordinator_generation) < generation),
            )
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    recovered = 0
    for turn in turns:
        phase = turn.checkpoint.get('phase')
        turn.claim_token = None
        turn.coordinator_generation = None
        turn.updated_at = datetime.now(UTC)
        if turn.status == 'queued' or phase == 'tool_ready':
            turn.status = 'queued'
            recovered += 1
            continue
        if turn.status == 'awaiting_confirmation':
            recovered += 1
            continue
        turn.status = 'interrupted'
        _append_event(
            db,
            session_id=turn.session_id,
            turn_id=turn.id,
            payload={'type': 'error', 'content': 'Generation interrupted by coordinator restart'},
        )
        _append_event(db, session_id=turn.session_id, turn_id=turn.id, payload={'type': 'done'})
        recovered += 1
    db.commit()
    return recovered


def _control_state(db: Session, *, turn_id: str, claim_token: str, generation: int) -> tuple[bool, bool | None]:
    turn = _verify_claim(db, turn_id, claim_token, generation)
    return turn.stop_requested, turn.confirmation_decision


def _set_checkpoint(
    db: Session,
    *,
    turn_id: str,
    claim_token: str,
    generation: int,
    checkpoint: dict[str, Any],
    status: str | None = None,
    clear_confirmation: bool = False,
) -> None:
    turn = _verify_claim(db, turn_id, claim_token, generation)
    turn.checkpoint = checkpoint
    turn.updated_at = datetime.now(UTC)
    if status is not None:
        turn.status = status
    if clear_confirmation:
        turn.confirmation_decision = None
    db.add(turn)
    db.commit()


def _write_message(
    db: Session,
    *,
    turn_id: str,
    claim_token: str,
    generation: int,
    message: dict[str, Any],
) -> None:
    turn = _verify_claim(db, turn_id, claim_token, generation)
    _append_message(db, session_id=turn.session_id, turn_id=turn.id, message=message)
    db.commit()


def _write_event(
    db: Session,
    *,
    turn_id: str,
    claim_token: str,
    generation: int,
    payload: dict[str, Any],
) -> int:
    turn = _verify_claim(db, turn_id, claim_token, generation)
    sequence = _append_event(db, session_id=turn.session_id, turn_id=turn.id, payload=payload)
    db.commit()
    return sequence


def _finish(db: Session, *, turn_id: str, claim_token: str, generation: int, status: str) -> None:
    turn = _verify_claim(db, turn_id, claim_token, generation)
    turn.status = status
    turn.claim_token = None
    turn.coordinator_generation = None
    turn.updated_at = datetime.now(UTC)
    _append_event(db, session_id=turn.session_id, turn_id=turn.id, payload={'type': 'done'})
    db.commit()


def _request_stop(db: Session, *, session_id: str, user_id: str) -> bool:
    turn = db.execute(
        select(ChatTurn)
        .where(col(ChatTurn.session_id) == session_id, col(ChatTurn.user_id) == user_id, col(ChatTurn.status).in_(ACTIVE_TURN_STATUSES))
        .with_for_update()
    ).scalar_one_or_none()
    if turn is None:
        return False
    turn.stop_requested = True
    turn.updated_at = datetime.now(UTC)
    _notify(db, {'kind': CHAT_TURN_WAKE_KIND, 'session_id': session_id, 'turn_id': turn.id})
    db.commit()
    return True


def _confirm(db: Session, *, session_id: str, user_id: str, approved: bool) -> bool:
    turn = db.execute(
        select(ChatTurn)
        .where(
            col(ChatTurn.session_id) == session_id,
            col(ChatTurn.user_id) == user_id,
            col(ChatTurn.status) == 'awaiting_confirmation',
            col(ChatTurn.confirmation_decision).is_(None),
        )
        .with_for_update()
    ).scalar_one_or_none()
    if turn is None:
        return False
    turn.confirmation_decision = approved
    turn.updated_at = datetime.now(UTC)
    _notify(db, {'kind': CHAT_TURN_WAKE_KIND, 'session_id': session_id, 'turn_id': turn.id})
    db.commit()
    return True


def _read_events(db: Session, *, session_id: str, after: int, limit: int) -> tuple[list[ChatEvent], int, int | None]:
    latest = int(db.execute(select(func.max(col(ChatEvent.sequence))).where(col(ChatEvent.session_id) == session_id)).scalar_one_or_none() or 0)
    oldest = db.execute(select(func.min(col(ChatEvent.sequence))).where(col(ChatEvent.session_id) == session_id)).scalar_one_or_none()
    rows = (
        db.execute(
            select(ChatEvent).where(col(ChatEvent.session_id) == session_id, col(ChatEvent.sequence) > after).order_by(col(ChatEvent.sequence)).limit(limit)
        )
        .scalars()
        .all()
    )
    return list(rows), latest, int(oldest) if oldest is not None else None


class ChatTurnStore:
    """Synchronous database boundary used by API routes and the coordinator."""

    def enqueue(self, *, session_id: str, user_id: str, content: str, tool_ids: list[str], namespace: str, session_token: str) -> str:
        return run_settings_db(
            _enqueue, session_id=session_id, user_id=user_id, content=content, tool_ids=tool_ids, namespace=namespace, session_token=session_token
        )

    def claim_batch(self, *, generation: int, limit: int) -> list[TurnClaim]:
        return run_settings_db(_claim_batch, generation=generation, limit=limit)

    def recover(self, *, generation: int) -> int:
        return run_settings_db(_recover, generation=generation)

    def release_confirmation(self, *, turn_id: str, claim_token: str, generation: int) -> None:
        def release(db: Session) -> None:
            turn = _verify_claim(db, turn_id, claim_token, generation)
            if turn.status != 'awaiting_confirmation':
                raise RuntimeError('Chat turn is not awaiting confirmation')
            turn.claim_token = None
            db.commit()

        run_settings_db(release)

    def control_state(self, *, turn_id: str, claim_token: str, generation: int) -> tuple[bool, bool | None]:
        return run_settings_db(_control_state, turn_id=turn_id, claim_token=claim_token, generation=generation)

    def set_checkpoint(
        self, *, turn_id: str, claim_token: str, generation: int, checkpoint: dict[str, Any], status: str | None = None, clear_confirmation: bool = False
    ) -> None:
        run_settings_db(
            _set_checkpoint,
            turn_id=turn_id,
            claim_token=claim_token,
            generation=generation,
            checkpoint=checkpoint,
            status=status,
            clear_confirmation=clear_confirmation,
        )

    def append_message(self, *, turn_id: str, claim_token: str, generation: int, message: dict[str, Any]) -> None:
        run_settings_db(_write_message, turn_id=turn_id, claim_token=claim_token, generation=generation, message=message)

    def append_event(self, *, turn_id: str, claim_token: str, generation: int, payload: dict[str, Any]) -> int:
        return run_settings_db(_write_event, turn_id=turn_id, claim_token=claim_token, generation=generation, payload=payload)

    def finish(self, *, turn_id: str, claim_token: str, generation: int, status: str) -> None:
        run_settings_db(_finish, turn_id=turn_id, claim_token=claim_token, generation=generation, status=status)

    def request_stop(self, *, session_id: str, user_id: str) -> bool:
        return run_settings_db(_request_stop, session_id=session_id, user_id=user_id)

    def confirm(self, *, session_id: str, user_id: str, approved: bool) -> bool:
        return run_settings_db(_confirm, session_id=session_id, user_id=user_id, approved=approved)

    def read_events(self, *, session_id: str, after: int, limit: int = 100) -> tuple[list[ChatEvent], int, int | None]:
        return run_settings_db(_read_events, session_id=session_id, after=after, limit=limit)


chat_turn_store = ChatTurnStore()


def _latest_session_events(session_ids: list[str]) -> dict[str, int]:
    if not session_ids:
        return {}
    rows = run_settings_db(
        lambda db: db.execute(
            select(col(ChatEvent.session_id), func.max(col(ChatEvent.sequence)))
            .where(col(ChatEvent.session_id).in_(session_ids))
            .group_by(col(ChatEvent.session_id))
        ).all()
    )
    return {str(session_id): int(sequence) for session_id, sequence in rows if sequence is not None}


class ChatStreamRecovery:
    """Multicast local wakeups with one indexed recovery query per API process."""

    recovery_seconds = 5.0

    def __init__(self) -> None:
        self.hub = KeyedVersionHub()
        self._subscribers: dict[str, int] = {}
        self._known_sequences: dict[str, int] = {}
        self._task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake_event: asyncio.Event | None = None

    def subscribe(self, session_id: str) -> None:
        self._subscribers[session_id] = self._subscribers.get(session_id, 0) + 1
        self.wake()

    def unsubscribe(self, session_id: str) -> None:
        count = self._subscribers.get(session_id, 0)
        if count <= 1:
            self._subscribers.pop(session_id, None)
            self._known_sequences.pop(session_id, None)
            return
        self._subscribers[session_id] = count - 1

    def publish(self, session_id: str, sequence: int | None = None) -> None:
        if sequence is not None and session_id in self._subscribers:
            self._known_sequences[session_id] = max(sequence, self._known_sequences.get(session_id, 0))
        self.hub.publish(session_id)

    def version(self, session_id: str) -> int:
        return self.hub.version(session_id)

    async def wait(self, session_id: str, last_seen: int) -> int:
        return await self.hub.wait(session_id, last_seen)

    def wake(self) -> None:
        if self._loop is not None and self._wake_event is not None:
            self._loop.call_soon_threadsafe(self._wake_event.set)

    async def run(self, stop_event: asyncio.Event) -> None:
        if self._task is not None and not self._task.done():
            raise RuntimeError('Chat stream recovery is already running')
        self._task = asyncio.current_task()
        self._loop = asyncio.get_running_loop()
        self._wake_event = asyncio.Event()
        try:
            while not stop_event.is_set():
                self._wake_event.clear()
                session_ids = list(self._subscribers)
                try:
                    latest = await asyncio.to_thread(_latest_session_events, session_ids)
                    for session_id in session_ids:
                        sequence = latest.get(session_id, 0)
                        if sequence > self._known_sequences.get(session_id, 0):
                            self.publish(session_id, sequence)
                        else:
                            self._known_sequences.setdefault(session_id, sequence)
                except Exception:
                    # A lost recovery pass is bounded by the next shared pass.
                    logger.warning('Chat event recovery query failed', exc_info=True)
                wake_task = asyncio.create_task(self._wake_event.wait())
                stop_task = asyncio.create_task(stop_event.wait())
                _done, pending = await asyncio.wait({wake_task, stop_task}, timeout=self.recovery_seconds, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(wake_task, stop_task, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        finally:
            self._task = None
            self._loop = None
            self._wake_event = None
            self._subscribers.clear()
            self._known_sequences.clear()
            await self.hub.clear()


chat_stream_recovery = ChatStreamRecovery()
