from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from backend_core.config import settings
from backend_core.namespace import normalize_namespace
from backend_core.persistence.namespaces.models import RuntimeNamespace


def register_namespace(session: Session, namespace: str | None) -> RuntimeNamespace:
    name = normalize_namespace(namespace)
    existing = session.get(RuntimeNamespace, name)
    now = datetime.now(UTC).replace(tzinfo=None)
    if existing is not None:
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
        return existing
    session.refresh(record)
    return record


def list_runtime_namespaces(session: Session) -> list[str]:
    rows = session.exec(select(RuntimeNamespace.name).order_by(RuntimeNamespace.name)).all()
    names = {normalize_namespace(row) for row in rows}
    names.add(settings.default_namespace)
    return sorted(names)
