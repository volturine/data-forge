from __future__ import annotations

import asyncio
import threading
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile

from modules.datasource import routes


@pytest.mark.asyncio
async def test_cancelled_staging_joins_late_upload_then_deletes_only_its_target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    upload_started = threading.Event()
    finish_upload = threading.Event()
    accepted_source = 's3://analytics/uploads/accepted.csv'
    objects: set[str] = {accepted_source}
    deleted: list[str] = []
    staged_path = tmp_path / 'staged.csv'
    target_url = 's3://analytics/uploads/unique.csv'

    class DataPlane:
        def build_object_url(self, *_parts: str, namespace: str) -> str:
            assert namespace == 'analytics'
            return target_url

        def upload_object_file(self, path: Path, target: str, *, max_bytes: int) -> str:
            assert path.exists()
            assert max_bytes > 0
            upload_started.set()
            assert finish_upload.wait(timeout=5)
            objects.add(target)
            return target

        def delete_object(self, target: str) -> None:
            deleted.append(target)
            objects.discard(target)

    async def save_upload(_file, path: Path, _max_bytes: int) -> None:
        path.write_bytes(b'staged content')

    monkeypatch.setattr(routes, '_temporary_upload_path', lambda _suffix: staged_path)
    monkeypatch.setattr(routes, '_save_upload_file', save_upload)
    monkeypatch.setattr(routes, 'client_from_settings', DataPlane)
    monkeypatch.setattr(routes, 'get_namespace', lambda: 'analytics')

    staging = asyncio.create_task(routes._stage_upload_to_object_store(UploadFile(file=BytesIO(), filename='input.csv'), 'unique.csv'))
    try:
        assert await asyncio.to_thread(upload_started.wait, 2)
        staging.cancel()
        await asyncio.sleep(0)

        assert not staging.done()
        assert staged_path.exists()

        finish_upload.set()
        with pytest.raises(asyncio.CancelledError):
            await staging
    finally:
        finish_upload.set()
        await asyncio.gather(staging, return_exceptions=True)

    assert not staged_path.exists()
    assert objects == {accepted_source}
    assert deleted == [target_url]
