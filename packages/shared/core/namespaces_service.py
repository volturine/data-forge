from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from contracts.namespaces.models import RuntimeNamespace
from core.config import settings
from core.namespace import normalize_namespace


def register_namespace(session: Session, namespace: str | None) -> RuntimeNamespace:
    name = normalize_namespace(namespace)
    existing = session.get(RuntimeNamespace, name)
    now = datetime.now(UTC).replace(tzinfo=None)
    if existing is not None:
        existing.updated_at = now
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing
    record = RuntimeNamespace(name=name, created_at=now, updated_at=now)
    session.add(record)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.get(RuntimeNamespace, name)
        if existing is None:
            raise
        existing.updated_at = now
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing
    session.refresh(record)
    return record


def list_runtime_namespaces(session: Session) -> list[str]:
    rows = session.exec(select(RuntimeNamespace.name).order_by(RuntimeNamespace.name)).all()
    names = {normalize_namespace(row) for row in rows}
    names.add(settings.default_namespace)
    return sorted(names)
