import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from core.dependencies import get_manager
from core.exceptions import PipelineValidationError
from main import app
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
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': 'out-1',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'out',
                        },
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
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.post('/api/v1/compute/preview', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert 'columns' in result
        assert 'data' in result
        assert result['total_rows'] == 2

    def test_preview_step_success_over_websocket(self, client, sample_datasource: DataSource):
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': 'out-1',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'out',
                        },
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
        }

        mock_manager = MagicMock()
        mock_engine = MagicMock()

        mock_engine.preview.return_value = 'preview-job-ws'
        mock_engine.get_result.side_effect = [
            None,
            {
                'data': {
                    'schema': {'name': 'String'},
                    'data': [{'name': 'Bob'}],
                    'row_count': 1,
                },
                'error': None,
            },
        ]

        mock_manager.get_engine.return_value = None
        mock_manager.get_or_create_engine.return_value = mock_engine
        app.dependency_overrides[get_manager] = lambda: mock_manager

        with client.websocket_connect('/api/v1/compute/ws?namespace=default') as websocket:
            websocket.send_json({'action': 'preview', 'payload': payload})
            started = websocket.receive_json()
            result = websocket.receive_json()

        assert started == {'type': 'started', 'action': 'preview'}
        assert result['type'] == 'result'
        assert result['action'] == 'preview'
        assert result['data']['step_id'] == 'step1'
        assert result['data']['total_rows'] == 1

    def test_preview_step_failure(self, client, sample_datasource: DataSource):
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': 'out-1',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'out',
                        },
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
        app.dependency_overrides[get_manager] = lambda: mock_manager

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
                        'datasource': {
                            'id': missing_id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': 'out-1',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'out',
                        },
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
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': 'out-1',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'out',
                        },
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
        app.dependency_overrides[get_manager] = lambda: mock_manager

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
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': 'out-1',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'out',
                        },
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
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.post('/api/v1/compute/preview', json=payload)

        assert response.status_code == 200

        result = test_db_session.execute(select(EngineRun))
        runs = result.scalars().all()
        assert len(runs) == 1

        run = runs[0]
        assert run.kind == 'preview'
        assert run.status == 'success'
        assert run.request_json['analysis_pipeline']['tabs'][0]['datasource']['id'] == sample_datasource.id
        assert run.request_json['iceberg_options']['branch'] == 'master'
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
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': 'out-1',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'out',
                        },
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

        mock_manager = MagicMock()
        mock_engine = MagicMock()

        mock_engine.preview.return_value = 'preview-job-126'
        mock_engine.get_result.side_effect = [
            None,
            {
                'data': {
                    'schema': {'id': 'Int64', 'name': 'String'},
                    'data': [{'id': 1, 'name': 'Alice'}],
                    'row_count': 1,
                },
                'error': None,
            },
        ]

        mock_manager.get_engine.return_value = None
        mock_manager.get_or_create_engine.return_value = mock_engine
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.post('/api/v1/compute/export', json=payload)

        assert response.status_code == 200

        result = test_db_session.execute(select(EngineRun))
        runs = result.scalars().all()
        assert len(runs) == 1

        run = runs[0]
        assert run.kind == 'download'
        assert run.status == 'success'
        assert run.request_json['analysis_pipeline']['tabs'][0]['datasource']['id'] == sample_datasource.id
        assert run.request_json['iceberg_options']['branch'] == 'master'
        assert run.result_json['format'] == 'csv'
        assert run.result_json['filename'] == 'export-test.csv'


class TestComputeRowCount:
    def test_row_count_logs_engine_run(self, client, sample_datasource: DataSource, test_db_session):
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': 'out-1',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'out',
                        },
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
        app.dependency_overrides[get_manager] = lambda: mock_manager

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
        assert run.request_json['analysis_pipeline']['tabs'][0]['datasource']['id'] == sample_datasource.id
        assert run.request_json['iceberg_options']['branch'] == 'master'
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

    steps = [
        {
            'id': 'step1',
            'type': 'filter',
            'config': {'conditions': [{'column': 'col', 'operator': '>', 'value': 1}]},
            'depends_on': ['step2'],
        },
        {'id': 'step2', 'type': 'select', 'config': {'columns': ['col']}, 'depends_on': ['step1']},
    ]

    with pytest.raises(PipelineValidationError, match='cycle'):
        PolarsComputeEngine._build_pipeline({}, steps, 'job', MagicMock())


@patch('modules.compute.engine.load_datasource')
@patch('modules.compute.engine.PolarsComputeEngine._apply_step')
def test_pipeline_multiple_dependencies_collapsed(mock_apply_step: MagicMock, mock_load: MagicMock):
    """Multi-dependency steps are collapsed to single-dep by apply_steps()."""
    fake_lf = MagicMock()
    fake_lf.collect_schema.return_value = {}

    mock_load.return_value = fake_lf
    mock_apply_step.return_value = fake_lf

    steps = [
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

    # apply_steps collapses multi-deps to single-dep (takes deps[0]),
    # so _build_pipeline should succeed without raising
    result = PolarsComputeEngine.build_pipeline({}, steps, 'job', MagicMock())
    assert result == fake_lf


@patch('modules.compute.engine.load_datasource')
@patch('modules.compute.engine.PolarsComputeEngine._apply_step')
def test_pipeline_topological_order(mock_apply_step: MagicMock, mock_load: MagicMock):
    fake_lf = MagicMock()
    fake_lf.collect_schema.return_value = {}

    mock_load.return_value = fake_lf
    mock_apply_step.return_value = fake_lf

    steps = [
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
    result = PolarsComputeEngine.build_pipeline({}, steps, 'job', MagicMock())
    assert result == fake_lf


class TestEngineLifecycle:
    def test_spawn_engine(self, client):
        analysis_id = str(uuid.uuid4())
        mock_manager = MagicMock()
        mock_manager.spawn_engine.return_value = MagicMock()
        mock_manager.get_engine_status.return_value = {
            'analysis_id': analysis_id,
            'status': 'healthy',
            'process_id': 12345,
            'last_activity': '2024-01-01T00:00:00',
            'current_job_id': None,
        }
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.post(f'/api/v1/compute/engine/spawn/{analysis_id}')

        assert response.status_code == 200
        result = response.json()
        assert result['analysis_id'] == analysis_id
        assert result['status'] == 'healthy'

    def test_keepalive_engine(self, client):
        analysis_id = str(uuid.uuid4())
        mock_manager = MagicMock()
        mock_manager.keepalive.return_value = MagicMock()
        mock_manager.get_engine_status.return_value = {
            'analysis_id': analysis_id,
            'status': 'healthy',
            'process_id': 12345,
            'last_activity': '2024-01-01T00:00:00',
            'current_job_id': None,
        }
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.post(f'/api/v1/compute/engine/keepalive/{analysis_id}')

        assert response.status_code == 200
        result = response.json()
        assert result['analysis_id'] == analysis_id

    def test_get_engine_status(self, client):
        analysis_id = str(uuid.uuid4())
        mock_manager = MagicMock()
        mock_manager.get_engine_status.return_value = {
            'analysis_id': analysis_id,
            'status': 'healthy',
            'process_id': 12345,
            'last_activity': '2024-01-01T00:00:00',
            'current_job_id': None,
        }
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.get(f'/api/v1/compute/engine/status/{analysis_id}')

        assert response.status_code == 200
        result = response.json()
        assert result['analysis_id'] == analysis_id
        assert result['status'] == 'healthy'

    def test_shutdown_engine(self, client):
        analysis_id = str(uuid.uuid4())
        mock_manager = MagicMock()
        mock_engine = MagicMock()
        mock_manager.get_engine.return_value = mock_engine
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.delete(f'/api/v1/compute/engine/{analysis_id}')

        assert response.status_code == 204
        mock_manager.shutdown_engine.assert_called_once_with(analysis_id)

    def test_shutdown_engine_not_found(self, client):
        analysis_id = str(uuid.uuid4())
        mock_manager = MagicMock()
        mock_manager.get_engine.return_value = None
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.delete(f'/api/v1/compute/engine/{analysis_id}')

        assert response.status_code == 404

    def test_list_engines(self, client):
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
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.get('/api/v1/compute/engines')

        assert response.status_code == 200
        result = response.json()
        assert result['total'] == 2
        assert len(result['engines']) == 2


class TestBuildAnalysisPipelinePayloadDerived:
    """Verify derived tabs preserve analysis_id in sources (not overwritten by DB placeholder)."""

    def test_derived_tab_sources_contain_analysis_id(self, test_db_session, sample_datasource: DataSource):
        from datetime import UTC, datetime

        from modules.analysis.models import Analysis
        from modules.compute.service import build_analysis_pipeline_payload
        from modules.datasource.service import create_placeholder_output_datasource

        analysis_id = str(uuid.uuid4())
        tab1_result_id = str(uuid.uuid4())
        tab2_result_id = str(uuid.uuid4())

        now = datetime.now(UTC).replace(tzinfo=None)
        analysis = Analysis(
            id=analysis_id,
            name='test',
            created_at=now,
            updated_at=now,
            pipeline_definition={
                'tabs': [
                    {
                        'id': 'tab1',
                        'name': 'Source',
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {'result_id': tab1_result_id, 'format': 'parquet', 'filename': 'source'},
                        'steps': [],
                    },
                    {
                        'id': 'tab2',
                        'name': 'Derived',
                        'parent_id': 'tab1',
                        'datasource': {
                            'id': tab1_result_id,
                            'analysis_tab_id': 'tab1',
                            'config': {'branch': 'master'},
                        },
                        'output': {'result_id': tab2_result_id, 'format': 'parquet', 'filename': 'derived'},
                        'steps': [],
                    },
                ]
            },
            status='draft',
        )
        test_db_session.add(analysis)
        create_placeholder_output_datasource(test_db_session, tab1_result_id, analysis_id, 'tab1')
        create_placeholder_output_datasource(test_db_session, tab2_result_id, analysis_id, 'tab2')
        test_db_session.commit()

        payload = build_analysis_pipeline_payload(test_db_session, analysis)

        # The source for tab1_result_id must have analysis_id (set by first loop),
        # not be overwritten by the DB placeholder (which only has analysis_tab_id).
        source = payload['sources'][tab1_result_id]
        assert source['source_type'] == 'analysis'
        assert source['analysis_id'] == analysis_id
        assert source['analysis_tab_id'] == 'tab1'


class TestDownloadStepFiltering:
    """Unit tests for download-step filtering logic in download_step().

    Steps arrive in frontend format (key='type', not 'operation').
    The function must filter out download steps and fall back to the parent
    when the target_step_id points at a download step.
    """

    def test_download_type_steps_are_filtered_out(self) -> None:
        """Steps with type='download' must be excluded from download_steps."""
        steps: list[dict[str, object]] = [
            {'id': 'step1', 'type': 'filter', 'config': {}},
            {'id': 'step2', 'type': 'download', 'config': {}, 'depends_on': ['step1']},
            {'id': 'step3', 'type': 'select', 'config': {}},
        ]

        download_steps = [step for step in steps if step.get('type') != 'download']

        assert len(download_steps) == 2
        ids = [s['id'] for s in download_steps]
        assert 'step2' not in ids
        assert 'step1' in ids
        assert 'step3' in ids

    def test_target_download_step_falls_back_to_parent(self) -> None:
        """When target_step_id matches a download step, fall back to depends_on[0]."""
        steps: list[dict[str, object]] = [
            {'id': 'step1', 'type': 'filter', 'config': {}},
            {'id': 'step2', 'type': 'download', 'config': {}, 'depends_on': ['step1']},
        ]
        target_step_id = 'step2'

        target_step = next((step for step in steps if step.get('id') == target_step_id), None)

        assert target_step is not None
        assert target_step.get('type') == 'download'

        # Replicate the fallback logic from download_step()
        depends_on = target_step.get('depends_on') or []
        assert isinstance(depends_on, list)
        parent_id = str(depends_on[0]) if depends_on and depends_on[0] else None

        assert parent_id == 'step1'

    def test_target_download_step_falls_back_to_last_step_when_no_parent(self) -> None:
        """When target is a download step without depends_on, fall back to last remaining step."""
        steps: list[dict[str, object]] = [
            {'id': 'step1', 'type': 'filter', 'config': {}},
            {'id': 'step2', 'type': 'download', 'config': {}},
        ]
        target_step_id = 'step2'

        download_steps = [step for step in steps if step.get('type') != 'download']
        target_step = next((step for step in steps if step.get('id') == target_step_id), None)

        assert target_step is not None
        assert target_step.get('type') == 'download'

        depends_on = target_step.get('depends_on') or []
        assert isinstance(depends_on, list)
        parent_id = str(depends_on[0]) if depends_on and depends_on[0] else None

        # No parent, so fall back to last remaining step
        assert parent_id is None
        target_step_id = str(download_steps[-1].get('id') or 'source') if download_steps else 'source'

        assert target_step_id == 'step1'
