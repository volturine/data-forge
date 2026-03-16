"""Chat session store — DB-persisted sessions with in-memory event queues."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections.abc import AsyncIterator
from typing import Any

from sqlmodel import Field, Session as DbSession, SQLModel, select

logger = logging.getLogger(__name__)

MAX_EVENTS = 500
MAX_MESSAGES = 100


class ChatSession(SQLModel, table=True):
    """Persisted chat session row."""

    __tablename__ = 'chat_sessions'  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    provider: str = Field(default='openrouter')
    model: str = Field(default='')
    api_key: str = Field(default='')
    messages_json: str = Field(default='[]')
    history_json: str = Field(default='[]')
    created_at: float = Field(default_factory=time.time)
    system_prompt: str = Field(default='')


class LiveSession:
    """Runtime wrapper around a persisted ChatSession row."""

    def __init__(self, row: ChatSession) -> None:
        self.id = row.id
        self.provider = row.provider
        self.model = row.model
        self.api_key = row.api_key
        self.system_prompt = row.system_prompt
        self.messages: list[dict[str, Any]] = json.loads(row.messages_json)
        self.created_at = row.created_at
        self._history: list[dict[str, Any]] = json.loads(row.history_json)
        self._queue: asyncio.Queue[dict | None] = asyncio.Queue()
        self._closed = False
        self._busy = False
        self._lock = asyncio.Lock()

    @property
    def busy(self) -> bool:
        return self._busy

    async def acquire_turn(self) -> bool:
        """Atomically check and set busy. Returns True if acquired."""
        async with self._lock:
            if self._busy:
                return False
            self._busy = True
            return True

    async def set_busy(self, value: bool) -> None:
        async with self._lock:
            self._busy = value

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({'role': role, 'content': content})
        if len(self.messages) > MAX_MESSAGES:
            system = [m for m in self.messages if m.get('role') == 'system']
            non_system = [m for m in self.messages if m.get('role') != 'system']
            self.messages = system + non_system[-(MAX_MESSAGES - len(system)) :]

    def push_event(self, event: dict) -> None:
        if 'ts' not in event:
            event = {**event, 'ts': time.time() * 1000}
        self._history.append(event)
        if len(self._history) > MAX_EVENTS:
            self._history = self._history[-MAX_EVENTS:]
        if not self._closed:
            self._queue.put_nowait(event)

    def close_stream(self) -> None:
        self._closed = True
        self._queue.put_nowait(None)

    def reopen_stream(self) -> None:
        self._closed = False
        drained: list[dict] = []
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                if item is not None:
                    drained.append(item)
            except asyncio.QueueEmpty:
                break
        for item in drained:
            self._queue.put_nowait(item)

    def get_history(self) -> list[dict[str, Any]]:
        return list(self._history)

    async def events(self) -> AsyncIterator[dict]:
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event


class SessionStore:
    """DB-persisted session store with in-memory live sessions."""

    TTL = 3600

    def __init__(self) -> None:
        self._live: dict[str, LiveSession] = {}

    def _db(self) -> DbSession:
        from core.database import settings_engine

        return DbSession(settings_engine)

    def create(self, provider: str, model: str, api_key: str, system_prompt: str = '') -> LiveSession:
        sid = secrets.token_urlsafe(16)
        now = time.time()
        initial_messages: list[dict[str, Any]] = []
        if system_prompt:
            initial_messages.append({'role': 'system', 'content': system_prompt})
        row = ChatSession(
            id=sid,
            provider=provider,
            model=model,
            api_key=api_key,
            system_prompt=system_prompt,
            messages_json=json.dumps(initial_messages),
            history_json='[]',
            created_at=now,
        )
        with self._db() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
        live = LiveSession(row)
        self._live[sid] = live
        return live

    def get(self, session_id: str) -> LiveSession | None:
        live = self._live.get(session_id)
        if live:
            if time.time() - live.created_at > self.TTL:
                self.delete(session_id)
                return None
            return live
        with self._db() as db:
            row = db.exec(select(ChatSession).where(ChatSession.id == session_id)).first()
            if not row:
                return None
            if time.time() - row.created_at > self.TTL:
                db.delete(row)
                db.commit()
                return None
            live = LiveSession(row)
            self._live[session_id] = live
            return live

    def flush(self, session_id: str) -> None:
        live = self._live.get(session_id)
        if not live:
            return
        with self._db() as db:
            row = db.get(ChatSession, session_id)
            if not row:
                return
            row.model = live.model
            row.api_key = live.api_key
            row.system_prompt = live.system_prompt
            row.messages_json = json.dumps(live.messages)
            row.history_json = json.dumps(live._history)
            db.add(row)
            db.commit()

    def delete(self, session_id: str) -> bool:
        live = self._live.pop(session_id, None)
        if live:
            live.close_stream()
        with self._db() as db:
            row = db.get(ChatSession, session_id)
            if not row:
                return live is not None
            db.delete(row)
            db.commit()
        return True

    def list_sessions(self) -> list[dict]:
        """List all sessions with preview info."""
        now = time.time()
        sessions = []
        with self._db() as db:
            rows = db.exec(select(ChatSession)).all()
            for row in rows:
                if now - row.created_at > self.TTL:
                    continue
                messages: list[dict[str, Any]] = json.loads(row.messages_json)
                preview = ''
                for m in messages:
                    if m.get('role') == 'user':
                        preview = m.get('content', '')[:100]
                        break
                sessions.append(
                    {
                        'id': row.id,
                        'model': row.model,
                        'provider': row.provider,
                        'created_at': row.created_at,
                        'preview': preview,
                    }
                )
        return sorted(sessions, key=lambda s: s['created_at'], reverse=True)

    def sweep(self) -> None:
        now = time.time()
        expired = [k for k, v in self._live.items() if now - v.created_at > self.TTL]
        for k in expired:
            self.delete(k)


session_store = SessionStore()
