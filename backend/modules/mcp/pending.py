"""MCP pending-action store — holds preview tokens awaiting confirmation."""

from __future__ import annotations

import secrets
import time
from typing import Any


class PendingStore:
    """In-memory store for pending MCP tool call tokens."""

    TTL = 300

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def create(self, tool_id: str, method: str, path: str, args: dict, context: dict[str, Any] | None = None) -> str:
        token = secrets.token_urlsafe(24)
        self._store[token] = {
            'tool_id': tool_id,
            'method': method,
            'path': path,
            'args': args,
            'context': context or {},
            'created_at': time.time(),
        }
        return token

    def pop(self, token: str) -> dict | None:
        entry = self._store.pop(token, None)
        if entry is None:
            return None
        if time.time() - entry['created_at'] > self.TTL:
            return None
        return entry

    def get(self, token: str) -> dict | None:
        entry = self._store.get(token)
        if entry is None:
            return None
        if time.time() - entry['created_at'] > self.TTL:
            self._store.pop(token, None)
            return None
        return entry

    def sweep(self) -> None:
        now = time.time()
        expired = [t for t, e in self._store.items() if now - e['created_at'] > self.TTL]
        for t in expired:
            self._store.pop(t, None)


pending_store = PendingStore()
