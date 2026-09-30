from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session

from backend_core.exceptions import AppError, DataSourceValidationError
from backend_core.persistence.datasource.models import DataSource
from modules.datasource.schemas import DataSourceResponse, DataSourceUpdate
from modules.datasource.service import update_datasource
from tests.harness.postgres_harness import wait_for_condition


def _insert_datasource(session: Session) -> str:
    datasource_id = str(uuid4())
    session.add(
        DataSource(
            id=datasource_id,
            name='Concurrent revision',
            source_type='file',
            config={'file_path': 's3://default/uploads/revisions.xlsx', 'file_type': 'excel'},
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    session.commit()
    return datasource_id


def test_expected_revision_refreshes_an_already_loaded_row(test_db_session: Session, test_engine: Engine) -> None:
    datasource_id = _insert_datasource(test_db_session)
    cached = test_db_session.get(DataSource, datasource_id)
    assert cached is not None and cached.revision == 1
    with Session(test_engine) as writer:
        current = writer.get(DataSource, datasource_id)
        assert current is not None
        current.config = {**current.config, 'annotation': 'committed by another session'}
        current.revision = 2
        writer.commit()

    assert cached.revision == 1
    with pytest.raises(DataSourceValidationError, match='changed while Excel selection was being resolved'):
        update_datasource(
            test_db_session,
            datasource_id,
            DataSourceUpdate(config={'sheet_name': 'Stale'}),
            resolved_excel_selection=('Stale', 0, 0, 0, 10),
            expected_revision=1,
        )
    test_db_session.rollback()
    test_db_session.refresh(cached)
    assert cached.revision == 2
    assert cached.config['annotation'] == 'committed by another session'
    assert 'sheet_name' not in cached.config


def test_update_rechecks_pending_delete_on_an_already_loaded_row(test_db_session: Session, test_engine: Engine) -> None:
    datasource_id = _insert_datasource(test_db_session)
    cached = test_db_session.get(DataSource, datasource_id)
    assert cached is not None and not cached.is_pending_delete
    with Session(test_engine) as writer:
        current = writer.get(DataSource, datasource_id)
        assert current is not None
        current.is_pending_delete = True
        writer.commit()

    assert not cached.is_pending_delete
    with pytest.raises(AppError, match=f'DataSource {datasource_id} not found'):
        update_datasource(test_db_session, datasource_id, DataSourceUpdate(name='Must not update a tombstone'))
    test_db_session.rollback()
    test_db_session.refresh(cached)
    assert cached.is_pending_delete
    assert cached.name == 'Concurrent revision'
    assert cached.revision == 1


@pytest.mark.parametrize('expected_revision', [1, None])
def test_postgres_update_serializes_revision_check_and_write(
    test_db_session: Session,
    test_engine: Engine,
    expected_revision: int | None,
) -> None:
    if test_engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL row locks are required for the concurrent revision regression')
    datasource_id = _insert_datasource(test_db_session)
    started = threading.Event()
    writer_pid: list[int] = []

    def update_after_locked_snapshot() -> DataSourceResponse:
        with Session(test_engine) as writer:
            writer_pid.append(int(writer.execute(text('SELECT pg_backend_pid()')).scalar_one()))
            started.set()
            return update_datasource(
                writer,
                datasource_id,
                DataSourceUpdate(config={'sheet_name': 'Resolved'}),
                resolved_excel_selection=('Resolved', 0, 0, 0, 10),
                expected_revision=expected_revision,
            )

    with Session(test_engine) as first_writer, ThreadPoolExecutor(max_workers=1, thread_name_prefix='datasource-revision') as pool:
        first_pid = int(first_writer.execute(text('SELECT pg_backend_pid()')).scalar_one())
        current = first_writer.get(DataSource, datasource_id, with_for_update=True)
        assert current is not None
        current.config = {**current.config, 'annotation': 'concurrent change'}
        current.revision = 2
        result = pool.submit(update_after_locked_snapshot)
        try:
            assert started.wait(timeout=5)

            def writer_is_blocked() -> bool:
                with test_engine.connect() as observer:
                    blockers = observer.execute(text('SELECT pg_blocking_pids(:pid)'), {'pid': writer_pid[0]}).scalar_one()
                return first_pid in blockers

            wait_for_condition(writer_is_blocked, timeout=5, interval=0.01, description='second datasource writer to wait for the first transaction')
            first_writer.commit()
            if expected_revision is not None:
                with pytest.raises(DataSourceValidationError, match='changed while Excel selection was being resolved'):
                    result.result(timeout=5)
            else:
                response = result.result(timeout=5)
                assert response.config['annotation'] == 'concurrent change'
                assert response.config['sheet_name'] == 'Resolved'
        finally:
            first_writer.rollback()

    test_db_session.expire_all()
    stored = test_db_session.get(DataSource, datasource_id)
    assert stored is not None
    assert stored.config['annotation'] == 'concurrent change'
    assert stored.revision == (2 if expected_revision is not None else 3)
    assert ('sheet_name' in stored.config) == (expected_revision is None)
