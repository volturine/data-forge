from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from modules.compute import executor_client
from modules.datasource import routes
from modules.datasource.preflight import ExcelPreflight


@pytest.mark.asyncio
async def test_cancelled_staging_joins_late_upload_then_deletes_only_its_target(monkeypatch: pytest.MonkeyPatch) -> None:
    upload_started = threading.Event()
    finish_upload = threading.Event()
    accepted_source = 's3://analytics/uploads/accepted.csv'
    objects: set[str] = {accepted_source}
    deleted: list[str] = []
    target_url = 's3://analytics/uploads/unique.csv'
    intent_operations: list[str] = []
    intent_now = 0.0
    intent_expiry = 0.0
    intent_clock = threading.Lock()
    intent_renewed = threading.Event()
    cleanup_eligible = False

    class DataPlane:
        def build_object_url(self, *_parts: str, namespace: str) -> str:
            assert namespace == 'analytics'
            return target_url

        def upload_object_fileobj(self, source, target: str, *, max_bytes: int) -> str:
            assert max_bytes > 0
            assert intent_operations == ['register_upload_source']
            upload_started.set()
            assert finish_upload.wait(timeout=5)
            source.seek(0)
            assert source.read() == b'staged content'
            objects.add(target)
            return target

        def delete_object(self, target: str) -> None:
            deleted.append(target)
            objects.discard(target)

    def run_db(operation, **kwargs) -> None:
        nonlocal intent_expiry, cleanup_eligible
        del kwargs
        intent_operations.append(operation.__name__)
        if operation.__name__ in {'register_upload_source', 'renew_upload_source', 'complete_upload_source'}:
            with intent_clock:
                intent_expiry = intent_now + 0.03
                if operation.__name__ == 'renew_upload_source':
                    intent_renewed.set()
        elif operation.__name__ == 'release_upload_source_for_cleanup':
            cleanup_eligible = True

    monkeypatch.setattr(routes, 'client_from_settings', DataPlane)
    monkeypatch.setattr(routes, 'get_namespace', lambda: 'analytics')
    monkeypatch.setattr(routes, 'run_db', run_db)
    monkeypatch.setattr(routes, '_UPLOAD_INTENT_RENEW_SECONDS', 0.01)

    upload = UploadFile(file=BytesIO(b'staged content'), filename='input.csv')
    staging = asyncio.create_task(routes._stage_upload_to_object_store(upload, 'unique.csv'))
    try:
        assert await asyncio.to_thread(upload_started.wait, 2)
        staging.cancel()
        # Cross the initial TTL while observing each renewal, without tying the
        # simulated lease's validity to the loaded runner's scheduling latency.
        for tick in range(1, 8):
            with intent_clock:
                intent_renewed.clear()
                intent_now = tick * 0.01
                assert intent_expiry > intent_now
            assert await asyncio.to_thread(intent_renewed.wait, 2)
            with intent_clock:
                assert intent_expiry > intent_now
        assert not staging.done()
        assert not upload.file.closed
        assert intent_expiry > intent_now
        assert intent_operations.count('renew_upload_source') >= 1
        assert not cleanup_eligible

        finish_upload.set()
        with pytest.raises(asyncio.CancelledError):
            await staging
    finally:
        finish_upload.set()
        await asyncio.gather(staging, return_exceptions=True)

    assert not upload.file.closed
    assert objects == {accepted_source, target_url}
    assert deleted == []
    assert cleanup_eligible
    assert intent_operations[0] == 'register_upload_source'
    assert intent_operations[-1] == 'release_upload_source_for_cleanup'


@pytest.mark.parametrize('creation_succeeds', [True, False])
@pytest.mark.asyncio
async def test_cancelled_upload_joins_creation_and_leaves_source_to_durable_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    creation_succeeds: bool,
) -> None:
    creation_started = asyncio.Event()
    finish_creation = asyncio.Event()
    source_path = 's3://analytics/uploads/staged.csv'

    async def create_datasource(**_kwargs):
        creation_started.set()
        await finish_creation.wait()
        if not creation_succeeds:
            raise RuntimeError('durable datasource creation failed')
        return object()

    monkeypatch.setattr(routes, 'create_remote_file_datasource', create_datasource)
    creation = asyncio.create_task(
        routes._create_uploaded_datasource(
            name='staged',
            description=None,
            file_path=source_path,
            file_type='csv',
            csv_options=None,
            owner_id=None,
        )
    )

    await asyncio.wait_for(creation_started.wait(), timeout=1)
    creation.cancel()
    await asyncio.sleep(0)
    assert not creation.done()

    finish_creation.set()
    with pytest.raises(asyncio.CancelledError):
        await creation


@pytest.mark.asyncio
async def test_failed_datasource_creation_returns_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    source_path = 's3://analytics/uploads/published.csv'
    staged_paths: list[str] = []

    async def stage_upload(_file, _target_name: str) -> str:
        staged_paths.append(source_path)
        return source_path

    async def fail_creation(**_kwargs):
        raise RuntimeError('datasource creation failed')

    async def compute_available() -> None:
        return None

    monkeypatch.setattr(routes, 'require_compute_available', compute_available)
    monkeypatch.setattr(routes, '_stage_upload_to_object_store', stage_upload)
    monkeypatch.setattr(routes, 'create_remote_file_datasource', fail_creation)

    with pytest.raises(HTTPException) as raised:
        await routes.upload_file(
            file=UploadFile(file=BytesIO(b'name\nvalue\n'), filename='data.csv'),
            name='published',
            delimiter=',',
            quote_char='"',
            has_header=True,
            skip_rows=0,
            encoding='utf8',
            user=None,
        )

    assert raised.value.status_code == 500
    assert staged_paths == [source_path]


@pytest.mark.asyncio
async def test_upload_is_refused_before_staging_when_compute_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def stage_upload(_file, _target_name: str) -> str:
        raise AssertionError('an upload compute cannot read must not be copied to object storage')

    monkeypatch.setattr(executor_client, '_worker_manager_recently_seen', _no_worker_manager)
    monkeypatch.setattr(routes, '_stage_upload_to_object_store', stage_upload)

    with pytest.raises(HTTPException) as raised:
        await routes.upload_file(
            file=UploadFile(file=BytesIO(b'name\nvalue\n'), filename='data.csv'),
            name='published',
            delimiter=',',
            quote_char='"',
            has_header=True,
            skip_rows=0,
            encoding='utf8',
            user=None,
        )
    assert raised.value.status_code == 503

    with pytest.raises(HTTPException) as raised:
        await routes.preflight_excel(file=UploadFile(file=BytesIO(b'PK\x03\x04' + b'\x00' * 8), filename='book.xlsx'))
    assert raised.value.status_code == 503


@pytest.mark.asyncio
async def test_confirm_keeps_the_staged_preflight_when_compute_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    cleared: list[tuple[str, bool]] = []
    preflight_id = str(uuid.uuid4())

    async def get_preflight(_preflight_id: str) -> ExcelPreflight:
        return ExcelPreflight(
            source_path='s3://analytics/uploads/book.xlsx',
            sheets=['Sheet1'],
            tables={},
            named_ranges=[],
            created_at=datetime.now(UTC),
            delete_source=True,
        )

    async def clear_preflight(cleared_id: str, *, delete_source: bool = True) -> None:
        cleared.append((cleared_id, delete_source))

    monkeypatch.setattr(executor_client, '_worker_manager_recently_seen', _no_worker_manager)
    monkeypatch.setattr(routes, 'get_preflight', get_preflight)
    monkeypatch.setattr(routes, 'clear_preflight', clear_preflight)

    with pytest.raises(HTTPException) as raised:
        await routes.confirm_excel(
            preflight_id=preflight_id,
            name='book',
            description=None,
            sheet_name=None,
            start_row=0,
            start_col=0,
            end_col=0,
            end_row=None,
            has_header=True,
            table_name=None,
            named_range=None,
            cell_range=None,
            user=SimpleNamespace(id='user-1'),
        )

    assert raised.value.status_code == 503
    # The retry needs the preflight and its source; expiry still owns cleanup.
    assert cleared == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('create_error', 'keeps_preflight'),
    [
        # Refused before staging, or staged and then retired because the
        # manager went away (both raise ComputeUnavailableError). The create
        # never takes over the source, so the preflight still owns it for a
        # retry, and the retired create cannot complete late.
        pytest.param(executor_client.ComputeUnavailableError(), True, id='compute-unavailable'),
        # The create ran and failed; the preflight is spent.
        pytest.param(HTTPException(status_code=400, detail='Selected range is empty'), False, id='create-failed'),
    ],
)
async def test_confirm_keeps_the_preflight_only_when_compute_was_unavailable(
    monkeypatch: pytest.MonkeyPatch, create_error: HTTPException, keeps_preflight: bool
) -> None:
    cleared: list[tuple[str, bool]] = []
    preflight_id = str(uuid.uuid4())

    async def get_preflight(_preflight_id: str) -> ExcelPreflight:
        return ExcelPreflight(
            source_path='s3://analytics/uploads/book.xlsx',
            sheets=['Sheet1'],
            tables={},
            named_ranges=[],
            created_at=datetime.now(UTC),
            delete_source=True,
        )

    async def clear_preflight(cleared_id: str, *, delete_source: bool = True) -> None:
        cleared.append((cleared_id, delete_source))

    async def resolve_selection(**_kwargs) -> dict[str, object]:
        return {'sheet_name': 'Sheet1', 'start_row': 0, 'start_col': 0, 'end_col': 1, 'detected_end_row': 9}

    async def create_datasource(**_kwargs):
        raise create_error

    monkeypatch.setattr(routes, 'get_preflight', get_preflight)
    monkeypatch.setattr(routes, 'clear_preflight', clear_preflight)
    monkeypatch.setattr(routes, 'execute_excel_preflight', resolve_selection)
    monkeypatch.setattr(routes, 'create_remote_file_datasource', create_datasource)

    with pytest.raises(HTTPException) as raised:
        await routes.confirm_excel(
            preflight_id=preflight_id,
            name='book',
            description=None,
            sheet_name=None,
            start_row=0,
            start_col=0,
            end_col=0,
            end_row=None,
            has_header=True,
            table_name=None,
            named_range=None,
            cell_range=None,
            user=SimpleNamespace(id='user-1'),
        )

    assert raised.value.status_code == create_error.status_code
    assert cleared == ([] if keeps_preflight else [(preflight_id, True)])


async def _no_worker_manager() -> bool:
    return False
