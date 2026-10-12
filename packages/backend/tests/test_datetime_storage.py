from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import DateTime
from sqlalchemy.engine import Engine
from sqlmodel import Session

from backend_core.persistence.locks.models import ResourceLock
from backend_core.persistence.namespaces.models import NamespaceEngineCredential, RuntimeNamespace
from backend_core.persistence.runtime_events.models import RuntimeOutboxEvent
from backend_core.persistence.runtime_workers.models import RuntimeWorker


def test_namespace_default_timestamps_persist_as_utc_naive(isolate_settings_engine: Engine) -> None:
    before = datetime.now(UTC).replace(tzinfo=None)
    namespace = RuntimeNamespace(name=f'datetime-storage-{uuid4().hex}')
    credential = NamespaceEngineCredential(
        id=uuid4().hex,
        namespace=namespace.name,
        role='reader',
        access_key=uuid4().hex,
        secret_key_encrypted='encrypted-test-secret',
    )
    after = datetime.now(UTC).replace(tzinfo=None)

    with Session(isolate_settings_engine) as session:
        assert before <= namespace.created_at <= after
        assert before <= namespace.updated_at <= after
        assert before <= credential.created_at <= after

        session.add(namespace)
        session.add(credential)
        session.commit()
        session.refresh(namespace)
        session.refresh(credential)

        assert namespace.created_at.tzinfo is None
        assert namespace.updated_at.tzinfo is None
        assert credential.created_at.tzinfo is None
        assert before <= namespace.created_at <= after
        assert before <= namespace.updated_at <= after
        assert before <= credential.created_at <= after


def test_datetime_column_metadata_preserves_timezone_boundaries() -> None:
    naive_columns = (
        cast(Any, RuntimeNamespace).__table__.c.created_at,
        cast(Any, RuntimeNamespace).__table__.c.updated_at,
        cast(Any, NamespaceEngineCredential).__table__.c.created_at,
    )
    aware_columns = (
        cast(Any, ResourceLock).__table__.c.acquired_at,
        cast(Any, ResourceLock).__table__.c.expires_at,
        cast(Any, RuntimeOutboxEvent).__table__.c.available_at,
        cast(Any, RuntimeWorker).__table__.c.started_at,
    )

    assert all(isinstance(column.type, DateTime) and column.type.timezone is False for column in naive_columns)
    assert all(isinstance(column.type, DateTime) and column.type.timezone is True for column in aware_columns)
