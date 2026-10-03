from __future__ import annotations

import asyncio
import threading
import time
from io import BytesIO
from typing import cast

import pytest
from fastapi import HTTPException, UploadFile

from modules.datasource import routes


@pytest.mark.asyncio
async def test_cancelled_staging_joins_late_upload_then_deletes_only_its_target(monkeypatch: pytest.MonkeyPatch) -> None:
    upload_started = threading.Event()
    finish_upload = threading.Event()
    accepted_source = 's3://analytics/uploads/accepted.csv'
    objects: set[str] = {accepted_source}
    deleted: list[str] = []
    target_url = 's3://analytics/uploads/unique.csv'
    intent_operations: list[str] = []
    intent_expiry = 0.0
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
            intent_expiry = time.monotonic() + 0.03
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
        await asyncio.sleep(0.07)  # Exceed the initial intent TTL while S3 is still blocked.
        assert not staging.done()
        assert not upload.file.closed
        assert intent_expiry > time.monotonic()
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
    deleted: list[str] = []
    source_path = 's3://analytics/uploads/staged.csv'

    async def create_datasource(**_kwargs):
        creation_started.set()
        await finish_creation.wait()
        if not creation_succeeds:
            raise RuntimeError('durable datasource creation failed')
        return object()

    async def delete_object(path: str) -> None:
        deleted.append(path)

    monkeypatch.setattr(routes, 'create_remote_file_datasource', create_datasource)
    monkeypatch.setattr(routes, '_delete_managed_object', delete_object)
    creation = asyncio.create_task(
        routes._create_uploaded_datasource(
            runtime_probe=cast(routes.RuntimeAvailabilityProbe, object()),
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

    assert deleted == []


@pytest.mark.asyncio
async def test_failed_response_after_datasource_publication_never_deletes_referenced_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    source_path = 's3://analytics/uploads/published.csv'
    published_paths: set[str] = set()
    deleted: list[str] = []

    async def stage_upload(_file, _target_name: str) -> str:
        return source_path

    async def publish_then_lose_response(**_kwargs):
        published_paths.add(source_path)
        raise RuntimeError('completion response was lost after publication')

    async def delete_object(path: str) -> None:
        deleted.append(path)
        published_paths.discard(path)

    monkeypatch.setattr(routes, '_stage_upload_to_object_store', stage_upload)
    monkeypatch.setattr(routes, 'create_remote_file_datasource', publish_then_lose_response)
    monkeypatch.setattr(routes, '_delete_managed_object', delete_object)

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
            runtime_probe=cast(routes.RuntimeAvailabilityProbe, object()),
        )

    assert raised.value.status_code == 500
    assert published_paths == {source_path}
    assert deleted == []
