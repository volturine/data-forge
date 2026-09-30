"""Durable chat session configuration and transcript reads."""

from __future__ import annotations

import math
import secrets
import time
from typing import Any

from sqlalchemy import func, select
from sqlmodel import Session as DbSession

from backend_core.database import get_settings_engine, run_settings_db
from backend_core.secrets import encrypt_secret
from backend_core.sqlmodel_typing import col
from modules.chat.models import ChatEvent, ChatMessage, ChatSession

MAX_EVENTS = 500
MAX_MESSAGES = 100
SECOND_EPOCH_THRESHOLD = 10_000_000_000


def normalize_epoch_milliseconds(value: Any) -> int | None:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    epoch_ms = value * 1000 if abs(value) < SECOND_EPOCH_THRESHOLD else value
    return int(round(epoch_ms))


def _session(db: DbSession, session_id: str, *, user_id: str | None = None) -> ChatSession | None:
    statement = select(ChatSession).where(col(ChatSession.id) == session_id)
    if user_id is not None:
        statement = statement.where(col(ChatSession.user_id) == user_id)
    return db.execute(statement).scalar_one_or_none()


def _create_session(
    db: DbSession,
    provider: str,
    model: str,
    api_key: str,
    system_prompt: str,
    user_id: str | None,
) -> ChatSession:
    row = ChatSession(
        id=secrets.token_urlsafe(16),
        user_id=user_id,
        provider=provider,
        model=model,
        api_key=encrypt_secret(api_key),
        system_prompt=system_prompt,
        created_at=time.time(),
    )
    db.add(row)
    if system_prompt:
        db.flush()
        db.add(ChatMessage(session_id=row.id, message={'role': 'system', 'content': system_prompt}))
    db.commit()
    db.refresh(row)
    return row


class SessionStore:
    """Persist configuration in PostgreSQL; never cache mutable session state."""

    def create(
        self,
        provider: str,
        model: str,
        api_key: str,
        system_prompt: str = '',
        *,
        user_id: str | None = None,
    ) -> ChatSession:
        return run_settings_db(_create_session, provider, model, api_key, system_prompt, user_id)

    def get(self, session_id: str, *, user_id: str | None = None) -> ChatSession | None:
        with DbSession(get_settings_engine()) as db:
            return _session(db, session_id, user_id=user_id)

    def update(
        self,
        session_id: str,
        *,
        user_id: str,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        system_prompt: str | None = None,
    ) -> ChatSession | None:
        with DbSession(get_settings_engine()) as db:
            row = _session(db, session_id, user_id=user_id)
            if row is None:
                return None
            if provider is not None:
                row.provider = provider
            if model is not None:
                row.model = model
            if api_key is not None:
                row.api_key = encrypt_secret(api_key)
            if system_prompt is not None:
                row.system_prompt = system_prompt
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

    def delete(self, session_id: str, *, user_id: str) -> bool:
        with DbSession(get_settings_engine()) as db:
            row = _session(db, session_id, user_id=user_id)
            if row is None:
                return False
            db.delete(row)
            db.commit()
            return True

    def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        with DbSession(get_settings_engine()) as db:
            rows = db.execute(select(ChatSession).where(col(ChatSession.user_id) == user_id).order_by(col(ChatSession.created_at).desc())).scalars().all()
            result: list[dict[str, Any]] = []
            for row in rows:
                first_user_message = (
                    db.execute(select(col(ChatMessage.message)).where(col(ChatMessage.session_id) == row.id).order_by(col(ChatMessage.sequence)))
                    .scalars()
                    .all()
                )
                preview = next(
                    (str(item.get('content', ''))[:100] for item in first_user_message if item.get('role') == 'user'),
                    '',
                )
                result.append(
                    {
                        'id': row.id,
                        'model': row.model,
                        'provider': row.provider,
                        'created_at': normalize_epoch_milliseconds(row.created_at) or 0,
                        'preview': preview,
                    }
                )
            return result

    def history(self, session_id: str) -> tuple[list[dict[str, Any]], int, bool]:
        with DbSession(get_settings_engine()) as db:
            latest = db.execute(select(func.max(col(ChatEvent.sequence))).where(col(ChatEvent.session_id) == session_id)).scalar_one_or_none()
            cursor = int(latest or 0)
            rows = (
                db.execute(select(ChatEvent).where(col(ChatEvent.session_id) == session_id).order_by(col(ChatEvent.sequence).desc()).limit(MAX_EVENTS))
                .scalars()
                .all()
            )
            rows = list(reversed(rows))
            first = rows[0].sequence if rows else cursor
            gap = bool(rows and int(first or 0) > 1)
            history = []
            for row in rows:
                event = dict(row.payload)
                event['ts'] = normalize_epoch_milliseconds(event.get('ts')) or int(row.created_at.timestamp() * 1000)
                history.append(event)
            return history, cursor, gap

    def messages(self, session_id: str) -> list[dict[str, Any]]:
        with DbSession(get_settings_engine()) as db:
            return list(
                db.execute(select(col(ChatMessage.message)).where(col(ChatMessage.session_id) == session_id).order_by(col(ChatMessage.sequence)))
                .scalars()
                .all()
            )


session_store = SessionStore()
