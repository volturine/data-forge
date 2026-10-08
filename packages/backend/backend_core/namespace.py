from __future__ import annotations

from contextvars import ContextVar, Token

from backend_core.config import settings
from backend_core.namespace_storage import validate_namespace_name

_NAMESPACE = ContextVar('namespace', default='')
_PUBLIC_NAMESPACE_DATABASE_SCHEMA = 'df$tenant$public'


def normalize_namespace(value: str | None) -> str:
    raw = (value or '').strip()
    if not raw:
        return settings.default_namespace
    return validate_namespace_name(raw)


def namespace_database_schema(value: str | None) -> str:
    name = normalize_namespace(value)
    if name == 'public':
        return _PUBLIC_NAMESPACE_DATABASE_SCHEMA
    return name


def set_namespace_context(value: str | None) -> Token:
    return _NAMESPACE.set(normalize_namespace(value))


def reset_namespace(token: Token) -> None:
    _NAMESPACE.reset(token)


def get_namespace() -> str:
    current = _NAMESPACE.get()
    if current:
        return current
    return settings.default_namespace
