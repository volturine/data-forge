"""PostgreSQL-backed, one-use MCP confirmation actions shared by API workers."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

from sqlalchemy import delete, func
from sqlmodel import Session, select

from backend_core.database import run_settings_db
from backend_core.persistence.mcp_pending.models import McpPendingAction
from backend_core.secrets import decrypt_secret, encrypt_secret
from modules.mcp.models import MCPHttpMethod


@dataclass(frozen=True, slots=True)
class PendingEntry:
    tool_id: str
    method: MCPHttpMethod
    path: str
    args: dict[str, Any]
    namespace: str
    created_at: datetime
    owner_id: str


def _database_now(session: Session) -> datetime:
    value = session.execute(select(func.current_timestamp())).scalar_one()
    if not isinstance(value, datetime):
        raise TypeError('Database CURRENT_TIMESTAMP did not return a datetime')
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _token_hash(token: str) -> str:
    return sha256(token.encode('utf-8')).hexdigest()


def _decode_args(encrypted: str) -> dict[str, Any]:
    value = json.loads(decrypt_secret(encrypted))
    if not isinstance(value, dict):
        raise ValueError('Pending MCP action arguments are not an object')
    return value


def _entry(action: McpPendingAction) -> PendingEntry:
    return PendingEntry(
        tool_id=action.tool_id,
        method=MCPHttpMethod.require(action.method),
        path=action.path,
        args=_decode_args(action.args_encrypted),
        namespace=action.namespace,
        created_at=action.created_at,
        owner_id=action.owner_id,
    )


def _create_action(
    session: Session,
    *,
    token_hash: str,
    tool_id: str,
    method: MCPHttpMethod,
    path: str,
    args: dict[str, Any],
    namespace: str,
    owner_id: str,
    ttl_seconds: int,
) -> None:
    now = _database_now(session)
    table = McpPendingAction.metadata.tables[McpPendingAction.__tablename__]
    session.execute(delete(McpPendingAction).where(table.c.expires_at <= now))
    session.add(
        McpPendingAction(
            token_hash=token_hash,
            owner_id=owner_id,
            tool_id=tool_id,
            method=method.value,
            path=path,
            namespace=namespace,
            args_encrypted=encrypt_secret(json.dumps(args, ensure_ascii=False, separators=(',', ':'))),
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
    )
    session.commit()


def _get_action(session: Session, *, token_hash: str, owner_id: str) -> PendingEntry | None:
    now = _database_now(session)
    table = McpPendingAction.metadata.tables[McpPendingAction.__tablename__]
    action = session.execute(
        select(McpPendingAction).where(
            table.c.token_hash == token_hash,
            table.c.owner_id == owner_id,
            table.c.expires_at > now,
        )
    ).scalar_one_or_none()
    return _entry(action) if action is not None else None


def _consume_action(session: Session, *, token_hash: str, owner_id: str) -> PendingEntry | None:
    now = _database_now(session)
    table = McpPendingAction.metadata.tables[McpPendingAction.__tablename__]
    row = session.execute(
        delete(McpPendingAction)
        .where(
            table.c.token_hash == token_hash,
            table.c.owner_id == owner_id,
            table.c.expires_at > now,
        )
        .returning(McpPendingAction)
    ).scalar_one_or_none()
    entry = _entry(row) if row is not None else None
    session.commit()
    return entry


class PendingStore:
    """Persist confirmation state so any API replica can consume it once."""

    ttl_seconds = 300

    def create(
        self,
        tool_id: str,
        method: str | MCPHttpMethod,
        path: str,
        args: dict[str, Any],
        *,
        namespace: str,
        owner_id: str,
    ) -> str:
        token = secrets.token_urlsafe(24)
        run_settings_db(
            _create_action,
            token_hash=_token_hash(token),
            tool_id=tool_id,
            method=MCPHttpMethod.require(method),
            path=path,
            args=args,
            namespace=namespace,
            owner_id=owner_id,
            ttl_seconds=self.ttl_seconds,
        )
        return token

    def pop(self, token: str, *, owner_id: str) -> PendingEntry | None:
        return run_settings_db(_consume_action, token_hash=_token_hash(token), owner_id=owner_id)

    def get(self, token: str, *, owner_id: str) -> PendingEntry | None:
        return run_settings_db(_get_action, token_hash=_token_hash(token), owner_id=owner_id)


pending_store = PendingStore()
