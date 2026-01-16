from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest
from httpx import AsyncClient

from core.config import settings


@pytest.mark.asyncio
class TestResultMetadata:
    async def test_get_result_metadata_success(self, client: AsyncClient, sample_result_file: tuple[str, Path]):
        analysis_id, result_path = sample_result_file

        with patch.object(settings, 'results_dir', result_path.parent):
            response = await client.get(f'/api/v1/results/{analysis_id}')

            assert response.status_code == 200
            result = response.json()

            assert result['analysis_id'] == analysis_id
            assert result['row_count'] == 100
            assert result['column_count'] == 3

            assert len(result['columns_schema']) == 3

            column_names = [col['name'] for col in result['columns_schema']]
            assert 'id' in column_names
            assert 'value' in column_names
            assert 'category' in column_names

            for col in result['columns_schema']:
                assert 'name' in col
                assert 'dtype' in col

            assert 'created_at' in result

    async def test_get_result_metadata_not_found(self, client: AsyncClient, temp_results_dir: Path):
        analysis_id = 'non-existent-analysis'

        with patch.object(settings, 'results_dir', temp_results_dir):
            response = await client.get(f'/api/v1/results/{analysis_id}')

            assert response.status_code == 404
            assert 'not found' in response.json()['detail']


@pytest.mark.asyncio
class TestResultData:
    async def test_get_result_data_first_page(self, client: AsyncClient, sample_result_file: tuple[str, Path]):
        analysis_id, result_path = sample_result_file

        with patch.object(settings, 'results_dir', result_path.parent):
            response = await client.get(f'/api/v1/results/{analysis_id}/data?page=1&page_size=10')

            assert response.status_code == 200
            result = response.json()

            assert result['page'] == 1
            assert result['page_size'] == 10
            assert result['total_count'] == 100
            assert len(result['data']) == 10

            assert result['columns'] == ['id', 'value', 'category']

            assert result['data'][0]['id'] == 1
            assert result['data'][0]['value'] == 10

    async def test_get_result_data_second_page(self, client: AsyncClient, sample_result_file: tuple[str, Path]):
        analysis_id, result_path = sample_result_file

        with patch.object(settings, 'results_dir', result_path.parent):
            response = await client.get(f'/api/v1/results/{analysis_id}/data?page=2&page_size=10')

            assert response.status_code == 200
            result = response.json()

            assert result['page'] == 2
            assert result['page_size'] == 10
            assert len(result['data']) == 10

            assert result['data'][0]['id'] == 11
            assert result['data'][0]['value'] == 110

    async def test_get_result_data_last_page(self, client: AsyncClient, sample_result_file: tuple[str, Path]):
        analysis_id, result_path = sample_result_file

        with patch.object(settings, 'results_dir', result_path.parent):
            response = await client.get(f'/api/v1/results/{analysis_id}/data?page=10&page_size=10')

            assert response.status_code == 200
            result = response.json()

            assert result['page'] == 10
            assert result['page_size'] == 10
            assert len(result['data']) == 10

            assert result['data'][0]['id'] == 91
            assert result['data'][9]['id'] == 100

    async def test_get_result_data_beyond_last_page(self, client: AsyncClient, sample_result_file: tuple[str, Path]):
        analysis_id, result_path = sample_result_file

        with patch.object(settings, 'results_dir', result_path.parent):
            response = await client.get(f'/api/v1/results/{analysis_id}/data?page=20&page_size=10')

            assert response.status_code == 200
            result = response.json()

            assert len(result['data']) == 0

    async def test_get_result_data_custom_page_size(self, client: AsyncClient, sample_result_file: tuple[str, Path]):
        analysis_id, result_path = sample_result_file

        with patch.object(settings, 'results_dir', result_path.parent):
            response = await client.get(f'/api/v1/results/{analysis_id}/data?page=1&page_size=25')

            assert response.status_code == 200
            result = response.json()

            assert result['page_size'] == 25
            assert len(result['data']) == 25

    async def test_get_result_data_default_pagination(self, client: AsyncClient, sample_result_file: tuple[str, Path]):
        analysis_id, result_path = sample_result_file

        with patch.object(settings, 'results_dir', result_path.parent):
            response = await client.get(f'/api/v1/results/{analysis_id}/data')

            assert response.status_code == 200
            result = response.json()

            assert result['page'] == 1
            assert result['page_size'] == 100
            assert len(result['data']) == 100

    async def test_get_result_data_invalid_page(self, client: AsyncClient, sample_result_file: tuple[str, Path]):
        analysis_id, result_path = sample_result_file

        with patch.object(settings, 'results_dir', result_path.parent):
            response = await client.get(f'/api/v1/results/{analysis_id}/data?page=0')

            assert response.status_code == 400
            assert 'Page must be >= 1' in response.json()['detail']

    async def test_get_result_data_invalid_page_size_too_small(self, client: AsyncClient, sample_result_file: tuple[str, Path]):
        analysis_id, result_path = sample_result_file

        with patch.object(settings, 'results_dir', result_path.parent):
            response = await client.get(f'/api/v1/results/{analysis_id}/data?page_size=0')

            assert response.status_code == 400
            assert 'between 1 and 1000' in response.json()['detail']

    async def test_get_result_data_invalid_page_size_too_large(self, client: AsyncClient, sample_result_file: tuple[str, Path]):
        analysis_id, result_path = sample_result_file

        with patch.object(settings, 'results_dir', result_path.parent):
            response = await client.get(f'/api/v1/results/{analysis_id}/data?page_size=2000')

            assert response.status_code == 400
            assert 'between 1 and 1000' in response.json()['detail']

    async def test_get_result_data_not_found(self, client: AsyncClient, temp_results_dir: Path):
        analysis_id = 'non-existent-analysis'

        with patch.object(settings, 'results_dir', temp_results_dir):
            response = await client.get(f'/api/v1/results/{analysis_id}/data')

            assert response.status_code == 404
            assert 'not found' in response.json()['detail']


@pytest.mark.asyncio
class TestExportResult:
    async def test_export_result_csv(self, client: AsyncClient, sample_result_file: tuple[str, Path]):
        analysis_id, result_path = sample_result_file

        with patch.object(settings, 'results_dir', result_path.parent):
            payload = {'format': 'csv'}
            response = await client.post(f'/api/v1/results/{analysis_id}/export', json=payload)

            assert response.status_code == 200
            assert response.headers['content-type'] == 'application/octet-stream'

            export_path = result_path.parent / f'{analysis_id}.csv'
            assert export_path.exists()

            df_original = pl.read_parquet(result_path)
            df_exported = pl.read_csv(export_path)

            assert df_original.shape == df_exported.shape

            export_path.unlink()

    async def test_export_result_parquet(self, client: AsyncClient, sample_result_file: tuple[str, Path]):
        analysis_id, result_path = sample_result_file

        with patch.object(settings, 'results_dir', result_path.parent):
            payload = {'format': 'parquet'}
            response = await client.post(f'/api/v1/results/{analysis_id}/export', json=payload)

            assert response.status_code == 200
            assert response.headers['content-type'] == 'application/octet-stream'

    async def test_export_result_json(self, client: AsyncClient, sample_result_file: tuple[str, Path]):
        analysis_id, result_path = sample_result_file

        with patch.object(settings, 'results_dir', result_path.parent):
            payload = {'format': 'json'}
            response = await client.post(f'/api/v1/results/{analysis_id}/export', json=payload)

            assert response.status_code == 200
            assert response.headers['content-type'] == 'application/octet-stream'

            export_path = result_path.parent / f'{analysis_id}.json'
            assert export_path.exists()

            df_original = pl.read_parquet(result_path)
            df_exported = pl.read_json(export_path)

            assert df_original.shape == df_exported.shape

            export_path.unlink()

    async def test_export_result_excel(self, client: AsyncClient, sample_result_file: tuple[str, Path]):
        analysis_id, result_path = sample_result_file

        with patch.object(settings, 'results_dir', result_path.parent):
            payload = {'format': 'excel'}
            response = await client.post(f'/api/v1/results/{analysis_id}/export', json=payload)

            if response.status_code == 200:
                assert response.headers['content-type'] == 'application/octet-stream'

                export_path = result_path.parent / f'{analysis_id}.excel'
                assert export_path.exists()

                export_path.unlink()
            else:
                assert response.status_code == 500

    async def test_export_result_not_found(self, client: AsyncClient, temp_results_dir: Path):
        analysis_id = 'non-existent-analysis'

        with patch.object(settings, 'results_dir', temp_results_dir):
            payload = {'format': 'csv'}
            response = await client.post(f'/api/v1/results/{analysis_id}/export', json=payload)

            assert response.status_code == 404
            assert 'not found' in response.json()['detail']


@pytest.mark.asyncio
class TestDeleteResult:
    async def test_delete_result_success(self, client: AsyncClient, sample_result_file: tuple[str, Path]):
        analysis_id, result_path = sample_result_file

        assert result_path.exists()

        with patch.object(settings, 'results_dir', result_path.parent):
            response = await client.delete(f'/api/v1/results/{analysis_id}')

            assert response.status_code == 200
            assert 'deleted successfully' in response.json()['message']

            assert not result_path.exists()

    async def test_delete_result_with_exports(self, client: AsyncClient, sample_result_file: tuple[str, Path]):
        analysis_id, result_path = sample_result_file

        df = pl.read_parquet(result_path)

        csv_path = result_path.parent / f'{analysis_id}.csv'
        json_path = result_path.parent / f'{analysis_id}.json'

        df.write_csv(csv_path)
        df.write_json(json_path)

        assert result_path.exists()
        assert csv_path.exists()
        assert json_path.exists()

        with patch.object(settings, 'results_dir', result_path.parent):
            response = await client.delete(f'/api/v1/results/{analysis_id}')

            assert response.status_code == 200

            assert not result_path.exists()
            assert not csv_path.exists()
            assert not json_path.exists()

    async def test_delete_result_not_found(self, client: AsyncClient, temp_results_dir: Path):
        analysis_id = 'non-existent-analysis'

        with patch.object(settings, 'results_dir', temp_results_dir):
            response = await client.delete(f'/api/v1/results/{analysis_id}')

            assert response.status_code == 404
            assert 'not found' in response.json()['detail']
