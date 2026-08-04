from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path

from backend_core.config import settings
from backend_core.namespace_storage import is_valid_namespace_name, validate_namespace_name

_NAMESPACE = ContextVar('namespace', default='')
_PUBLIC_NAMESPACE_DATABASE_SCHEMA = 'df$tenant$public'


@dataclass(frozen=True)
class NamespacePaths:
    base_dir: Path
    upload_dir: Path
    clean_dir: Path
    exports_dir: Path
    db_path: Path


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


def namespace_paths(namespace: str | None = None) -> NamespacePaths:
    name = normalize_namespace(namespace) if namespace is not None else get_namespace()
    base_dir = settings.data_dir / 'namespaces' / name
    upload_dir = base_dir / 'uploads'
    clean_dir = base_dir / 'clean'
    exports_dir = base_dir / 'exports'
    db_path = base_dir / 'namespace.db'
    for path in (base_dir, upload_dir, clean_dir, exports_dir):
        path.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return NamespacePaths(base_dir=base_dir, upload_dir=upload_dir, clean_dir=clean_dir, exports_dir=exports_dir, db_path=db_path)


def list_namespaces() -> list[str]:
    base_dir = settings.data_dir / 'namespaces'
    if not base_dir.exists():
        return []
    entries = [
        entry.name
        for entry in base_dir.iterdir()
        if entry.is_dir() and is_valid_namespace_name(entry.name) and entry.name != 'logs'
    ]
    return sorted(entries)
