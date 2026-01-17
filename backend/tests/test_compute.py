from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

from modules.compute.engine import PolarsComputeEngine
from modules.compute.schemas import JobStatus
from modules.datasource.models import DataSource


@pytest.mark.asyncio
class TestComputeExecute:
    async def test_execute_analysis_success(self, client: AsyncClient, sample_datasource: DataSource):
        payload = {
            'datasource_id': sample_datasource.id,
            'pipeline_steps': [
                {
                    'id': 'step1',
                    'type': 'filter',
                    'config': {'column': 'age', 'operator': '>', 'value': 25},
                }
            ],
        }

        with patch('modules.compute.service.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_engine = MagicMock()
            mock_engine.execute.return_value = 'test-job-123'
            mock_engine.process.pid = 12345

            mock_manager.get_or_create_engine.return_value = mock_engine
            mock_get_manager.return_value = mock_manager

            response = await client.post('/api/v1/compute/execute', json=payload)

            assert response.status_code == 200
            result = response.json()

            assert result['job_id'] == 'test-job-123'
            assert result['status'] == JobStatus.PENDING
            assert result['progress'] == 0.0
            assert result['process_id'] == 12345

            mock_manager.get_or_create_engine.assert_called_once_with(sample_datasource.id)
            mock_engine.execute.assert_called_once()

    async def test_execute_analysis_datasource_not_found(self, client: AsyncClient):
        payload = {
            'datasource_id': 'non-existent-id',
            'pipeline_steps': [],
        }

        response = await client.post('/api/v1/compute/execute', json=payload)

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']

    async def test_execute_analysis_with_complex_pipeline(self, client: AsyncClient, sample_datasource: DataSource):
        payload = {
            'datasource_id': sample_datasource.id,
            'pipeline_steps': [
                {
                    'id': 'step1',
                    'type': 'filter',
                    'config': {'column': 'age', 'operator': '>', 'value': 25},
                },
                {
                    'id': 'step2',
                    'type': 'select',
                    'config': {'columns': ['name', 'age']},
                },
                {
                    'id': 'step3',
                    'type': 'sort',
                    'config': {'column': 'age', 'descending': True},
                },
            ],
        }

        with patch('modules.compute.service.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_engine = MagicMock()
            mock_engine.execute.return_value = 'test-job-456'
            mock_engine.process.pid = 12346

            mock_manager.get_or_create_engine.return_value = mock_engine
            mock_get_manager.return_value = mock_manager

            response = await client.post('/api/v1/compute/execute', json=payload)

            assert response.status_code == 200
            result = response.json()

            assert result['job_id'] == 'test-job-456'

            call_args = mock_engine.execute.call_args
            assert len(call_args[1]['pipeline_steps']) == 3


@pytest.mark.asyncio
class TestComputePreview:
    async def test_preview_step_success(self, client: AsyncClient, sample_datasource: DataSource):
        payload = {
            'datasource_id': sample_datasource.id,
            'pipeline_steps': [
                {
                    'id': 'step1',
                    'type': 'filter',
                    'config': {'column': 'age', 'operator': '>', 'value': 25},
                },
                {
                    'id': 'step2',
                    'type': 'select',
                    'config': {'columns': ['name', 'age']},
                },
            ],
            'step_index': 0,
        }

        with patch('modules.compute.service.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_engine = MagicMock()

            mock_engine.execute.return_value = 'preview-job-123'
            mock_engine.get_result.side_effect = [
                None,
                {
                    'status': JobStatus.COMPLETED,
                    'data': {
                        'columns': ['name', 'age'],
                        'rows': [['Bob', 30], ['Charlie', 35]],
                        'row_count': 2,
                    },
                },
            ]

            mock_manager.get_or_create_engine.return_value = mock_engine
            mock_get_manager.return_value = mock_manager

            response = await client.post('/api/v1/compute/preview', json=payload)

            assert response.status_code == 200
            result = response.json()

            assert 'columns' in result
            assert 'rows' in result
            assert result['row_count'] == 2

            mock_manager.shutdown_engine.assert_called_once()

    async def test_preview_step_failure(self, client: AsyncClient, sample_datasource: DataSource):
        payload = {
            'datasource_id': sample_datasource.id,
            'pipeline_steps': [
                {
                    'id': 'step1',
                    'type': 'invalid_operation',
                    'config': {},
                }
            ],
            'step_index': 0,
        }

        with patch('modules.compute.service.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_engine = MagicMock()

            mock_engine.execute.return_value = 'preview-job-124'
            mock_engine.get_result.side_effect = [
                None,
                {
                    'status': JobStatus.FAILED,
                    'error': 'Invalid operation type',
                },
            ]

            mock_manager.get_or_create_engine.return_value = mock_engine
            mock_get_manager.return_value = mock_manager

            response = await client.post('/api/v1/compute/preview', json=payload)

            assert response.status_code == 404

    async def test_preview_step_datasource_not_found(self, client: AsyncClient):
        payload = {
            'datasource_id': 'non-existent-id',
            'pipeline_steps': [],
            'step_index': 0,
        }

        response = await client.post('/api/v1/compute/preview', json=payload)

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']

    async def test_preview_step_specific_index(self, client: AsyncClient, sample_datasource: DataSource):
        payload = {
            'datasource_id': sample_datasource.id,
            'pipeline_steps': [
                {'id': 'step1', 'type': 'filter', 'config': {}},
                {'id': 'step2', 'type': 'select', 'config': {}},
                {'id': 'step3', 'type': 'sort', 'config': {}},
            ],
            'step_index': 1,
        }

        with patch('modules.compute.service.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_engine = MagicMock()

            mock_engine.execute.return_value = 'preview-job-125'
            mock_engine.get_result.side_effect = [
                None,
                {
                    'status': JobStatus.COMPLETED,
                    'data': {'columns': [], 'rows': [], 'row_count': 0},
                },
            ]

            mock_manager.get_or_create_engine.return_value = mock_engine
            mock_get_manager.return_value = mock_manager

            response = await client.post('/api/v1/compute/preview', json=payload)

            assert response.status_code == 200

            call_args = mock_engine.execute.call_args
            executed_steps = call_args[1]['pipeline_steps']
            assert len(executed_steps) == 2


def _build_fake_dataframe() -> MagicMock:
    fake_df = MagicMock()
    fake_df.schema = {}
    fake_df.__len__.return_value = 0
    fake_head = MagicMock()
    fake_head.to_dicts.return_value = []
    fake_df.head.return_value = fake_head
    return fake_df


@patch('modules.compute.engine.PolarsComputeEngine._load_datasource')
@patch('modules.compute.engine.PolarsComputeEngine._apply_step')
def test_pipeline_cycle_detection(mock_apply_step: MagicMock, mock_load: MagicMock):
    mock_load.return_value = MagicMock()
    mock_apply_step.side_effect = lambda frame, _step: frame

    pipeline_steps = [
        {'id': 'step1', 'type': 'filter', 'config': {}, 'depends_on': ['step2']},
        {'id': 'step2', 'type': 'select', 'config': {}, 'depends_on': ['step1']},
    ]

    with pytest.raises(ValueError, match='cycle'):
        PolarsComputeEngine._execute_pipeline({}, pipeline_steps, 'job', MagicMock())


@patch('modules.compute.engine.PolarsComputeEngine._load_datasource')
@patch('modules.compute.engine.PolarsComputeEngine._apply_step')
def test_pipeline_multiple_dependencies(mock_apply_step: MagicMock, mock_load: MagicMock):
    mock_load.return_value = MagicMock()
    mock_apply_step.side_effect = lambda frame, _step: frame

    pipeline_steps = [
        {'id': 'step1', 'type': 'filter', 'config': {}, 'depends_on': []},
        {'id': 'step2', 'type': 'select', 'config': {}, 'depends_on': ['step1', 'step3']},
        {'id': 'step3', 'type': 'sort', 'config': {}, 'depends_on': []},
    ]

    with pytest.raises(ValueError, match='multiple dependencies'):
        PolarsComputeEngine._execute_pipeline({}, pipeline_steps, 'job', MagicMock())


@patch('modules.compute.engine.PolarsComputeEngine._load_datasource')
@patch('modules.compute.engine.PolarsComputeEngine._apply_step')
def test_pipeline_topological_order(mock_apply_step: MagicMock, mock_load: MagicMock):
    fake_df = _build_fake_dataframe()
    fake_frame = MagicMock()
    fake_frame.collect.return_value = fake_df

    mock_load.return_value = fake_frame
    mock_apply_step.return_value = fake_frame

    pipeline_steps = [
        {'id': 'step1', 'type': 'filter', 'config': {}, 'depends_on': []},
        {'id': 'step2', 'type': 'select', 'config': {}, 'depends_on': ['step1']},
        {'id': 'step3', 'type': 'sort', 'config': {}, 'depends_on': ['step2']},
    ]

    result = PolarsComputeEngine._execute_pipeline({}, pipeline_steps, 'job', MagicMock())
    assert result['row_count'] == len(result['sample_data'])


@pytest.mark.asyncio
class TestJobStatus:
    async def test_get_job_status_success(self, client: AsyncClient):
        job_id = 'test-job-789'

        with patch('modules.compute.service.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_engine = MagicMock()
            mock_engine.current_job_id = job_id
            mock_engine.get_result.return_value = {
                'job_id': job_id,
                'status': JobStatus.RUNNING,
                'progress': 0.5,
                'current_step': 'step2',
                'error_message': None,
                'process_id': 12347,
            }

            mock_manager.list_engines.return_value = ['datasource-1']
            mock_manager.get_engine.return_value = mock_engine
            mock_get_manager.return_value = mock_manager

            response = await client.get(f'/api/v1/compute/status/{job_id}')

            assert response.status_code == 200
            result = response.json()

            assert result['job_id'] == job_id
            assert result['status'] == JobStatus.RUNNING
            assert result['progress'] == 0.5
            assert result['current_step'] == 'step2'

    async def test_get_job_status_not_found(self, client: AsyncClient):
        job_id = 'non-existent-job'

        with patch('modules.compute.service.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_manager.list_engines.return_value = []
            mock_get_manager.return_value = mock_manager

            response = await client.get(f'/api/v1/compute/status/{job_id}')

            assert response.status_code == 404
            assert 'not found' in response.json()['detail']

    async def test_get_job_status_completed(self, client: AsyncClient):
        job_id = 'completed-job-123'

        with patch('modules.compute.service.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_engine = MagicMock()
            mock_engine.current_job_id = job_id
            mock_engine.get_result.return_value = {
                'job_id': job_id,
                'status': JobStatus.COMPLETED,
                'progress': 1.0,
                'current_step': None,
                'error_message': None,
                'process_id': None,
                'data': {'result': 'success'},
            }

            mock_manager.list_engines.return_value = ['datasource-1']
            mock_manager.get_engine.return_value = mock_engine
            mock_get_manager.return_value = mock_manager

            response = await client.get(f'/api/v1/compute/status/{job_id}')

            assert response.status_code == 200
            result = response.json()

            assert result['status'] == JobStatus.COMPLETED
            assert result['progress'] == 1.0


@pytest.mark.asyncio
class TestJobResult:
    async def test_get_job_result_success(self, client: AsyncClient):
        job_id = 'completed-job-456'

        with patch(
            'modules.compute.service._job_results',
            {
                job_id: {
                    'status': JobStatus.COMPLETED,
                    'data': {
                        'columns': ['name', 'age'],
                        'rows': [['Alice', 25], ['Bob', 30]],
                    },
                    'error': None,
                }
            },
        ):
            response = await client.get(f'/api/v1/compute/result/{job_id}')

            assert response.status_code == 200
            result = response.json()

            assert result['job_id'] == job_id
            assert result['status'] == JobStatus.COMPLETED
            assert 'data' in result
            assert result['data']['columns'] == ['name', 'age']

    async def test_get_job_result_not_found(self, client: AsyncClient):
        job_id = 'non-existent-result'

        with patch('modules.compute.service._job_results', {}):
            response = await client.get(f'/api/v1/compute/result/{job_id}')

            assert response.status_code == 404
            assert 'not found' in response.json()['detail']


@pytest.mark.asyncio
class TestCancelJob:
    async def test_cancel_job_success(self, client: AsyncClient):
        job_id = 'running-job-789'

        with patch('modules.compute.service.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_engine = MagicMock()
            mock_engine.current_job_id = job_id

            mock_manager.list_engines.return_value = ['datasource-1']
            mock_manager.get_engine.return_value = mock_engine
            mock_get_manager.return_value = mock_manager

            response = await client.delete(f'/api/v1/compute/{job_id}')

            assert response.status_code == 200
            assert 'cancelled successfully' in response.json()['message']

            mock_manager.shutdown_engine.assert_called_once_with('datasource-1')

    async def test_cancel_job_not_found(self, client: AsyncClient):
        job_id = 'non-existent-job'

        with patch('modules.compute.service.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_manager.list_engines.return_value = []
            mock_get_manager.return_value = mock_manager

            response = await client.delete(f'/api/v1/compute/{job_id}')

            assert response.status_code == 404
            assert 'not found' in response.json()['detail']


@pytest.mark.asyncio
class TestCleanupJob:
    async def test_cleanup_job_success(self, client: AsyncClient):
        job_id = 'cleanup-job-123'

        with (
            patch('modules.compute.service._job_status', {job_id: {'status': 'completed'}}),
            patch('modules.compute.service._job_results', {job_id: {'data': 'result'}}),
        ):
            response = await client.delete(f'/api/v1/compute/{job_id}/cleanup')

            assert response.status_code == 200
            assert 'cleaned up successfully' in response.json()['message']

    async def test_cleanup_nonexistent_job(self, client: AsyncClient):
        job_id = 'non-existent-job'

        with patch('modules.compute.service._job_status', {}), patch('modules.compute.service._job_results', {}):
            response = await client.delete(f'/api/v1/compute/{job_id}/cleanup')

            assert response.status_code == 200
