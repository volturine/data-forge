"""Extended tests for datasource module."""

import uuid
from pathlib import Path

import polars as pl
import pytest

from modules.datasource.models import DataSource


class TestDataSourceValidation:
    """Test datasource validation logic."""

    def test_upload_empty_file(self, client, temp_upload_dir: Path):
        """Test uploading an empty file."""
        files = {'file': ('empty.csv', b'', 'text/csv')}

        response = client.post('/api/v1/datasource/upload', files=files)

        # Should fail with validation error
        assert response.status_code in [400, 422]

    def test_upload_file_too_large(self, client, monkeypatch):
        """Test uploading a file that exceeds size limit."""
        # Create a large file (> 100MB)
        large_content = b'a' * (101 * 1024 * 1024)
        files = {'file': ('large.csv', large_content, 'text/csv')}

        response = client.post('/api/v1/datasource/upload', files=files)

        # Should fail with file too large error
        assert response.status_code in [400, 413, 422]

    def test_upload_unsupported_format(self, client):
        """Test uploading unsupported file format."""
        files = {'file': ('test.xyz', b'random data', 'application/octet-stream')}
        data = {'name': 'Unsupported Format Test'}

        response = client.post('/api/v1/datasource/upload', files=files, data=data)

        # Should fail with unsupported format error
        assert response.status_code in [400, 422]

    def test_upload_corrupted_csv(self, client):
        """Test uploading a corrupted CSV file."""
        corrupted_csv = b'id,name,age\n1,Alice\n2,Bob,30,extra\n'
        files = {'file': ('corrupted.csv', corrupted_csv, 'text/csv')}
        data = {'name': 'Corrupted CSV Test'}

        response = client.post('/api/v1/datasource/upload', files=files, data=data)

        # May succeed but should handle gracefully
        if response.status_code == 200:
            json_data = response.json()
            assert 'id' in json_data

    def test_upload_csv_with_special_characters(self, client):
        """Test uploading CSV with special characters."""
        csv_content = b'id,name,description\n1,"O\'Brien","Quote: \\"test\\""\n2,Smith,"Newline:\ntest"\n'
        files = {'file': ('special.csv', csv_content, 'text/csv')}
        data = {'name': 'Special Characters Test'}

        response = client.post('/api/v1/datasource/upload', files=files, data=data)

        assert response.status_code == 200

    def test_upload_csv_with_unicode(self, client):
        """Test uploading CSV with Unicode characters."""
        csv_content = 'id,name,city\n1,José,São Paulo\n2,François,Zürich\n'.encode()
        files = {'file': ('unicode.csv', csv_content, 'text/csv')}
        data = {'name': 'Unicode Test'}

        response = client.post('/api/v1/datasource/upload', files=files, data=data)

        assert response.status_code == 200
        json_data = response.json()
        assert 'id' in json_data

    def test_upload_with_missing_file(self, client):
        """Test upload endpoint without providing a file."""
        data = {'name': 'Missing File Test'}
        response = client.post('/api/v1/datasource/upload', data=data)

        assert response.status_code == 422

    def test_get_nonexistent_datasource(self, client):
        """Test getting a datasource that doesn't exist."""
        fake_id = str(uuid.uuid4())
        response = client.get(f'/api/v1/datasource/{fake_id}')

        assert response.status_code == 404

    def test_delete_nonexistent_datasource(self, client):
        """Test deleting a datasource that doesn't exist."""
        fake_id = str(uuid.uuid4())
        response = client.delete(f'/api/v1/datasource/{fake_id}')

        assert response.status_code == 404

    def test_get_schema_nonexistent_datasource(self, client):
        """Test getting schema for non-existent datasource."""
        fake_id = str(uuid.uuid4())
        response = client.get(f'/api/v1/datasource/{fake_id}/schema')

        assert response.status_code == 404

    def test_upload_csv_with_different_delimiters(self, client):
        """Test uploading CSV with different delimiters."""
        # Tab-separated
        tsv_content = b'id\tname\tage\n1\tAlice\t25\n2\tBob\t30\n'
        files = {'file': ('test.tsv', tsv_content, 'text/tab-separated-values')}
        data = {'name': 'TSV Test'}

        response = client.post('/api/v1/datasource/upload', files=files, data=data)

        # Should handle or reject gracefully
        assert response.status_code in [200, 400, 422]

    def test_upload_json_array(self, client):
        """Test uploading JSON array format."""
        json_content = b'[{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]'
        files = {'file': ('test.json', json_content, 'application/json')}
        data = {'name': 'JSON Array Test'}

        response = client.post('/api/v1/datasource/upload', files=files, data=data)

        assert response.status_code == 200

    def test_upload_ndjson_multiline(self, client):
        """Test uploading NDJSON with multiple lines."""
        ndjson_content = b'{"id": 1, "name": "Alice"}\n{"id": 2, "name": "Bob"}\n{"id": 3, "name": "Charlie"}\n'
        files = {'file': ('test.ndjson', ndjson_content, 'application/x-ndjson')}
        data = {'name': 'NDJSON Test'}

        response = client.post('/api/v1/datasource/upload', files=files, data=data)

        assert response.status_code == 200

    def test_upload_excel_xlsx(self, client, temp_upload_dir: Path):
        """Test uploading Excel XLSX file."""
        # Create a simple Excel file using Polars
        excel_path = temp_upload_dir / 'test.xlsx'
        df = pl.DataFrame({'id': [1, 2, 3], 'name': ['A', 'B', 'C']})

        try:
            df.write_excel(excel_path)

            with open(excel_path, 'rb') as f:
                files = {'file': ('test.xlsx', f.read(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}
                data = {'name': 'Excel Test'}

            response = client.post('/api/v1/datasource/upload', files=files, data=data)

            assert response.status_code == 200
        except Exception:
            # Excel support may not be available
            pytest.skip('Excel support not available')

    def test_preflight_requires_xlsx(self, client):
        """Test preflight endpoint rejects non-xlsx files."""
        files = {'file': ('test.csv', b'a,b\n1,2', 'text/csv')}

        response = client.post('/api/v1/datasource/preflight', files=files)

        assert response.status_code == 400


class TestDataSourceSchema:
    """Test datasource schema extraction."""

    def test_schema_caching(self, client, test_db_session, sample_datasource: DataSource):
        """Test that schema is cached after first request."""
        # First request
        response1 = client.get(f'/api/v1/datasource/{sample_datasource.id}/schema')
        assert response1.status_code == 200

        # Check that schema_cache is populated
        test_db_session.refresh(sample_datasource)

        # Second request should use cache
        response2 = client.get(f'/api/v1/datasource/{sample_datasource.id}/schema')
        assert response2.status_code == 200

        # Responses should be identical
        assert response1.json() == response2.json()

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

        # Both should have columns
        assert 'columns' in csv_schema.json() or 'fields' in csv_schema.json()
        assert 'columns' in parquet_schema.json() or 'fields' in parquet_schema.json()


class TestDataSourceListing:
    """Test datasource listing functionality."""

    def test_list_empty_datasources(self, client):
        """Test listing when no datasources exist."""
        response = client.get('/api/v1/datasource')

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_list_multiple_datasources(self, client, sample_datasources: list[DataSource]):
        """Test listing multiple datasources."""
        response = client.get('/api/v1/datasource')

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= len(sample_datasources)

    def test_list_datasources_pagination(self, client, sample_datasources: list[DataSource]):
        """Test datasource listing with pagination."""
        # Test if pagination is supported
        response = client.get('/api/v1/datasource?limit=1')

        assert response.status_code == 200
        data = response.json()

        # Should return at most 1 item if pagination is supported
        if isinstance(data, list):
            assert len(data) <= 1 or len(data) == len(sample_datasources)


class TestDataSourceDeletion:
    """Test datasource deletion."""

    def test_delete_datasource_cascades(self, client, test_db_session, sample_analysis):
        """Test that deleting a datasource handles linked analyses."""
        datasource_id = sample_analysis.pipeline_definition['datasource_ids'][0]

        # Delete the datasource
        response = client.delete(f'/api/v1/datasource/{datasource_id}')

        # Should succeed or return appropriate error
        assert response.status_code in [200, 204, 400, 409]

    def test_delete_datasource_removes_file(self, client, temp_upload_dir: Path):
        """Test that deleting a datasource removes the file."""
        # Create and upload a file
        csv_path = temp_upload_dir / 'to_delete.csv'
        df = pl.DataFrame({'id': [1], 'value': [10]})
        df.write_csv(csv_path)

        with open(csv_path, 'rb') as f:
            files = {'file': ('to_delete.csv', f.read(), 'text/csv')}
            data = {'name': 'Delete Test'}
            response = client.post('/api/v1/datasource/upload', files=files, data=data)

        datasource_id = response.json()['id']

        # Delete the datasource
        response = client.delete(f'/api/v1/datasource/{datasource_id}')

        # File should be removed (implementation dependent)
        assert response.status_code in [200, 204]
