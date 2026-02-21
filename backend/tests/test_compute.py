import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from core.exceptions import PipelineValidationError
from modules.compute.engine import PolarsComputeEngine
from modules.datasource.models import DataSource
from modules.engine_runs.models import EngineRun


class TestComputePreview:
    def test_preview_step_success(self, client, sample_datasource: DataSource):
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource_id': sample_datasource.id,
                        'datasource_config': {},
                        'output_datasource_id': 'out-1',
                        'steps': [
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
                    }
                ],
                'sources': {
                    sample_datasource.id: {
                        'source_type': sample_datasource.source_type,
                        **sample_datasource.config,
                    },
                    'out-1': {
                        'source_type': 'analysis',
                        'analysis_id': 'analysis-id',
                        'analysis_tab_id': 'tab1',
                    },
                },
            },
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

            response = client.post('/api/v1/compute/preview', json=payload)

            assert response.status_code == 200
            result = response.json()

            assert 'columns' in result
            assert 'data' in result
            assert result['total_rows'] == 2

    def test_preview_step_failure(self, client, sample_datasource: DataSource):
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource_id': sample_datasource.id,
                        'datasource_config': {},
                        'output_datasource_id': 'out-1',
                        'steps': [
                            {
                                'id': 'step1',
                                'type': 'invalid_operation',
                                'config': {},
                            }
                        ],
                    }
                ],
                'sources': {
                    sample_datasource.id: {
                        'source_type': sample_datasource.source_type,
                        **sample_datasource.config,
                    },
                    'out-1': {
                        'source_type': 'analysis',
                        'analysis_id': 'analysis-id',
                        'analysis_tab_id': 'tab1',
                    },
                },
            },
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

            response = client.post('/api/v1/compute/preview', json=payload)

            # Failed pipeline execution returns 500
            assert response.status_code in [404, 500]

    def test_preview_step_datasource_not_found(self, client):
        missing_id = str(uuid.uuid4())
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource_id': missing_id,
                        'datasource_config': {},
                        'output_datasource_id': 'out-1',
                        'steps': [],
                    }
                ],
                'sources': {
                    missing_id: {
                        'source_type': 'file',
                    },
                    'out-1': {
                        'source_type': 'analysis',
                        'analysis_id': 'analysis-id',
                        'analysis_tab_id': 'tab1',
                    },
                },
            },
            'target_step_id': 'step1',
        }

        response = client.post('/api/v1/compute/preview', json=payload)

        assert response.status_code == 500

    def test_preview_step_specific_target(self, client, sample_datasource: DataSource):
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource_id': sample_datasource.id,
                        'datasource_config': {},
                        'output_datasource_id': 'out-1',
                        'steps': [
                            {'id': 'step1', 'type': 'filter', 'config': {}},
                            {'id': 'step2', 'type': 'select', 'config': {}},
                            {'id': 'step3', 'type': 'sort', 'config': {}},
                        ],
                    }
                ],
                'sources': {
                    sample_datasource.id: {
                        'source_type': sample_datasource.source_type,
                        **sample_datasource.config,
                    },
                    'out-1': {
                        'source_type': 'analysis',
                        'analysis_id': 'analysis-id',
                        'analysis_tab_id': 'tab1',
                    },
                },
            },
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

            response = client.post('/api/v1/compute/preview', json=payload)

            assert response.status_code == 200

    def test_preview_logs_engine_run(self, client, sample_datasource: DataSource, test_db_session):
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource_id': sample_datasource.id,
                        'datasource_config': {},
                        'output_datasource_id': 'out-1',
                        'steps': [
                            {
                                'id': 'step1',
                                'type': 'filter',
                                'config': {'column': 'age', 'operator': '>', 'value': 25},
                            }
                        ],
                    }
                ],
                'sources': {
                    sample_datasource.id: {
                        'source_type': sample_datasource.source_type,
                        **sample_datasource.config,
                    },
                    'out-1': {
                        'source_type': 'analysis',
                        'analysis_id': 'analysis-id',
                        'analysis_tab_id': 'tab1',
                    },
                },
            },
            'target_step_id': 'step1',
            'row_limit': 10,
            'page': 1,
        }

        with patch('modules.compute.service.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_engine = MagicMock()

            mock_engine.preview.return_value = 'preview-job-126'
            mock_engine.get_result.side_effect = [
                None,
                {
                    'data': {
                        'schema': {'name': 'String'},
                        'data': [{'name': 'Bob'}],
                        'row_count': 1,
                        'query_plans': {'optimized': 'opt', 'unoptimized': 'unopt'},
                    },
                    'error': None,
                },
            ]

            mock_manager.get_engine.return_value = None
            mock_manager.get_or_create_engine.return_value = mock_engine
            mock_get_manager.return_value = mock_manager

            response = client.post('/api/v1/compute/preview', json=payload)

            assert response.status_code == 200

        result = test_db_session.execute(select(EngineRun))
        runs = result.scalars().all()
        assert len(runs) == 1

        run = runs[0]
        assert run.kind == 'preview'
        assert run.status == 'success'
        assert run.request_json['analysis_pipeline']['tabs'][0]['datasource_id'] == sample_datasource.id
        assert 'data' not in run.result_json
        assert run.result_json['query_plans']['optimized'] == 'opt'


class TestComputeExport:
    def test_export_logs_engine_run(self, client, sample_datasource: DataSource, test_db_session):
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource_id': sample_datasource.id,
                        'datasource_config': {},
                        'output_datasource_id': 'out-1',
                        'steps': [
                            {
                                'id': 'step1',
                                'type': 'select',
                                'config': {'columns': ['name']},
                            }
                        ],
                    }
                ],
                'sources': {
                    sample_datasource.id: {
                        'source_type': sample_datasource.source_type,
                        **sample_datasource.config,
                    },
                    'out-1': {
                        'source_type': 'analysis',
                        'analysis_id': 'analysis-id',
                        'analysis_tab_id': 'tab1',
                    },
                },
            },
            'target_step_id': 'step1',
            'format': 'csv',
            'filename': 'export-test',
            'destination': 'download',
        }

        def write_export(*_args, **kwargs):
            output_path = kwargs.get('output_path')
            if not output_path:
                return None
            with open(output_path, 'wb') as handle:
                handle.write(b'id,name\n1,Alice\n')
            return None

        with patch('modules.compute.service.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_engine = MagicMock()

            mock_engine.export.side_effect = write_export
            mock_engine.get_result.side_effect = [
                None,
                {
                    'data': {
                        'row_count': 1,
                        'export_format': 'csv',
                        'query_plans': {'optimized': 'opt', 'unoptimized': 'unopt'},
                    },
                    'error': None,
                },
            ]

            mock_manager.get_engine.return_value = None
            mock_manager.get_or_create_engine.return_value = mock_engine
            mock_get_manager.return_value = mock_manager

            response = client.post('/api/v1/compute/export', json=payload)

            assert response.status_code == 200

        result = test_db_session.execute(select(EngineRun))
        runs = result.scalars().all()
        assert len(runs) == 1

        run = runs[0]
        assert run.kind == 'export'
        assert run.status == 'success'
        assert run.request_json['analysis_pipeline']['tabs'][0]['datasource_id'] == sample_datasource.id
        assert 'data' not in run.result_json
        assert run.result_json['query_plans']['optimized'] == 'opt'
        assert run.result_json['file_size_bytes'] > 0


class TestComputeRowCount:
    def test_row_count_logs_engine_run(self, client, sample_datasource: DataSource, test_db_session):
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource_id': sample_datasource.id,
                        'datasource_config': {},
                        'output_datasource_id': 'out-1',
                        'steps': [
                            {
                                'id': 'step1',
                                'type': 'select',
                                'config': {'columns': ['name']},
                            }
                        ],
                    }
                ],
                'sources': {
                    sample_datasource.id: {
                        'source_type': sample_datasource.source_type,
                        **sample_datasource.config,
                    },
                    'out-1': {
                        'source_type': 'analysis',
                        'analysis_id': 'analysis-id',
                        'analysis_tab_id': 'tab1',
                    },
                },
            },
            'target_step_id': 'step1',
        }

        with patch('modules.compute.service.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_engine = MagicMock()

            mock_engine.get_row_count.return_value = 'row-count-job-123'
            mock_engine.get_result.side_effect = [
                None,
                {
                    'data': {
                        'row_count': 42,
                    },
                    'error': None,
                },
            ]

            mock_manager.get_engine.return_value = None
            mock_manager.get_or_create_engine.return_value = mock_engine
            mock_get_manager.return_value = mock_manager

            response = client.post('/api/v1/compute/row-count', json=payload)

            assert response.status_code == 200
            result = response.json()
            assert result['row_count'] == 42

        test_db_session.expire_all()
        runs = test_db_session.execute(select(EngineRun)).scalars().all()
        assert len(runs) == 1

        run = runs[0]
        assert run.kind == 'row_count'
        assert run.status == 'success'
        assert run.request_json['analysis_pipeline']['tabs'][0]['datasource_id'] == sample_datasource.id
        assert run.result_json['row_count'] == 42


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
        {
            'id': 'step1',
            'type': 'filter',
            'config': {'conditions': [{'column': 'col', 'operator': '>', 'value': 1}]},
            'depends_on': ['step2'],
        },
        {'id': 'step2', 'type': 'select', 'config': {'columns': ['col']}, 'depends_on': ['step1']},
    ]

    with pytest.raises(PipelineValidationError, match='cycle'):
        PolarsComputeEngine._build_pipeline({}, pipeline_steps, 'job', MagicMock())


@patch('modules.compute.engine.load_datasource')
@patch('modules.compute.engine.PolarsComputeEngine._apply_step')
def test_pipeline_multiple_dependencies(mock_apply_step: MagicMock, mock_load: MagicMock):
    mock_load.return_value = MagicMock()
    mock_apply_step.side_effect = lambda frame, _step, **kwargs: frame

    pipeline_steps = [
        {
            'id': 'step1',
            'type': 'filter',
            'config': {'conditions': [{'column': 'col', 'operator': '>', 'value': 1}]},
            'depends_on': [],
        },
        {
            'id': 'step2',
            'type': 'select',
            'config': {'columns': ['col']},
            'depends_on': ['step1', 'step3'],
        },
        {'id': 'step3', 'type': 'sort', 'config': {'columns': ['col'], 'descending': [False]}, 'depends_on': []},
    ]

    with pytest.raises(PipelineValidationError, match='multiple dependencies'):
        PolarsComputeEngine._build_pipeline({}, pipeline_steps, 'job', MagicMock())


@patch('modules.compute.engine.load_datasource')
@patch('modules.compute.engine.PolarsComputeEngine._apply_step')
def test_pipeline_topological_order(mock_apply_step: MagicMock, mock_load: MagicMock):
    fake_lf = MagicMock()
    fake_lf.collect_schema.return_value = {}

    mock_load.return_value = fake_lf
    mock_apply_step.return_value = fake_lf

    pipeline_steps = [
        {
            'id': 'step1',
            'type': 'filter',
            'config': {'conditions': [{'column': 'col', 'operator': '>', 'value': 1}]},
            'depends_on': [],
        },
        {'id': 'step2', 'type': 'select', 'config': {'columns': ['col']}, 'depends_on': ['step1']},
        {
            'id': 'step3',
            'type': 'sort',
            'config': {'columns': ['col'], 'descending': [False]},
            'depends_on': ['step2'],
        },
    ]

    # build_pipeline returns just the LazyFrame
    result = PolarsComputeEngine.build_pipeline({}, pipeline_steps, 'job', MagicMock())
    assert result == fake_lf


class TestEngineLifecycle:
    def test_spawn_engine(self, client):
        analysis_id = str(uuid.uuid4())

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

            response = client.post(f'/api/v1/compute/engine/spawn/{analysis_id}')

            assert response.status_code == 200
            result = response.json()
            assert result['analysis_id'] == analysis_id
            assert result['status'] == 'healthy'

    def test_keepalive_engine(self, client):
        analysis_id = str(uuid.uuid4())

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

            response = client.post(f'/api/v1/compute/engine/keepalive/{analysis_id}')

            assert response.status_code == 200
            result = response.json()
            assert result['analysis_id'] == analysis_id

    def test_get_engine_status(self, client):
        analysis_id = str(uuid.uuid4())

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

            response = client.get(f'/api/v1/compute/engine/status/{analysis_id}')

            assert response.status_code == 200
            result = response.json()
            assert result['analysis_id'] == analysis_id
            assert result['status'] == 'healthy'

    def test_shutdown_engine(self, client):
        analysis_id = str(uuid.uuid4())

        with patch('modules.compute.routes.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_engine = MagicMock()
            mock_manager.get_engine.return_value = mock_engine
            mock_get_manager.return_value = mock_manager

            response = client.delete(f'/api/v1/compute/engine/{analysis_id}')

            assert response.status_code == 204
            mock_manager.shutdown_engine.assert_called_once_with(analysis_id)

    def test_shutdown_engine_not_found(self, client):
        analysis_id = str(uuid.uuid4())

        with patch('modules.compute.routes.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_manager.get_engine.return_value = None
            mock_get_manager.return_value = mock_manager

            response = client.delete(f'/api/v1/compute/engine/{analysis_id}')

        assert response.status_code == 404

    def test_list_engines(self, client):
        with patch('modules.compute.routes.get_manager') as mock_get_manager:
            mock_manager = MagicMock()
            mock_manager.list_all_engine_statuses.return_value = [
                {
                    'analysis_id': str(uuid.uuid4()),
                    'status': 'healthy',
                    'process_id': 12345,
                    'last_activity': '2024-01-01T00:00:00',
                    'current_job_id': None,
                },
                {
                    'analysis_id': str(uuid.uuid4()),
                    'status': 'healthy',
                    'process_id': 12346,
                    'last_activity': '2024-01-01T00:00:00',
                    'current_job_id': None,
                },
            ]
            mock_get_manager.return_value = mock_manager

            response = client.get('/api/v1/compute/engines')

            assert response.status_code == 200
            result = response.json()
            assert result['total'] == 2
            assert len(result['engines']) == 2
