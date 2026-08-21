"""Excel-bounds updates on datasources must read workbooks from object storage."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

from openpyxl import Workbook
from sqlmodel import Session

from backend_core.persistence.datasource.models import DataSource
from modules.datasource import service as datasource_service
from modules.datasource.schemas import DataSourceUpdate


class _Classification:
    def __init__(self, is_object_store: bool) -> None:
        self.is_object_store = is_object_store
        self.is_managed = is_object_store


class _FakeDataPlane:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.downloaded: list[str] = []

    def classify_object_url(self, value: str):
        return _Classification(value.startswith('s3://'))

    def download_object_bytes(self, source_url: str) -> bytes:
        self.downloaded.append(source_url)
        return self.payload


def _workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet['A1'] = 'name'
    sheet['A2'] = 'alice'
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _insert_excel_datasource(session: Session, *, datasource_id: str, file_path: str, file_type: str) -> DataSource:
    ds = DataSource(
        id=datasource_id,
        name=datasource_id,
        description=None,
        source_type='file',
        config={'file_path': file_path, 'file_type': file_type},
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds


def test_update_resolves_bounds_via_object_store_download(
    test_db_session: Session,
    monkeypatch,
) -> None:
    datasource_id = '22222222-2222-4222-8222-000000000001'
    file_url = 's3://dataforge/uploads/bounds.xlsx'
    fake = _FakeDataPlane(_workbook_bytes())
    monkeypatch.setattr(datasource_service, 'client_from_settings', lambda: fake)
    _insert_excel_datasource(
        test_db_session,
        datasource_id=datasource_id,
        file_path=file_url,
        file_type='excel',
    )

    response = datasource_service.update_datasource(
        test_db_session,
        datasource_id,
        DataSourceUpdate(config={'sheet_name': 'Sheet'}),
    )

    assert fake.downloaded == [file_url]
    assert response.config['sheet_name'] == 'Sheet'
    assert response.config['end_row'] == 1
    row = test_db_session.get(DataSource, datasource_id)
    assert row is not None
    assert row.config['end_row'] == 1


def test_update_resolves_bounds_for_local_file_without_download(
    test_db_session: Session,
    tmp_path: Path,
    monkeypatch,
) -> None:
    datasource_id = '22222222-2222-4222-8222-000000000002'
    local_file = tmp_path / 'bounds.xlsx'
    local_file.write_bytes(_workbook_bytes())
    fake = _FakeDataPlane(b'')
    monkeypatch.setattr(datasource_service, 'client_from_settings', lambda: fake)
    _insert_excel_datasource(
        test_db_session,
        datasource_id=datasource_id,
        file_path=str(local_file),
        file_type='excel',
    )

    response = datasource_service.update_datasource(
        test_db_session,
        datasource_id,
        DataSourceUpdate(config={'sheet_name': 'Sheet'}),
    )

    assert fake.downloaded == []
    assert response.config['end_row'] == 1
