import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import polars as pl
from sqlmodel import select

from core.exceptions import DataSourceValidationError
from core.namespace import namespace_paths
from main import app
from modules.auth.dependencies import get_optional_user
from modules.datasource.models import DataSource, DataSourceColumnMetadata


class TestDataSourceUpload:
    def test_upload_csv_file_success(self, client, temp_upload_dir: Path, mock_file_upload: dict):
        files = {'file': (mock_file_upload['filename'], mock_file_upload['content'], mock_file_upload['content_type'])}
        data = {'name': 'Test CSV Upload'}

        response = client.post('/api/v1/datasource/upload', files=files, data=data)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'Test CSV Upload'
        assert result['source_type'] == 'iceberg'
        assert 'id' in result
        assert 'created_at' in result
        assert result['config']['branch'] == 'master'
        assert result['config']['metadata_path'].startswith(str(namespace_paths().clean_dir))

    def test_upload_csv_file_with_description_success(self, client, temp_upload_dir: Path, mock_file_upload: dict):
        files = {'file': (mock_file_upload['filename'], mock_file_upload['content'], mock_file_upload['content_type'])}
        data = {'name': 'Described CSV Upload', 'description': 'Source of truth for customer lifecycle analysis.'}

        response = client.post('/api/v1/datasource/upload', files=files, data=data)

        assert response.status_code == 200
        result = response.json()
        assert result['description'] == 'Source of truth for customer lifecycle analysis.'

    def test_upload_parquet_file_success(self, client, temp_upload_dir: Path, sample_parquet_file: Path):
        with open(sample_parquet_file, 'rb') as f:
            files = {'file': ('test.parquet', f, 'application/octet-stream')}
            data = {'name': 'Test Parquet Upload'}

            response = client.post('/api/v1/datasource/upload', files=files, data=data)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'Test Parquet Upload'
        assert result['source_type'] == 'iceberg'
        assert result['config']['branch'] == 'master'

    def test_upload_json_file_success(self, client, temp_upload_dir: Path, sample_json_file: Path):
        with open(sample_json_file, 'rb') as f:
            files = {'file': ('test.json', f, 'application/json')}
            data = {'name': 'Test JSON Upload'}

            response = client.post('/api/v1/datasource/upload', files=files, data=data)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'Test JSON Upload'
        assert result['source_type'] == 'iceberg'
        assert result['config']['branch'] == 'master'

    def test_upload_ndjson_file_success(self, client, temp_upload_dir: Path, sample_ndjson_file: Path):
        with open(sample_ndjson_file, 'rb') as f:
            files = {'file': ('test.ndjson', f, 'application/json')}
            data = {'name': 'Test NDJSON Upload'}

            response = client.post('/api/v1/datasource/upload', files=files, data=data)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'Test NDJSON Upload'
        assert result['source_type'] == 'iceberg'
        assert result['config']['branch'] == 'master'

    def test_upload_without_filename(self, client, temp_upload_dir: Path):
        files = {'file': ('', b'content', 'text/csv')}
        data = {'name': 'Test Upload'}

        response = client.post('/api/v1/datasource/upload', files=files, data=data)

        assert response.status_code == 422

    def test_upload_unsupported_file_type(self, client, temp_upload_dir: Path):
        files = {'file': ('test.txt', b'content', 'text/plain')}
        data = {'name': 'Test Upload'}

        response = client.post('/api/v1/datasource/upload', files=files, data=data)

        assert response.status_code == 400
        assert 'Unsupported file type' in response.json()['detail']

    def test_upload_sets_owner_id_when_optional_user_present(self, client, mock_file_upload: dict, test_db_session, test_user, monkeypatch):
        monkeypatch.setitem(app.dependency_overrides, get_optional_user, lambda: test_user)
        files = {'file': (mock_file_upload['filename'], mock_file_upload['content'], mock_file_upload['content_type'])}
        data = {'name': 'Owned Upload'}

        response = client.post('/api/v1/datasource/upload', files=files, data=data)

        assert response.status_code == 200
        datasource_id = response.json()['id']
        created = test_db_session.get(DataSource, datasource_id)
        assert created is not None
        assert created.owner_id == test_user.id

    @patch('modules.datasource.routes.run_db')
    def test_upload_preserves_datasource_validation_error(self, mock_run_db, client, mock_file_upload: dict):
        mock_run_db.side_effect = DataSourceValidationError('CSV schema is invalid')
        files = {'file': (mock_file_upload['filename'], mock_file_upload['content'], mock_file_upload['content_type'])}
        data = {'name': 'Validation Failure'}

        response = client.post('/api/v1/datasource/upload', files=files, data=data)

        assert response.status_code == 400
        assert response.json()['detail'] == 'CSV schema is invalid'

    @patch('modules.datasource.routes.run_db')
    def test_upload_preserves_value_error(self, mock_run_db, client, mock_file_upload: dict):
        mock_run_db.side_effect = ValueError('Bad upload path')
        files = {'file': (mock_file_upload['filename'], mock_file_upload['content'], mock_file_upload['content_type'])}
        data = {'name': 'Value Failure'}

        response = client.post('/api/v1/datasource/upload', files=files, data=data)

        assert response.status_code == 400
        assert response.json()['detail'] == 'Bad upload path'


class TestDataSourceConnect:
    def test_connect_database_datasource(self, client):
        payload = {
            'name': 'Test Database Connection',
            'source_type': 'database',
            'config': {
                'connection_string': 'postgresql://user:pass@localhost/db',
                'query': 'SELECT * FROM users',
            },
        }

        response = client.post('/api/v1/datasource/connect', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'Test Database Connection'
        assert result['description'] is None
        assert result['source_type'] == 'database'
        assert result['config']['connection_string'] == 'postgresql://user:pass@localhost/db'
        assert result['config']['query'] == 'SELECT * FROM users'

    def test_connect_database_datasource_with_description(self, client):
        payload = {
            'name': 'Described Database Connection',
            'description': 'Read-only reporting extract for finance reconciliation.',
            'source_type': 'database',
            'config': {
                'connection_string': 'postgresql://user:pass@localhost/db',
                'query': 'SELECT * FROM users',
            },
        }

        response = client.post('/api/v1/datasource/connect', json=payload)

        assert response.status_code == 200
        result = response.json()
        assert result['description'] == 'Read-only reporting extract for finance reconciliation.'

    def test_connect_sets_owner_id_when_optional_user_present(self, client, test_db_session, test_user, monkeypatch):
        monkeypatch.setitem(app.dependency_overrides, get_optional_user, lambda: test_user)
        payload = {
            'name': 'Owned Database Connection',
            'source_type': 'database',
            'config': {
                'connection_string': 'postgresql://user:pass@localhost/db',
                'query': 'SELECT * FROM users',
            },
        }

        response = client.post('/api/v1/datasource/connect', json=payload)

        assert response.status_code == 200
        datasource_id = response.json()['id']
        created = test_db_session.get(DataSource, datasource_id)
        assert created is not None
        assert created.owner_id == test_user.id

    def test_connect_unsupported_source_type(self, client):
        payload = {
            'name': 'Test Unknown',
            'source_type': 'unknown',
            'config': {},
        }

        response = client.post('/api/v1/datasource/connect', json=payload)

        assert response.status_code == 422

    def test_connect_iceberg_rejects_direct_metadata_path(self, client):
        payload = {
            'name': 'Bad Iceberg Connection',
            'source_type': 'iceberg',
            'config': {'metadata_path': '/tmp/existing-table'},
        }

        response = client.post('/api/v1/datasource/connect', json=payload)

        assert response.status_code == 400

    @patch('modules.datasource.service.load_datasource')
    @patch('modules.datasource.service._write_iceberg_table')
    def test_connect_iceberg_with_source_config_creates_iceberg(
        self,
        mock_write,
        mock_load,
        client,
        sample_csv_file: Path,
    ):
        class _Snap:
            snapshot_id = 100
            timestamp_ms = 123456

        class _Table:
            def current_snapshot(self):
                return _Snap()

        mock_load.return_value = pl.DataFrame({'a': [1]}).lazy()
        mock_write.return_value = _Table()

        payload = {
            'name': 'Good Iceberg Connection',
            'source_type': 'iceberg',
            'config': {
                'branch': 'master',
                'source': {'source_type': 'file', 'file_path': str(sample_csv_file), 'file_type': 'csv', 'options': {}},
            },
        }

        response = client.post('/api/v1/datasource/connect', json=payload)

        assert response.status_code == 200
        body = response.json()
        assert body['source_type'] == 'iceberg'
        assert body['config']['source']['source_type'] == 'file'


class TestDataSourceList:
    def test_list_empty_datasources(self, client):
        response = client.get('/api/v1/datasource')

        assert response.status_code == 200
        result = response.json()

        assert isinstance(result, list)
        assert len(result) == 0

    def test_list_datasources_with_data(self, client, sample_datasources: list[DataSource]):
        response = client.get('/api/v1/datasource')

        assert response.status_code == 200
        result = response.json()

        assert isinstance(result, list)
        assert len(result) == 2

        assert result[0]['name'] == 'CSV DataSource'
        assert result[0]['description'] == 'CSV DataSource description'
        assert result[1]['name'] == 'Parquet DataSource'
        assert result[1]['description'] == 'Parquet DataSource description'


class TestDataSourceGet:
    def test_get_datasource_success(self, client, sample_datasource: DataSource):
        response = client.get(f'/api/v1/datasource/{sample_datasource.id}')

        assert response.status_code == 200
        result = response.json()

        assert result['id'] == sample_datasource.id
        assert result['name'] == sample_datasource.name
        assert result['description'] == sample_datasource.description
        assert result['source_type'] == sample_datasource.source_type

    def test_get_datasource_not_found(self, client):
        missing_id = str(uuid.uuid4())
        response = client.get(f'/api/v1/datasource/{missing_id}')

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']


class TestDataSourceUpdate:
    def test_update_description_success(self, client, sample_datasource: DataSource, test_db_session):
        payload = {
            'name': sample_datasource.name,
            'description': 'Canonical customer export used for weekly KPI reporting.',
        }

        response = client.put(f'/api/v1/datasource/{sample_datasource.id}', json=payload)

        assert response.status_code == 200
        body = response.json()
        assert body['description'] == 'Canonical customer export used for weekly KPI reporting.'

        test_db_session.refresh(sample_datasource)
        assert sample_datasource.description == 'Canonical customer export used for weekly KPI reporting.'

    def test_update_description_empty_string_clears_value(self, client, sample_datasource: DataSource, test_db_session):
        payload = {
            'name': sample_datasource.name,
            'description': '',
        }

        response = client.put(f'/api/v1/datasource/{sample_datasource.id}', json=payload)

        assert response.status_code == 200
        body = response.json()
        assert body['description'] is None

        test_db_session.refresh(sample_datasource)
        assert sample_datasource.description is None


class TestDataSourceSchema:
    def test_get_schema_csv_file(self, client, sample_datasource: DataSource):
        response = client.get(f'/api/v1/datasource/{sample_datasource.id}/schema')

        assert response.status_code == 200
        result = response.json()

        assert 'columns' in result
        assert len(result['columns']) == 4

        column_names = [col['name'] for col in result['columns']]
        assert 'id' in column_names
        assert 'name' in column_names
        assert 'age' in column_names
        assert 'city' in column_names

        for col in result['columns']:
            assert 'dtype' in col
            assert 'nullable' in col
            assert 'description' in col

    def test_get_schema_includes_column_descriptions(self, client, sample_datasource: DataSource, test_db_session):
        metadata = DataSourceColumnMetadata(
            id=str(uuid.uuid4()),
            datasource_id=sample_datasource.id,
            column_name='city',
            description='Primary city label used in reports',
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        test_db_session.add(metadata)
        test_db_session.commit()

        response = client.get(f'/api/v1/datasource/{sample_datasource.id}/schema')

        assert response.status_code == 200
        result = response.json()
        city = next(col for col in result['columns'] if col['name'] == 'city')
        age = next(col for col in result['columns'] if col['name'] == 'age')
        assert city['description'] == 'Primary city label used in reports'
        assert age['description'] is None

    def test_get_schema_caching(self, client, sample_datasource: DataSource, test_db_session):
        response1 = client.get(f'/api/v1/datasource/{sample_datasource.id}/schema')
        assert response1.status_code == 200

        test_db_session.refresh(sample_datasource)
        assert sample_datasource.schema_cache is not None

        response2 = client.get(f'/api/v1/datasource/{sample_datasource.id}/schema')
        assert response2.status_code == 200
        assert response1.json() == response2.json()

    def test_get_schema_uses_live_descriptions_with_cached_schema(self, client, sample_datasource: DataSource, test_db_session):
        initial = client.get(f'/api/v1/datasource/{sample_datasource.id}/schema')
        assert initial.status_code == 200

        metadata = DataSourceColumnMetadata(
            id=str(uuid.uuid4()),
            datasource_id=sample_datasource.id,
            column_name='name',
            description='Customer-facing display label',
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        test_db_session.add(metadata)
        test_db_session.commit()

        response = client.get(f'/api/v1/datasource/{sample_datasource.id}/schema')

        assert response.status_code == 200
        name_column = next(col for col in response.json()['columns'] if col['name'] == 'name')
        assert name_column['description'] == 'Customer-facing display label'
        test_db_session.refresh(sample_datasource)
        schema_cache = sample_datasource.schema_cache
        assert isinstance(schema_cache, dict)
        cached_name = next(col for col in schema_cache['columns'] if col['name'] == 'name')
        assert 'description' not in cached_name

    def test_get_schema_not_found(self, client):
        missing_id = str(uuid.uuid4())
        response = client.get(f'/api/v1/datasource/{missing_id}/schema')

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']

    def test_patch_column_metadata_updates_and_clears_descriptions(self, client, sample_datasource: DataSource, test_db_session):
        response = client.patch(
            f'/api/v1/datasource/{sample_datasource.id}/column-metadata',
            json={
                'columns': [
                    {'column_name': 'name', 'description': '  Customer display name  '},
                    {'column_name': 'city', 'description': 'City used for segmentation'},
                ],
            },
        )

        assert response.status_code == 200
        body = response.json()
        name_column = next(col for col in body['columns'] if col['name'] == 'name')
        city_column = next(col for col in body['columns'] if col['name'] == 'city')
        assert name_column['description'] == 'Customer display name'
        assert city_column['description'] == 'City used for segmentation'

        rows = list(test_db_session.exec(select(DataSourceColumnMetadata)))
        assert len(rows) == 2

        clear = client.patch(
            f'/api/v1/datasource/{sample_datasource.id}/column-metadata',
            json={'columns': [{'column_name': 'name', 'description': '   '}]},
        )

        assert clear.status_code == 200
        cleared_name = next(col for col in clear.json()['columns'] if col['name'] == 'name')
        assert cleared_name['description'] is None
        remaining = list(test_db_session.exec(select(DataSourceColumnMetadata)))
        assert len(remaining) == 1
        assert remaining[0].column_name == 'city'

    def test_patch_column_metadata_rejects_unknown_column(self, client, sample_datasource: DataSource):
        response = client.patch(
            f'/api/v1/datasource/{sample_datasource.id}/column-metadata',
            json={'columns': [{'column_name': 'missing_column', 'description': 'Nope'}]},
        )

        assert response.status_code == 400
        assert response.json()['detail'] == 'Column not found in active schema: missing_column'

    def test_patch_column_metadata_rejects_descriptions_over_2000_chars(self, client, sample_datasource: DataSource):
        response = client.patch(
            f'/api/v1/datasource/{sample_datasource.id}/column-metadata',
            json={'columns': [{'column_name': 'name', 'description': 'x' * 2001}]},
        )

        assert response.status_code == 400
        assert response.json()['detail'] == 'Column descriptions must be 2,000 characters or fewer'

    def test_refresh_preserves_column_descriptions(self, client, sample_datasource: DataSource):
        update = client.patch(
            f'/api/v1/datasource/{sample_datasource.id}/column-metadata',
            json={'columns': [{'column_name': 'age', 'description': 'Age in years'}]},
        )
        assert update.status_code == 200

        refresh = client.get(f'/api/v1/datasource/{sample_datasource.id}/schema', params={'refresh': 'true'})

        assert refresh.status_code == 200
        age_column = next(col for col in refresh.json()['columns'] if col['name'] == 'age')
        assert age_column['description'] == 'Age in years'


class TestColumnStats:
    def test_column_stats_with_config_override(self, client, sample_datasource: DataSource, sample_csv_file: Path):
        payload = {
            'datasource': {
                'config': {
                    'file_path': str(sample_csv_file),
                    'file_type': 'csv',
                    'options': {},
                },
            },
        }

        response = client.post(
            f'/api/v1/datasource/{sample_datasource.id}/column/age/stats',
            params={'sample': 'false'},
            json=payload,
        )

        assert response.status_code == 200
        result = response.json()

        assert result['column'] == 'age'
        assert result['count'] == 5
        assert result['null_count'] == 0


class TestDataSourceDelete:
    def test_delete_datasource_success(self, client, sample_datasource: DataSource, test_db_session):
        datasource_id = sample_datasource.id
        file_path = Path(sample_datasource.config['file_path'])

        assert file_path.exists()

        response = client.delete(f'/api/v1/datasource/{datasource_id}')

        assert response.status_code == 204

        assert not file_path.exists()

        get_response = client.get(f'/api/v1/datasource/{datasource_id}')
        assert get_response.status_code == 404

    def test_delete_datasource_not_found(self, client):
        missing_id = str(uuid.uuid4())
        response = client.delete(f'/api/v1/datasource/{missing_id}')

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']

    def test_delete_datasource_without_file(self, client, test_db_session):
        import uuid
        from datetime import UTC, datetime

        datasource_id = str(uuid.uuid4())
        config = {
            'connection_string': 'postgresql://localhost/db',
            'query': 'SELECT * FROM table',
        }

        datasource = DataSource(
            id=datasource_id,
            name='Database Source',
            source_type='database',
            config=config,
            created_at=datetime.now(UTC),
        )

        test_db_session.add(datasource)
        test_db_session.commit()

        response = client.delete(f'/api/v1/datasource/{datasource_id}')

        assert response.status_code == 204
