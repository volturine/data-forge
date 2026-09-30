from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlmodel import Session

from backend_core.persistence.runtime_events.models import RuntimeCoordinatorState
from backend_core.persistence.settings.models import AppSettings
from backend_core.persistence.telegram.models import TelegramDetectionRequest, TelegramPollOffset
from backend_core.secrets import decrypt_secret, encrypt_secret
from backend_core.sqlmodel_typing import col, sa
from modules.telegram.domain import TelegramDetectionClaim, TelegramDetectionResult, TelegramSettings

_RUNTIME_CHANNEL = 'runtime_events'
_DETECTION_WAKE_KIND = 'telegram_detection'
MAX_PENDING_DETECTIONS = 32
DETECTION_TIMEOUT_SECONDS = 20


class TelegramOwnerFenced(RuntimeError):
    pass


class DetectionQueueFull(RuntimeError):
    pass


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def read_settings(session: Session) -> TelegramSettings:
    row = session.get(AppSettings, 1)
    if row is None:
        return TelegramSettings(enabled=False, token='')
    stored_token = row.telegram_bot_token or ''
    token = decrypt_secret(stored_token) if stored_token else ''
    return TelegramSettings(enabled=bool(row.telegram_bot_enabled and token), token=token)


def get_next_update_id(session: Session, fingerprint: str) -> int:
    offset = session.get(TelegramPollOffset, fingerprint)
    return offset.next_update_id if offset is not None else 0


def observed_chats(session: Session, fingerprint: str) -> list[dict[str, str]]:
    row = session.get(TelegramPollOffset, fingerprint)
    return list(row.chats_json) if row is not None else []


def advance_update_id(session: Session, *, fingerprint: str, next_update_id: int, generation: int, chats: list[dict[str, str]]) -> None:
    if next_update_id < 0:
        raise ValueError('Telegram update offset cannot be negative')
    require_generation(session, generation)
    row = session.get(TelegramPollOffset, fingerprint)
    now = datetime.now(UTC)
    if row is None:
        session.add(
            TelegramPollOffset(
                token_sha256=fingerprint,
                next_update_id=next_update_id,
                chats_json=chats[-10:],
                coordinator_generation=generation,
                updated_at=now,
            )
        )
    else:
        row.next_update_id = max(row.next_update_id, next_update_id)
        by_chat = {chat['chat_id']: chat for chat in row.chats_json}
        for chat in chats:
            by_chat.pop(chat['chat_id'], None)
            by_chat[chat['chat_id']] = chat
        row.chats_json = list(by_chat.values())[-10:]
        row.coordinator_generation = generation
        row.updated_at = now
        session.add(row)
    session.commit()


def enqueue_detection(
    session: Session,
    *,
    token: str,
    request_user_id: str,
    namespace: str,
) -> str:
    session.execute(select(RuntimeCoordinatorState).where(sa(RuntimeCoordinatorState.singleton_id == 1)).with_for_update()).scalar_one()
    now = datetime.now(UTC)
    pending = session.execute(
        select(func.count())
        .select_from(TelegramDetectionRequest)
        .where(col(TelegramDetectionRequest.status).in_(('pending', 'running')))
        .where(sa(TelegramDetectionRequest.deadline_at > now))
    ).scalar_one()
    if int(pending) >= MAX_PENDING_DETECTIONS:
        raise DetectionQueueFull('Telegram chat detection is busy; try again shortly')

    request_id = secrets.token_urlsafe(24)
    request = TelegramDetectionRequest(
        id=request_id,
        token_encrypted=encrypt_secret(token),
        token_sha256=token_fingerprint(token),
        request_user_id=request_user_id,
        namespace=namespace,
        status='pending',
        owner_generation=0,
        deadline_at=now + timedelta(seconds=DETECTION_TIMEOUT_SECONDS),
        created_at=now,
        updated_at=now,
    )
    session.add(request)
    session.flush()
    if session.get_bind().dialect.name == 'postgresql':
        session.execute(
            text('SELECT pg_notify(:channel, :payload)'),
            {
                'channel': _RUNTIME_CHANNEL,
                'payload': json.dumps({'kind': _DETECTION_WAKE_KIND, 'request_id': request_id}, separators=(',', ':')),
            },
        )
    session.commit()
    return request_id


def recover_detection_requests(session: Session, *, generation: int) -> None:
    require_generation(session, generation)
    now = datetime.now(UTC)
    expired = session.execute(
        select(TelegramDetectionRequest)
        .where(col(TelegramDetectionRequest.status).in_(('pending', 'running')))
        .where(sa(TelegramDetectionRequest.deadline_at <= now))
        .with_for_update()
    ).scalars()
    for request in expired:
        request.status = 'timed_out'
        request.token_encrypted = ''
        request.error = 'Telegram chat detection deadline expired'
        request.updated_at = now
        session.add(request)

    abandoned = session.execute(
        select(TelegramDetectionRequest)
        .where(sa(TelegramDetectionRequest.status == 'running'))
        .where(sa(TelegramDetectionRequest.owner_generation < generation))
        .with_for_update()
    ).scalars()
    for request in abandoned:
        request.status = 'pending'
        request.owner_generation = 0
        request.updated_at = now
        session.add(request)
    session.commit()


def claim_detection(session: Session, *, generation: int) -> TelegramDetectionClaim | None:
    require_generation(session, generation)
    now = datetime.now(UTC)
    request = session.execute(
        select(TelegramDetectionRequest)
        .where(sa(TelegramDetectionRequest.status == 'pending'))
        .where(sa(TelegramDetectionRequest.deadline_at > now))
        .order_by(col(TelegramDetectionRequest.created_at), col(TelegramDetectionRequest.id))
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if request is None:
        session.rollback()
        return None
    request.status = 'running'
    request.owner_generation = generation
    request.updated_at = now
    token = decrypt_secret(request.token_encrypted)
    claim = TelegramDetectionClaim(
        request_id=request.id,
        token=token,
        token_sha256=request.token_sha256,
        request_user_id=request.request_user_id,
        namespace=request.namespace,
        owner_generation=generation,
        deadline_at=request.deadline_at,
    )
    session.add(request)
    session.commit()
    return claim


def complete_detection(
    session: Session,
    *,
    claim: TelegramDetectionClaim,
    result: dict[str, object],
) -> bool:
    require_generation(session, claim.owner_generation)
    request = session.execute(
        select(TelegramDetectionRequest)
        .where(sa(TelegramDetectionRequest.id == claim.request_id))
        .where(sa(TelegramDetectionRequest.owner_generation == claim.owner_generation))
        .where(sa(TelegramDetectionRequest.status == 'running'))
        .with_for_update()
    ).scalar_one_or_none()
    if request is None:
        session.rollback()
        return False
    now = datetime.now(UTC)
    if request.deadline_at <= now:
        request.status = 'timed_out'
        request.error = 'Telegram chat detection deadline expired'
    else:
        request.status = 'completed'
        request.result_json = result
        request.error = None
    request.token_encrypted = ''
    request.updated_at = now
    session.add(request)
    session.commit()
    return True


def fail_detection(session: Session, *, claim: TelegramDetectionClaim, error: str) -> bool:
    require_generation(session, claim.owner_generation)
    request = session.execute(
        select(TelegramDetectionRequest)
        .where(sa(TelegramDetectionRequest.id == claim.request_id))
        .where(sa(TelegramDetectionRequest.owner_generation == claim.owner_generation))
        .where(sa(TelegramDetectionRequest.status == 'running'))
        .with_for_update()
    ).scalar_one_or_none()
    if request is None:
        session.rollback()
        return False
    expired = request.deadline_at <= datetime.now(UTC)
    request.status = 'timed_out' if expired else 'failed'
    request.error = 'Telegram detection deadline expired' if expired else error[:500]
    request.token_encrypted = ''
    request.updated_at = datetime.now(UTC)
    session.add(request)
    session.commit()
    return True


def get_detection_result(session: Session, *, request_id: str, request_user_id: str) -> TelegramDetectionResult | None:
    request = session.get(TelegramDetectionRequest, request_id)
    if request is None or request.request_user_id != request_user_id:
        return None
    return TelegramDetectionResult(
        status=request.status,
        result=request.result_json,
        error=request.error,
        deadline_at=request.deadline_at,
    )


def time_out_detection(session: Session, *, request_id: str, request_user_id: str) -> None:
    request = session.execute(
        select(TelegramDetectionRequest)
        .where(sa(TelegramDetectionRequest.id == request_id))
        .where(sa(TelegramDetectionRequest.request_user_id == request_user_id))
        .where(col(TelegramDetectionRequest.status).in_(('pending', 'running')))
        .with_for_update()
    ).scalar_one_or_none()
    if request is None:
        session.rollback()
        return
    request.status = 'timed_out'
    request.token_encrypted = ''
    request.error = 'Telegram chat detection deadline expired'
    request.updated_at = datetime.now(UTC)
    session.add(request)
    session.commit()


def require_generation(session: Session, generation: int) -> None:
    current = session.execute(
        select(col(RuntimeCoordinatorState.generation)).where(sa(RuntimeCoordinatorState.singleton_id == 1)).with_for_update(read=True)
    ).scalar_one_or_none()
    if current is None or int(current) != generation:
        raise TelegramOwnerFenced('Telegram coordinator generation is fenced')
