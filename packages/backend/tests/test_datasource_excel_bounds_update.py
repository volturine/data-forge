"""Excel bounds updates consume selections resolved by the compute worker."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session

from backend_core.persistence.datasource.models import DataSource
from modules.datasource import routes as datasource_routes, service as datasource_service
from modules.datasource.preflight import resolved_selection
from modules.datasource.schemas import DataSourceUpdate


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


def test_update_uses_worker_resolved_bounds_for_object_store_source(
    test_db_session: Session,
) -> None:
    datasource_id = '22222222-2222-4222-8222-000000000001'
    file_url = 's3://dataforge/uploads/bounds.xlsx'
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
        resolved_excel_selection=resolved_selection(
            {
                'sheet_name': 'Sheet',
                'start_row': 0,
                'start_col': 0,
                'end_col': 0,
                'detected_end_row': 1,
            }
        ),
    )

    assert response.config['sheet_name'] == 'Sheet'
    assert response.config['end_row'] == 1
    assert response.config['file_path'] == file_url
    row = test_db_session.get(DataSource, datasource_id)
    assert row is not None
    assert row.config['end_row'] == 1


def test_update_uses_worker_resolved_bounds_for_local_file(
    test_db_session: Session,
    tmp_path: Path,
) -> None:
    datasource_id = '22222222-2222-4222-8222-000000000002'
    local_file = tmp_path / 'bounds.xlsx'
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
        resolved_excel_selection=resolved_selection(
            {
                'sheet_name': 'Sheet',
                'start_row': 0,
                'start_col': 0,
                'end_col': 0,
                'detected_end_row': 1,
            }
        ),
    )

    assert response.config['end_row'] == 1
    assert response.config['file_path'] == str(local_file)


def test_put_resolves_excel_bounds_on_worker_and_preserves_source(
    client,
    test_db_session: Session,
    monkeypatch,
) -> None:
    datasource_id = '22222222-2222-4222-8222-000000000003'
    file_url = 's3://dataforge/uploads/route-bounds.xlsx'
    _insert_excel_datasource(test_db_session, datasource_id=datasource_id, file_path=file_url, file_type='excel')
    calls: list[dict[str, object]] = []

    async def resolve(_session, **kwargs):
        calls.append(kwargs)
        return {
            'sheet_name': 'Sheet',
            'start_row': 0,
            'start_col': 0,
            'end_col': 2,
            'detected_end_row': 17,
        }

    monkeypatch.setattr(datasource_routes, 'execute_excel_preflight', resolve)
    response = client.put(f'/api/v1/datasource/{datasource_id}', json={'config': {'sheet_name': 'Sheet'}})

    assert response.status_code == 200
    assert response.json()['config']['end_row'] == 17
    assert response.json()['config']['file_path'] == file_url
    assert len(calls) == 1
    assert calls[0]['preflight_id'] != datasource_id
    assert calls[0]['source_path'] == file_url
    assert calls[0]['datasource_id'] == datasource_id
    assert calls[0]['action'] == datasource_routes.enums_pb2.DATASOURCE_PREFLIGHT_ACTION_RESOLVE_SELECTION
    assert calls[0]['selection'] == {'sheet_name': 'Sheet', 'has_header': True}
    assert calls[0]['delete_source'] is False


def test_put_rejects_excel_update_when_revision_changes_during_resolution(
    client,
    test_db_session: Session,
    monkeypatch,
) -> None:
    datasource_id = '22222222-2222-4222-8222-000000000004'
    _insert_excel_datasource(
        test_db_session,
        datasource_id=datasource_id,
        file_path='s3://dataforge/uploads/stale-bounds.xlsx',
        file_type='excel',
    )

    async def resolve(_session, **_kwargs):
        datasource = test_db_session.get(DataSource, datasource_id)
        assert datasource is not None
        datasource.revision += 1
        test_db_session.add(datasource)
        test_db_session.commit()
        return {
            'sheet_name': 'Sheet',
            'start_row': 0,
            'start_col': 0,
            'end_col': 0,
            'detected_end_row': 17,
        }

    monkeypatch.setattr(datasource_routes, 'execute_excel_preflight', resolve)
    response = client.put(f'/api/v1/datasource/{datasource_id}', json={'config': {'sheet_name': 'Sheet'}})

    assert response.status_code == 400
    assert 'changed while Excel selection was being resolved' in response.json()['detail']
