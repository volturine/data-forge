import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.datasource import preflight


@pytest.mark.asyncio
async def test_delete_source_offloads_object_store_and_filesystem_work(monkeypatch, tmp_path: Path) -> None:
    loop_thread = threading.get_ident()
    factory_threads: list[int] = []
    operation_threads: list[int] = []
    local_file = tmp_path / 'upload.xlsx'
    local_file.write_bytes(b'workbook')

    class DataPlane:
        def classify_object_url(self, _path: str) -> SimpleNamespace:
            operation_threads.append(threading.get_ident())
            return SimpleNamespace(is_managed=False)

    def create_data_plane() -> DataPlane:
        factory_threads.append(threading.get_ident())
        return DataPlane()

    original_unlink = Path.unlink

    def unlink(path: Path, *, missing_ok: bool = False) -> None:
        operation_threads.append(threading.get_ident())
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(preflight, 'client_from_settings', create_data_plane)
    monkeypatch.setattr(Path, 'unlink', unlink)

    await preflight._delete_source(str(local_file), delete_source=True)

    assert not local_file.exists()
    assert factory_threads and all(thread_id != loop_thread for thread_id in factory_threads)
    assert operation_threads and all(thread_id != loop_thread for thread_id in operation_threads)
