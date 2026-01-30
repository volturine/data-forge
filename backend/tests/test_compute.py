from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

from modules.compute.engine import PolarsComputeEngine
from modules.datasource.models import DataSource


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
            'target_step_id': 'step1',
        }

        with patch('modules.compute.service.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_engine = MagicMock()

            mock_engine.preview.return_value = 'preview-job-123'
            mock_engine.get_result.side_effect = [
                None,
                {
                    'data': {
                        'schema': {'name': 'String', 'age': 'Int64'},
                        'data': [{'name': 'Bob', 'age': 30}, {'name': 'Charlie', 'age': 35}],
                        'row_count': 2,
                    },
                    'error': None,
                },
            ]

            mock_manager.get_engine.return_value = None
            mock_manager.get_or_create_engine.return_value = mock_engine
            mock_get_manager.return_value = mock_manager

            response = await client.post('/api/v1/compute/preview', json=payload)

            assert response.status_code == 200
            result = response.json()

            assert 'columns' in result
            assert 'data' in result
            assert result['total_rows'] == 2

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
            'target_step_id': 'step1',
        }

        with patch('modules.compute.service.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_engine = MagicMock()

            mock_engine.preview.return_value = 'preview-job-124'
            mock_engine.get_result.side_effect = [
                None,
                {
                    'data': None,
                    'error': 'Invalid operation type',
                },
            ]

            mock_manager.get_engine.return_value = None
            mock_manager.get_or_create_engine.return_value = mock_engine
            mock_get_manager.return_value = mock_manager

            response = await client.post('/api/v1/compute/preview', json=payload)

            # Failed pipeline execution returns 500
            assert response.status_code in [404, 500]

    async def test_preview_step_datasource_not_found(self, client: AsyncClient):
        payload = {
            'datasource_id': 'non-existent-id',
            'pipeline_steps': [],
            'target_step_id': 'step1',
        }

        response = await client.post('/api/v1/compute/preview', json=payload)

        assert response.status_code == 404
        result = response.json()
        detail = result.get('detail', result)
        if isinstance(detail, dict):
            assert 'not found' in detail.get('message', '')
        else:
            assert 'not found' in str(detail)

    async def test_preview_step_specific_target(self, client: AsyncClient, sample_datasource: DataSource):
        payload = {
            'datasource_id': sample_datasource.id,
            'pipeline_steps': [
                {'id': 'step1', 'type': 'filter', 'config': {}},
                {'id': 'step2', 'type': 'select', 'config': {}},
                {'id': 'step3', 'type': 'sort', 'config': {}},
            ],
            'target_step_id': 'step2',
        }

        with patch('modules.compute.service.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_engine = MagicMock()

            mock_engine.preview.return_value = 'preview-job-125'
            mock_engine.get_result.side_effect = [
                None,
                {
                    'data': {'schema': {}, 'data': [], 'row_count': 0},
                    'error': None,
                },
            ]

            mock_manager.get_engine.return_value = None
            mock_manager.get_or_create_engine.return_value = mock_engine
            mock_get_manager.return_value = mock_manager

            response = await client.post('/api/v1/compute/preview', json=payload)

            assert response.status_code == 200


def _build_fake_dataframe() -> MagicMock:
    fake_df = MagicMock()
    fake_df.schema = {}
    fake_df.__len__.return_value = 0
    fake_head = MagicMock()
    fake_head.to_dicts.return_value = []
    fake_df.head.return_value = fake_head
    return fake_df


@patch('modules.compute.engine.load_datasource')
@patch('modules.compute.engine.PolarsComputeEngine._apply_step')
def test_pipeline_cycle_detection(mock_apply_step: MagicMock, mock_load: MagicMock):
    mock_load.return_value = MagicMock()
    mock_apply_step.side_effect = lambda frame, _step, **kwargs: frame

    pipeline_steps = [
        {'id': 'step1', 'type': 'filter', 'config': {}, 'depends_on': ['step2']},
        {'id': 'step2', 'type': 'select', 'config': {}, 'depends_on': ['step1']},
    ]

    with pytest.raises(ValueError, match='cycle'):
        PolarsComputeEngine._build_pipeline({}, pipeline_steps, 'job', MagicMock())


@patch('modules.compute.engine.load_datasource')
@patch('modules.compute.engine.PolarsComputeEngine._apply_step')
def test_pipeline_multiple_dependencies(mock_apply_step: MagicMock, mock_load: MagicMock):
    mock_load.return_value = MagicMock()
    mock_apply_step.side_effect = lambda frame, _step, **kwargs: frame

    pipeline_steps = [
        {'id': 'step1', 'type': 'filter', 'config': {}, 'depends_on': []},
        {'id': 'step2', 'type': 'select', 'config': {}, 'depends_on': ['step1', 'step3']},
        {'id': 'step3', 'type': 'sort', 'config': {}, 'depends_on': []},
    ]

    with pytest.raises(ValueError, match='multiple dependencies'):
        PolarsComputeEngine._build_pipeline({}, pipeline_steps, 'job', MagicMock())


@patch('modules.compute.engine.load_datasource')
@patch('modules.compute.engine.PolarsComputeEngine._apply_step')
def test_pipeline_topological_order(mock_apply_step: MagicMock, mock_load: MagicMock):
    fake_lf = MagicMock()
    fake_lf.collect_schema.return_value = {}

    mock_load.return_value = fake_lf
    mock_apply_step.return_value = fake_lf

    pipeline_steps = [
        {'id': 'step1', 'type': 'filter', 'config': {}, 'depends_on': []},
        {'id': 'step2', 'type': 'select', 'config': {}, 'depends_on': ['step1']},
        {'id': 'step3', 'type': 'sort', 'config': {}, 'depends_on': ['step2']},
    ]

    # _build_pipeline returns a LazyFrame, not a dict
    result = PolarsComputeEngine._build_pipeline({}, pipeline_steps, 'job', MagicMock())
    assert result == fake_lf


@pytest.mark.asyncio
class TestEngineLifecycle:
    async def test_spawn_engine(self, client: AsyncClient):
        analysis_id = 'test-analysis-123'

        with patch('modules.compute.routes.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_manager.spawn_engine.return_value = MagicMock()
            mock_manager.get_engine_status.return_value = {
                'analysis_id': analysis_id,
                'status': 'healthy',
                'process_id': 12345,
                'last_activity': '2024-01-01T00:00:00',
                'current_job_id': None,
            }
            mock_get_manager.return_value = mock_manager

            response = await client.post(f'/api/v1/compute/engine/spawn/{analysis_id}')

            assert response.status_code == 200
            result = response.json()
            assert result['analysis_id'] == analysis_id
            assert result['status'] == 'healthy'

    async def test_keepalive_engine(self, client: AsyncClient):
        analysis_id = 'test-analysis-123'

        with patch('modules.compute.routes.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_manager.keepalive.return_value = MagicMock()
            mock_manager.get_engine_status.return_value = {
                'analysis_id': analysis_id,
                'status': 'healthy',
                'process_id': 12345,
                'last_activity': '2024-01-01T00:00:00',
                'current_job_id': None,
            }
            mock_get_manager.return_value = mock_manager

            response = await client.post(f'/api/v1/compute/engine/keepalive/{analysis_id}')

            assert response.status_code == 200
            result = response.json()
            assert result['analysis_id'] == analysis_id

    async def test_get_engine_status(self, client: AsyncClient):
        analysis_id = 'test-analysis-123'

        with patch('modules.compute.routes.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_manager.get_engine_status.return_value = {
                'analysis_id': analysis_id,
                'status': 'healthy',
                'process_id': 12345,
                'last_activity': '2024-01-01T00:00:00',
                'current_job_id': None,
            }
            mock_get_manager.return_value = mock_manager

            response = await client.get(f'/api/v1/compute/engine/status/{analysis_id}')

            assert response.status_code == 200
            result = response.json()
            assert result['analysis_id'] == analysis_id
            assert result['status'] == 'healthy'

    async def test_shutdown_engine(self, client: AsyncClient):
        analysis_id = 'test-analysis-123'

        with patch('modules.compute.routes.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_engine = MagicMock()
            mock_manager.get_engine.return_value = mock_engine
            mock_get_manager.return_value = mock_manager

            response = await client.delete(f'/api/v1/compute/engine/{analysis_id}')

            assert response.status_code == 200
            assert 'shutdown successfully' in response.json()['message']
            mock_manager.shutdown_engine.assert_called_once_with(analysis_id)

    async def test_shutdown_engine_not_found(self, client: AsyncClient):
        analysis_id = 'non-existent-analysis'

        with patch('modules.compute.routes.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_manager.get_engine.return_value = None
            mock_get_manager.return_value = mock_manager

            response = await client.delete(f'/api/v1/compute/engine/{analysis_id}')

            assert response.status_code == 404

    async def test_list_engines(self, client: AsyncClient):
        with patch('modules.compute.routes.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_manager.list_all_engine_statuses.return_value = [
                {
                    'analysis_id': 'analysis-1',
                    'status': 'healthy',
                    'process_id': 12345,
                    'last_activity': '2024-01-01T00:00:00',
                    'current_job_id': None,
                },
                {
                    'analysis_id': 'analysis-2',
                    'status': 'healthy',
                    'process_id': 12346,
                    'last_activity': '2024-01-01T00:00:00',
                    'current_job_id': None,
                },
            ]
            mock_get_manager.return_value = mock_manager

            response = await client.get('/api/v1/compute/engines')

            assert response.status_code == 200
            result = response.json()
            assert result['total'] == 2
            assert len(result['engines']) == 2
