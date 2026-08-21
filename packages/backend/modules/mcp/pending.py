"""MCP pending-action store — holds preview tokens awaiting confirmation."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any

from modules.mcp.models import MCPHttpMethod


@dataclass(slots=True)
class PendingEntry:
    tool_id: str
    method: MCPHttpMethod
    path: str
    args: dict[str, Any]
    context: dict[str, Any]
    created_at: float
    owner_id: str


class PendingStore:
    """In-memory store for pending MCP tool call tokens."""

    TTL = 300

    def __init__(self) -> None:
        self._store: dict[str, PendingEntry] = {}

    def create(
        self,
        tool_id: str,
        method: str | MCPHttpMethod,
        path: str,
        args: dict[str, Any],
        context: dict[str, Any] | None = None,
        *,
        owner_id: str,
    ) -> str:
        token = secrets.token_urlsafe(24)
        self._store[token] = PendingEntry(
            tool_id=tool_id,
            method=MCPHttpMethod.require(method),
            path=path,
            args=dict(args),
            context=dict(context or {}),
            created_at=time.time(),
            owner_id=owner_id,
        )
        return token

    def pop(self, token: str, *, owner_id: str) -> PendingEntry | None:
        entry = self.get(token, owner_id=owner_id)
        if entry is None:
            return None
        self._store.pop(token, None)
        return entry

    def get(self, token: str, *, owner_id: str) -> PendingEntry | None:
        entry = self._store.get(token)
        if entry is None:
            return None
        if time.time() - entry.created_at > self.TTL:
            self._store.pop(token, None)
            return None
        if entry.owner_id != owner_id:
            return None
        return entry

    def sweep(self) -> None:
        now = time.time()
        expired = [t for t, e in self._store.items() if now - e.created_at > self.TTL]
        for t in expired:
            self._store.pop(t, None)


pending_store = PendingStore()
