import uuid
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

import polars as pl
import pytest
from openpyxl import Workbook
from sqlmodel import select

from backend_core.exceptions import DataSourceValidationError
from backend_core.persistence.analysis.models import Analysis
from backend_core.persistence.compute_worker_runs.models import ComputeWorkerRun
from backend_core.persistence.datasource.models import DataSource
from backend_core.sqlmodel_typing import sa

XLSX_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _xlsx_bytes(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    if sheet is None:
        pytest.skip('Excel support not available')
    sheet.title = 'Sheet1'
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class TestDataSourceValidation:
    def test_upload_empty_file(self, client, temp_upload_dir: Path):
        files = {'file': ('empty.csv', b'', 'text/csv')}

        response = client.post('/api/v1/datasource/upload', files=files)

        # Should fail with validation error
        assert response.status_code in [400, 422]

    def test_upload_file_over_size_limit_is_rejected(self, client, monkeypatch):
        from backend_core.config import settings

        monkeypatch.setattr(settings, 'upload_max_file_size_bytes', 1024)
        large_csv = b'id,value\n' + b'1,10\n' * 512
        files = {'file': ('large.csv', large_csv, 'text/csv')}

        response = client.post('/api/v1/datasource/upload', files=files, data={'name': 'Oversized CSV'})

        assert response.status_code == 413
        assert response.json()['detail'] == 'Uploaded file exceeds size limit'

    def test_upload_malformed_csv_is_rejected(self, client):
        # The second data row has more fields than the header, so no datasource may be created.
        malformed_csv = b'id,name,age\n1,Alice\n2,Bob,30,extra\n'
        files = {'file': ('corrupted.csv', malformed_csv, 'text/csv')}
        data = {'name': 'Corrupted CSV Test'}

        response = client.post('/api/v1/datasource/upload', files=files, data=data)

        assert response.status_code >= 400

    @pytest.mark.parametrize(
        ('filename', 'csv_content', 'name'),
        [
            pytest.param(
                'special.csv',
                b'id,name,description\n1,"O\'Brien","Quote: \\"test\\""\n2,Smith,"Newline:\ntest"\n',
                'Special Characters Test',
                id='special_characters',
            ),
            pytest.param(
                'unicode.csv',
                'id,name,city\n1,José,São Paulo\n2,François,Zürich\n'.encode(),
                'Unicode Test',
                id='unicode',
            ),
        ],
    )
    def test_upload_csv_with_special_characters_and_unicode(self, client, filename, csv_content, name):
        files = {'file': (filename, csv_content, 'text/csv')}
        data = {'name': name}

        response = client.post('/api/v1/datasource/upload', files=files, data=data)

        assert response.status_code == 200
        assert 'id' in response.json()

    def test_upload_with_missing_file(self, client):
        data = {'name': 'Missing File Test'}
        response = client.post('/api/v1/datasource/upload', data=data)

        assert response.status_code == 422

    def test_upload_excel_xlsx(self, client, temp_upload_dir: Path):
        """Test uploading Excel XLSX file."""
        # Create a simple Excel file using Polars
        excel_path = temp_upload_dir / 'test.xlsx'
        df = pl.DataFrame({'id': [1, 2, 3], 'name': ['A', 'B', 'C']})

        df.write_excel(excel_path)

        with open(excel_path, 'rb') as f:
            files = {
                'file': (
                    'test.xlsx',
                    f.read(),
                    XLSX_CONTENT_TYPE,
                )
            }
            data = {'name': 'Excel Test'}

        response = client.post('/api/v1/datasource/upload', files=files, data=data)

        assert response.status_code == 200

    def test_preflight_requires_xlsx(self, client):
        """Test preflight endpoint rejects non-xlsx files."""
        files = {'file': ('test.csv', b'a,b\n1,2', 'text/csv')}

        response = client.post('/api/v1/datasource/preflight', files=files)

        assert response.status_code == 400

    def test_preflight_excel_cell_range(self, client, faux_datasource_runtime):
        """Test Excel preflight supports A1 range selection."""
        files = {'file': ('range.xlsx', _xlsx_bytes([['id', 'name'], [1, 'A'], [2, 'B']]), XLSX_CONTENT_TYPE)}
        data = {'cell_range': 'A1:B3', 'has_header': 'true'}

        response = client.post('/api/v1/datasource/preflight', files=files, data=data)

        assert response.status_code == 200
        payload = response.json()
        assert payload['sheet_name'] == 'Sheet1'
        assert payload['start_row'] == 0
        assert payload['start_col'] == 0
        assert payload['end_col'] == 1
        assert payload['detected_end_row'] == 2
        assert len(payload['preview']) == 3
        assert faux_datasource_runtime.preflight_calls == [
            (
                'initial',
                {
                    'sheet_name': None,
                    'start_row': 0,
                    'start_col': 0,
                    'end_col': 0,
                    'end_row': None,
                    'has_header': True,
                    'table_name': None,
                    'named_range': None,
                    'cell_range': 'A1:B3',
                },
            )
        ]

    def test_preflight_excel_invalid_cell_range(self, client):
        """Test Excel preflight rejects invalid cell ranges."""
        files = {'file': ('invalid.xlsx', _xlsx_bytes([['id', 'name'], [1, 'A']]), XLSX_CONTENT_TYPE)}
        data = {'cell_range': 'NotARange', 'has_header': 'true'}

        response = client.post('/api/v1/datasource/preflight', files=files, data=data)

        assert response.status_code == 400

    def test_preflight_excel_path_rejects_non_xlsx(self, client, temp_upload_dir: Path):
        from backend_core.data_plane_client import client_from_settings

        csv_path = temp_upload_dir / 'invalid.csv'
        csv_path.write_text('a,b\n1,2')
        data_plane = client_from_settings()
        object_url = data_plane.build_object_url('tests', uuid.uuid4().hex, csv_path.name)
        data_plane.upload_object_bytes(csv_path.read_bytes(), object_url)
        payload = {'file_path': object_url}

        response = client.post('/api/v1/datasource/preflight-path', json=payload)

        assert response.status_code == 400

    def test_preflight_excel_path_returns_preview(self, client):
        from backend_core.data_plane_client import client_from_settings

        data_plane = client_from_settings()
        object_url = data_plane.build_object_url('tests', uuid.uuid4().hex, 'path.xlsx')
        data_plane.upload_object_bytes(_xlsx_bytes([['id', 'name'], [1, 'A'], [2, 'B']]), object_url)
        payload = {'file_path': object_url}

        response = client.post('/api/v1/datasource/preflight-path', json=payload)

        assert response.status_code == 200
        body = response.json()
        assert body['sheet_name'] == 'Sheet1'
        assert body['preflight_id']
        assert len(body['preview']) == 3

    def test_confirm_excel_end_row(self, client):
        """Test Excel confirm stores manual end row selection."""
        files = {'file': ('bounds.xlsx', _xlsx_bytes([['id', 'name'], [1, 'A'], [2, 'B'], [3, 'C']]), XLSX_CONTENT_TYPE)}

        preflight = client.post(
            '/api/v1/datasource/preflight',
            files=files,
            data={'start_row': '0', 'start_col': '0', 'end_col': '1'},
        )
        assert preflight.status_code == 200
        preflight_id = preflight.json()['preflight_id']

        confirm_data = {
            'preflight_id': preflight_id,
            'name': 'Excel End Row',
            'sheet_name': 'Sheet1',
            'start_row': '0',
            'start_col': '0',
            'end_col': '1',
            'end_row': '1',
            'has_header': 'true',
        }
        confirm = client.post('/api/v1/datasource/confirm', data=confirm_data)

        assert confirm.status_code == 200
        config = confirm.json()['config']
        assert config['source']['end_row'] == 1

    def test_confirm_excel_cell_range_stores_bounds(self, client):
        """Test Excel confirm stores manual cell range selection."""
        files = {'file': ('cell-range.xlsx', _xlsx_bytes([['id', 'name'], [1, 'A'], [2, 'B']]), XLSX_CONTENT_TYPE)}

        preflight = client.post('/api/v1/datasource/preflight', files=files)
        assert preflight.status_code == 200
        preflight_id = preflight.json()['preflight_id']

        confirm_data = {
            'preflight_id': preflight_id,
            'name': 'Excel Range',
            'cell_range': 'Sheet1!A1:B3',
            'has_header': 'true',
        }
        confirm = client.post('/api/v1/datasource/confirm', data=confirm_data)

        assert confirm.status_code == 200
        config = confirm.json()['config']
        assert config['source']['cell_range'] == 'Sheet1!A1:B3'
        assert config['source']['sheet_name'] == 'Sheet1'
        assert config['source']['start_row'] == 0
        assert config['source']['start_col'] == 0
        assert config['source']['end_col'] == 1
        assert config['source']['end_row'] == 2

    @patch(
        'modules.datasource.routes.create_remote_file_datasource',
        new_callable=AsyncMock,
    )
    def test_confirm_excel_preserves_validation_error(self, mock_create, client):
        files = {'file': ('confirm-invalid.xlsx', _xlsx_bytes([['id', 'name'], [1, 'A']]), XLSX_CONTENT_TYPE)}

        preflight = client.post('/api/v1/datasource/preflight', files=files)
        assert preflight.status_code == 200
        preflight_id = preflight.json()['preflight_id']

        mock_create.side_effect = DataSourceValidationError('Excel selection is invalid')
        confirm = client.post(
            '/api/v1/datasource/confirm',
            data={
                'preflight_id': preflight_id,
                'name': 'Broken Excel',
                'sheet_name': 'Sheet1',
                'has_header': 'true',
            },
        )

        assert confirm.status_code == 400
        assert confirm.json()['detail'] == 'Excel selection is invalid'


class TestDataSourceSchema:
    """Test datasource schema extraction."""

    def test_schema_for_different_types(self, client, sample_csv_file: Path, sample_parquet_file: Path):
        """Test schema extraction for different file types."""
        # Upload CSV
        with open(sample_csv_file, 'rb') as f:
            files = {'file': ('test.csv', f.read(), 'text/csv')}
            data = {'name': 'CSV Schema Test'}
            response = client.post('/api/v1/datasource/upload', files=files, data=data)
            csv_id = response.json()['id']

        # Upload Parquet
        with open(sample_parquet_file, 'rb') as f:
            files = {'file': ('test.parquet', f.read(), 'application/octet-stream')}
            data = {'name': 'Parquet Schema Test'}
            response = client.post('/api/v1/datasource/upload', files=files, data=data)
            parquet_id = response.json()['id']

        # Get schemas
        csv_schema = client.get(f'/api/v1/datasource/{csv_id}/schema')
        parquet_schema = client.get(f'/api/v1/datasource/{parquet_id}/schema')

        assert csv_schema.status_code == 200
        assert parquet_schema.status_code == 200
        assert {col['name'] for col in csv_schema.json()['columns']} == {'id', 'name', 'age', 'city'}
        assert {col['name'] for col in parquet_schema.json()['columns']} == {'product_id', 'product_name', 'price', 'stock'}


class TestDataSourceListing:
    """Test datasource listing functionality."""

    def test_list_does_not_write_schema_cache(self, client, test_db_session, sample_datasource: DataSource):
        """Listing datasources stays read-only for schema cache."""
        response = client.get('/api/v1/datasource')
        assert response.status_code == 200

        test_db_session.refresh(sample_datasource)
        assert sample_datasource.schema_cache is None


class TestDataSourceDeletion:
    """Test datasource deletion."""

    def test_delete_datasource_linked_to_analysis_is_accepted(self, client, test_db_session, sample_analysis):
        """A datasource referenced by an analysis tab is accepted for deletion and tombstoned."""
        datasource_id = sample_analysis.pipeline_definition['tabs'][0]['datasource']['id']

        response = client.delete(f'/api/v1/datasource/{datasource_id}')

        # Delete is now asynchronous: accepted immediately, finalized once preview work drains.
        assert response.status_code == 202
        test_db_session.expire_all()
        stored = test_db_session.get(DataSource, datasource_id)
        assert stored is not None
        assert stored.is_pending_delete is True

    def test_delete_uploaded_datasource_removes_iceberg_and_upload(self, client):
        payload = b'id,value\n1,10\n2,20\n'
        files = {'file': ('to_delete.csv', payload, 'text/csv')}
        data = {'name': 'Delete Test'}

        create = client.post('/api/v1/datasource/upload', files=files, data=data)

        assert create.status_code == 200
        from backend_core.data_plane_client import client_from_settings

        body = create.json()
        datasource_id = body['id']
        metadata_path = body['config']['metadata_path']
        source = body['config']['source']
        upload_path = source['file_path']

        data_plane = client_from_settings()
        assert data_plane.classify_object_url(metadata_path).is_object_store
        assert bool(data_plane.list_metadata_files(metadata_path))
        assert data_plane.object_exists(upload_path)
        assert source['source_type'] == 'file'

        response = client.delete(f'/api/v1/datasource/{datasource_id}')

        assert response.status_code == 202
        assert bool(data_plane.list_metadata_files(metadata_path))
        assert data_plane.object_exists(upload_path)

        get_response = client.get(f'/api/v1/datasource/{datasource_id}')
        assert get_response.status_code == 404


class TestIsHidden:
    """Test is_hidden field on datasources."""

    def _insert_datasource(self, session, *, is_hidden: bool, csv_file: Path) -> DataSource:
        """Insert a datasource directly into the DB with the given visibility."""
        ds = DataSource(
            id=str(uuid.uuid4()),
            name='Hidden DS' if is_hidden else 'Visible DS',
            source_type='file',
            config={'file_path': str(csv_file), 'file_type': 'csv', 'options': {}},
            is_hidden=is_hidden,
            created_at=datetime.now(UTC),
        )
        session.add(ds)
        session.commit()
        session.refresh(ds)
        return ds

    def test_list_excludes_hidden_by_default(self, client, test_db_session, sample_csv_file: Path):
        """GET /api/v1/datasource omits hidden datasources by default."""
        visible = self._insert_datasource(test_db_session, is_hidden=False, csv_file=sample_csv_file)
        self._insert_datasource(test_db_session, is_hidden=True, csv_file=sample_csv_file)

        response = client.get('/api/v1/datasource')
        assert response.status_code == 200

        ids = [ds['id'] for ds in response.json()]
        assert visible.id in ids
        # Hidden datasource must not appear
        hidden_ids = [ds['id'] for ds in response.json() if ds.get('is_hidden')]
        assert hidden_ids == []

    def test_list_includes_hidden_when_requested(self, client, test_db_session, sample_csv_file: Path):
        """GET /api/v1/datasource?include_hidden=true returns both hidden and visible."""
        visible = self._insert_datasource(test_db_session, is_hidden=False, csv_file=sample_csv_file)
        hidden = self._insert_datasource(test_db_session, is_hidden=True, csv_file=sample_csv_file)

        response = client.get('/api/v1/datasource?include_hidden=true')
        assert response.status_code == 200

        ids = [ds['id'] for ds in response.json()]
        assert visible.id in ids
        assert hidden.id in ids

    def test_hidden_datasource_still_accessible_by_id(self, client, test_db_session, sample_csv_file: Path):
        """GET /api/v1/datasource/{id} returns a hidden datasource."""
        hidden = self._insert_datasource(test_db_session, is_hidden=True, csv_file=sample_csv_file)

        response = client.get(f'/api/v1/datasource/{hidden.id}')
        assert response.status_code == 200
        assert response.json()['id'] == hidden.id
        assert response.json()['is_hidden'] is True

    def test_auto_creation_on_analysis_update(self, client, test_db_session, sample_analysis: Analysis):
        """Updating an analysis keeps explicit datasource ids."""
        new_tab_id = str(uuid.uuid4())
        update_payload: dict[str, object] = {
            'tabs': [
                {
                    'id': new_tab_id,
                    'name': 'Auto Tab',
                    'parent_id': None,
                    'datasource': {
                        'id': sample_analysis.pipeline_definition['tabs'][0]['datasource']['id'],
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'source_datasource',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.put(
            f'/api/v1/analysis/{sample_analysis.id}',
            json=update_payload,
            headers={'If-Match': str(sample_analysis.revision)},
        )
        assert response.status_code == 200


class TestDatasourceUpdateRunLogging:
    def test_update_raw_iceberg_does_not_create_build_compute_worker_run(self, client, test_db_session, sample_csv_object_url: str):
        ds = DataSource(
            id=str(uuid.uuid4()),
            name='Raw Iceberg',
            source_type='iceberg',
            config={
                'metadata_path': str(Path('data') / 'clean' / str(uuid.uuid4()) / 'master'),
                'branch': 'master',
                'snapshot_id': '500',
                'source': {
                    'source_type': 'file',
                    'file_path': sample_csv_object_url,
                    'file_type': 'csv',
                    'options': {},
                },
            },
            created_by='import',
            created_at=datetime.now(UTC),
        )
        test_db_session.add(ds)
        test_db_session.commit()

        response = client.put(f'/api/v1/datasource/{ds.id}', json={'name': 'Renamed Raw'})
        assert response.status_code == 200

        runs = test_db_session.execute(select(ComputeWorkerRun).where(sa(ComputeWorkerRun.datasource_id == ds.id))).scalars().all()
        assert runs == []

    def test_update_rejects_system_snapshot_fields(self, client, test_db_session, sample_csv_object_url: str):
        ds = DataSource(
            id=str(uuid.uuid4()),
            name='Snapshot Locked',
            source_type='iceberg',
            config={
                'metadata_path': str(Path('data') / 'clean' / str(uuid.uuid4()) / 'master'),
                'branch': 'master',
                'snapshot_id': '111',
                'snapshot_timestamp_ms': 1000,
                'current_snapshot_id': '111',
                'current_snapshot_timestamp_ms': 1000,
                'source': {
                    'source_type': 'file',
                    'file_path': sample_csv_object_url,
                    'file_type': 'csv',
                    'options': {},
                },
            },
            created_by='import',
            created_at=datetime.now(UTC),
        )
        test_db_session.add(ds)
        test_db_session.commit()

        response = client.put(
            f'/api/v1/datasource/{ds.id}',
            json={'config': {'current_snapshot_id': '999'}},
        )

        assert response.status_code == 400
        assert 'system-managed' in response.json()['detail']
