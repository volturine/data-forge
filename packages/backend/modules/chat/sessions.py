"""Chat session store — DB-persisted sessions with in-memory event queues."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections.abc import AsyncIterator
from typing import Any

from core.secrets import decrypt_secret, encrypt_secret
from sqlmodel import Session as DbSession
from sqlmodel import select

from modules.chat.models import ChatSession

logger = logging.getLogger(__name__)

MAX_EVENTS = 500
MAX_MESSAGES = 100


class LiveSession:
    """Runtime wrapper around a persisted ChatSession row."""

    def __init__(self, row: ChatSession) -> None:
        self.id = row.id
        self.provider = row.provider
        self.model = row.model
        self.api_key = decrypt_secret(row.api_key)
        self.system_prompt = row.system_prompt
        self.messages: list[dict[str, Any]] = json.loads(row.messages_json)
        self.created_at = row.created_at
        self.last_activity = time.time()
        self._history: list[dict[str, Any]] = json.loads(row.history_json)
        self._queue: asyncio.Queue[dict | None] = asyncio.Queue()
        self._closed = False
        self._busy = False
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._confirm_event: asyncio.Event | None = None
        self._confirm_approved: bool = False

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

    def set_task(self, task: asyncio.Task[None]) -> None:
        self._task = task

    def cancel_task(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            self._task = None

    async def wait_for_confirm(self) -> bool:
        """Block until user confirms or denies. Returns True if approved."""
        self._confirm_event = asyncio.Event()
        self._confirm_approved = False
        await self._confirm_event.wait()
        self._confirm_event = None
        return self._confirm_approved

    def resolve_confirm(self, approved: bool) -> None:
        """Resolve a pending confirmation."""
        self._confirm_approved = approved
        if self._confirm_event:
            self._confirm_event.set()

    def _trim_messages(self) -> None:
        if len(self.messages) <= MAX_MESSAGES:
            return
        system = [m for m in self.messages if m.get("role") == "system"]
        non_system = [m for m in self.messages if m.get("role") != "system"]
        self.messages = system + non_system[-(MAX_MESSAGES - len(system)) :]

    def add_message(self, role: str, content: str) -> None:
        self.last_activity = time.time()
        self.messages.append({"role": role, "content": content})
        self._trim_messages()

    def append_message(self, msg: dict[str, Any]) -> None:
        self.last_activity = time.time()
        self.messages.append(msg)
        self._trim_messages()

    def push_event(self, event: dict) -> None:
        self.last_activity = time.time()
        if "ts" not in event:
            event = {**event, "ts": time.time() * 1000}
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

    MEMORY_TTL = 3600  # evict idle in-memory wrappers after 1 hour

    def __init__(self) -> None:
        self._live: dict[str, LiveSession] = {}

    def _db(self) -> DbSession:
        from core.database import get_settings_engine

        return DbSession(get_settings_engine())

    def create(self, provider: str, model: str, api_key: str, system_prompt: str = "") -> LiveSession:
        sid = secrets.token_urlsafe(16)
        now = time.time()
        initial_messages: list[dict[str, Any]] = []
        if system_prompt:
            initial_messages.append({"role": "system", "content": system_prompt})
        row = ChatSession(
            id=sid,
            provider=provider,
            model=model,
            api_key=encrypt_secret(api_key),
            system_prompt=system_prompt,
            messages_json=json.dumps(initial_messages),
            history_json="[]",
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
            return live
        with self._db() as db:
            row = db.exec(select(ChatSession).where(ChatSession.id == session_id)).first()
            if not row:
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
            row.api_key = encrypt_secret(live.api_key)
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
        sessions = []
        with self._db() as db:
            rows = db.exec(select(ChatSession)).all()
            for row in rows:
                messages: list[dict[str, Any]] = json.loads(row.messages_json)
                preview = ""
                for m in messages:
                    if m.get("role") == "user":
                        preview = m.get("content", "")[:100]
                        break
                sessions.append(
                    {
                        "id": row.id,
                        "model": row.model,
                        "provider": row.provider,
                        "created_at": row.created_at,
                        "preview": preview,
                    },
                )
        return sorted(sessions, key=lambda s: s["created_at"], reverse=True)

    def sweep(self) -> None:
        """Evict idle in-memory wrappers to free resources. DB rows are preserved."""
        now = time.time()
        expired = [k for k, v in self._live.items() if now - v.last_activity > self.MEMORY_TTL and not v.busy]
        for k in expired:
            live = self._live.pop(k, None)
            if live:
                live.close_stream()


session_store = SessionStore()
