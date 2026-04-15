import uuid

from modules.datasource.models import DataSource


def _create_analysis_with_join(client, left_ds_id: str, right_ds_id: str) -> str:
    payload = {
        'name': 'Snippet Export Analysis',
        'description': 'pipeline for snippet export tests',
        'tabs': [
            {
                'id': 'tab-right',
                'name': 'Right Source',
                'parent_id': None,
                'datasource': {
                    'id': right_ds_id,
                    'analysis_tab_id': None,
                    'config': {'branch': 'master'},
                },
                'output': {
                    'result_id': str(uuid.uuid4()),
                    'datasource_type': 'iceberg',
                    'format': 'parquet',
                    'filename': 'right_source',
                },
                'steps': [{'id': 'view-right', 'type': 'view', 'config': {}, 'depends_on': []}],
            },
            {
                'id': 'tab-left',
                'name': 'Left Source',
                'parent_id': None,
                'datasource': {
                    'id': left_ds_id,
                    'analysis_tab_id': None,
                    'config': {'branch': 'master'},
                },
                'output': {
                    'result_id': str(uuid.uuid4()),
                    'datasource_type': 'iceberg',
                    'format': 'parquet',
                    'filename': 'left_source',
                },
                'steps': [
                    {'id': 'view-left', 'type': 'view', 'config': {}, 'depends_on': []},
                    {
                        'id': 'filter-left',
                        'type': 'filter',
                        'config': {
                            'conditions': [
                                {
                                    'column': 'age',
                                    'operator': '>',
                                    'value': 20,
                                    'value_type': 'number',
                                },
                            ],
                            'logic': 'AND',
                        },
                        'depends_on': ['view-left'],
                    },
                    {
                        'id': 'join-left',
                        'type': 'join',
                        'config': {
                            'how': 'left',
                            'right_source': 'tab-right',
                            'join_columns': [
                                {
                                    'id': 'join-1',
                                    'left_column': 'id',
                                    'right_column': 'id',
                                },
                            ],
                            'right_columns': ['name'],
                            'suffix': '_right',
                        },
                        'depends_on': ['filter-left'],
                    },
                    {
                        'id': 'groupby-left',
                        'type': 'groupby',
                        'config': {
                            'group_by': ['city'],
                            'aggregations': [
                                {
                                    'column': 'age',
                                    'function': 'count',
                                    'alias': 'row_count',
                                },
                            ],
                        },
                        'depends_on': ['join-left'],
                    },
                    {
                        'id': 'sort-left',
                        'type': 'sort',
                        'config': {'columns': ['row_count'], 'descending': [True]},
                        'depends_on': ['groupby-left'],
                    },
                ],
            },
        ],
    }
    response = client.post('/api/v1/analysis', json=payload)
    assert response.status_code == 200
    return response.json()['id']


def test_export_code_polars_includes_join_groupby_sort(client, sample_datasources: list[DataSource]) -> None:
    analysis_id = _create_analysis_with_join(client, sample_datasources[0].id, sample_datasources[1].id)

    response = client.post(
        f'/api/v1/analysis/{analysis_id}/export-code',
        json={'format': 'polars'},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload['format'] == 'polars'
    assert payload['filename'].endswith('_pipeline.py')
    assert payload['warnings'] == []
    assert 'import polars as pl' in payload['code']
    assert 'tab_1_right_source_source.show(limit=5)' in payload['code']
    assert 'tab_2_left_source_source.show(limit=5)' in payload['code']
    assert 'tab_1_right_source_step_1 =' not in payload['code']
    assert 'tab_2_left_source_step_1 =' not in payload['code']
    assert '.join(' in payload['code']
    assert '.group_by(' in payload['code']
    assert '.sort(' in payload['code']
    assert '.collect()' in payload['code']
    compile(payload['code'], '<export-polars>', 'exec')


def test_export_code_sql_tab_scope_uses_tab_filename(client, sample_datasources: list[DataSource]) -> None:
    analysis_id = _create_analysis_with_join(client, sample_datasources[0].id, sample_datasources[1].id)

    response = client.post(
        f'/api/v1/analysis/{analysis_id}/export-code',
        json={'format': 'sql', 'tab_id': 'tab-left'},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload['format'] == 'sql'
    assert payload['tab_id'] == 'tab-left'
    assert payload['filename'].endswith('_left_source.sql')
    assert 'WITH' in payload['code']
    assert 'JOIN' in payload['code']
    assert 'GROUP BY' in payload['code']
    assert 'ORDER BY' in payload['code']


def test_export_code_warns_for_untranslatable_step(client, sample_datasource: DataSource) -> None:
    payload = {
        'name': 'Unsupported Step Analysis',
        'tabs': [
            {
                'id': 'tab-unsupported',
                'name': 'Unsupported Tab',
                'parent_id': None,
                'datasource': {
                    'id': sample_datasource.id,
                    'analysis_tab_id': None,
                    'config': {'branch': 'master'},
                },
                'output': {
                    'result_id': str(uuid.uuid4()),
                    'datasource_type': 'iceberg',
                    'format': 'parquet',
                    'filename': 'unsupported',
                },
                'steps': [
                    {'id': 'step-view', 'type': 'view', 'config': {}, 'depends_on': []},
                    {'id': 'step-ai', 'type': 'ai', 'config': {}, 'depends_on': ['step-view']},
                ],
            },
        ],
    }
    create_response = client.post('/api/v1/analysis', json=payload)
    assert create_response.status_code == 200
    analysis_id = create_response.json()['id']

    response = client.post(
        f'/api/v1/analysis/{analysis_id}/export-code',
        json={'format': 'sql', 'tab_id': 'tab-unsupported'},
    )
    assert response.status_code == 200
    result = response.json()
    assert result['warnings']
    assert any('ai' in warning.lower() for warning in result['warnings'])
    assert '-- WARNING:' in result['code']
    assert 'Original config' in result['code']


def test_export_code_rejects_missing_tab(client, sample_analysis) -> None:
    response = client.post(
        f'/api/v1/analysis/{sample_analysis.id}/export-code',
        json={'format': 'sql', 'tab_id': 'does-not-exist'},
    )
    assert response.status_code == 400
    assert 'not found' in response.json()['detail']
