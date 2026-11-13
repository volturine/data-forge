import logging
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from backend_core.config import settings
from backend_core.namespace import normalize_namespace
from backend_core.namespace_storage import is_valid_namespace_name
from backend_core.persistence.namespaces.models import RuntimeNamespace

logger = logging.getLogger(__name__)


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


def runtime_namespace_exists(session: Session, namespace: str | None) -> bool:
    """Return whether a namespace has crossed the runtime publication fence."""
    return session.get(RuntimeNamespace, normalize_namespace(namespace)) is not None


def list_runtime_namespaces(session: Session) -> list[str]:
    rows = session.exec(select(RuntimeNamespace.name).order_by(RuntimeNamespace.name)).all()
    # Rows registered before the bucket-name rules (e.g. with underscores) are
    # not served. Skip them so startup and namespace iteration keep working.
    invalid = [row for row in rows if not is_valid_namespace_name(row)]
    if invalid:
        logger.warning('Skipping registered namespaces with invalid names: %s', ', '.join(repr(row) for row in invalid))
    names = {row for row in rows if is_valid_namespace_name(row)}
    names.add(settings.default_namespace)
    return sorted(names)
