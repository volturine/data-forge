import uuid
from unittest.mock import patch

from modules.analysis import dashboard_service
from modules.datasource.models import DataSource


def _base_tab(datasource: DataSource) -> dict:
    return {
        'id': 'tab-source',
        'name': 'Source',
        'parent_id': None,
        'datasource': {
            'id': datasource.id,
            'analysis_tab_id': None,
            'config': {'branch': 'master'},
        },
        'output': {
            'result_id': str(uuid.uuid4()),
            'format': 'parquet',
            'filename': 'source_output',
        },
        'steps': [
            {
                'id': 'filter-step',
                'type': 'filter',
                'config': {
                    'conditions': [
                        {
                            'column': 'city',
                            'operator': 'in',
                            'value': {'kind': 'variable_ref', 'variable_id': 'city_filter'},
                            'value_type': 'string',
                        },
                    ],
                    'logic': 'AND',
                },
                'depends_on': [],
            },
        ],
    }


def test_create_analysis_with_dashboard_extensions_persists_payload(client, sample_datasource: DataSource):
    payload = {
        'name': 'Dashboard Analysis',
        'description': 'analysis with dashboard metadata',
        'tabs': [_base_tab(sample_datasource)],
        'variables': [
            {
                'id': 'city_filter',
                'label': 'City',
                'type': 'multi_select',
                'default_value': ['NYC'],
                'required': True,
                'options': [
                    {'label': 'NYC', 'value': 'NYC'},
                    {'label': 'LA', 'value': 'LA'},
                ],
            },
        ],
        'dashboards': [
            {
                'id': 'overview',
                'name': 'Overview',
                'description': 'Operational dashboard',
                'layout': [
                    {'widget_id': 'dataset', 'x': 0, 'y': 0, 'w': 6, 'h': 2},
                    {'widget_id': 'metric', 'x': 6, 'y': 0, 'w': 3, 'h': 2},
                ],
                'widgets': [
                    {
                        'id': 'dataset',
                        'type': 'dataset_preview',
                        'title': 'Rows',
                        'source_tab_id': 'tab-source',
                        'config': {'page_size': 25, 'searchable': True},
                    },
                    {
                        'id': 'metric',
                        'type': 'metric_kpi',
                        'title': 'Count',
                        'source_tab_id': 'tab-source',
                        'config': {'label': 'Rows', 'aggregation': 'count'},
                    },
                ],
            },
        ],
    }

    response = client.post('/api/v1/analysis', json=payload)

    assert response.status_code == 200
    result = response.json()
    assert result['pipeline_definition']['variables'][0]['id'] == 'city_filter'
    assert result['pipeline_definition']['dashboards'][0]['id'] == 'overview'


def test_create_analysis_rejects_invalid_variable_binding_path(client, sample_datasource: DataSource):
    payload = {
        'name': 'Invalid Dashboard Analysis',
        'tabs': [
            {
                **_base_tab(sample_datasource),
                'steps': [
                    {
                        'id': 'select-step',
                        'type': 'select',
                        'config': {
                            'columns': [
                                {
                                    'kind': 'variable_ref',
                                    'variable_id': 'city_filter',
                                },
                            ],
                        },
                        'depends_on': [],
                    },
                ],
            },
        ],
        'variables': [
            {
                'id': 'city_filter',
                'label': 'City',
                'type': 'single_select',
                'default_value': 'NYC',
                'required': True,
                'options': [{'label': 'NYC', 'value': 'NYC'}],
            },
        ],
        'dashboards': [],
    }

    response = client.post('/api/v1/analysis', json=payload)

    assert response.status_code == 400
    assert 'Variable refs are not supported' in response.json()['detail']


def test_get_dashboard_detail_resolves_source_backed_options(client, sample_datasource: DataSource):
    source_tab = _base_tab(sample_datasource)
    source_tab['steps'] = []
    create_payload = {
        'name': 'Dashboard Options Analysis',
        'tabs': [source_tab],
        'variables': [
            {
                'id': 'city_filter',
                'label': 'City',
                'type': 'single_select',
                'default_value': 'NYC',
                'required': True,
                'option_source': {'tab_id': 'tab-source', 'column': 'city', 'limit': 10},
            },
        ],
        'dashboards': [
            {
                'id': 'overview',
                'name': 'Overview',
                'layout': [{'widget_id': 'dataset', 'x': 0, 'y': 0, 'w': 6, 'h': 2}],
                'widgets': [
                    {
                        'id': 'dataset',
                        'type': 'dataset_preview',
                        'title': 'Rows',
                        'source_tab_id': 'tab-source',
                        'config': {'page_size': 25, 'searchable': True},
                    },
                ],
            },
        ],
    }
    create = client.post('/api/v1/analysis', json=create_payload)
    analysis_id = create.json()['id']

    response = client.get(f'/api/v1/analysis/{analysis_id}/dashboards/overview')

    assert response.status_code == 200
    detail = response.json()
    values = {option['value'] for option in detail['variables'][0]['options']}
    assert {'NYC', 'LA', 'Chicago', 'Houston', 'Phoenix'} <= values


def test_create_analysis_rejects_invalid_chart_interaction_config(client, sample_datasource: DataSource):
    payload = {
        'name': 'Invalid Chart Config',
        'tabs': [_base_tab(sample_datasource)],
        'variables': [
            {
                'id': 'city_filter',
                'label': 'City',
                'type': 'multi_select',
                'default_value': ['NYC'],
                'required': True,
                'options': [{'label': 'NYC', 'value': 'NYC'}],
            },
        ],
        'dashboards': [
            {
                'id': 'overview',
                'name': 'Overview',
                'layout': [{'widget_id': 'chart', 'x': 0, 'y': 0, 'w': 6, 'h': 2}],
                'widgets': [
                    {
                        'id': 'chart',
                        'type': 'chart',
                        'title': 'Age by city',
                        'source_tab_id': 'tab-source',
                        'config': {
                            'chart_type': 'bar',
                            'x_column': 'city',
                            'y_column': 'age',
                            'legend_position': 'middle',
                        },
                    },
                ],
            },
        ],
    }

    response = client.post('/api/v1/analysis', json=payload)

    assert response.status_code == 400
    assert 'legend_position must be one of' in response.json()['detail']


def test_run_dashboard_executes_widgets_with_variable_state(client, sample_datasource: DataSource):
    create_payload = {
        'name': 'Dashboard Runtime Analysis',
        'tabs': [_base_tab(sample_datasource)],
        'variables': [
            {
                'id': 'city_filter',
                'label': 'City',
                'type': 'multi_select',
                'default_value': ['NYC', 'LA'],
                'required': True,
                'options': [
                    {'label': 'NYC', 'value': 'NYC'},
                    {'label': 'LA', 'value': 'LA'},
                    {'label': 'Chicago', 'value': 'Chicago'},
                ],
            },
        ],
        'dashboards': [
            {
                'id': 'overview',
                'name': 'Overview',
                'layout': [
                    {'widget_id': 'dataset', 'x': 0, 'y': 0, 'w': 6, 'h': 2},
                    {'widget_id': 'chart', 'x': 6, 'y': 0, 'w': 6, 'h': 2},
                    {'widget_id': 'metric', 'x': 0, 'y': 2, 'w': 3, 'h': 2},
                    {'widget_id': 'header', 'x': 3, 'y': 2, 'w': 9, 'h': 1},
                ],
                'widgets': [
                    {
                        'id': 'dataset',
                        'type': 'dataset_preview',
                        'title': 'Rows',
                        'source_tab_id': 'tab-source',
                        'config': {'page_size': 25, 'searchable': True},
                    },
                    {
                        'id': 'chart',
                        'type': 'chart',
                        'title': 'Age by city',
                        'source_tab_id': 'tab-source',
                        'config': {'chart_type': 'bar', 'x_column': 'city', 'y_column': 'age', 'aggregation': 'sum'},
                    },
                    {
                        'id': 'metric',
                        'type': 'metric_kpi',
                        'title': 'Count',
                        'source_tab_id': 'tab-source',
                        'config': {'label': 'Filtered rows', 'aggregation': 'count'},
                    },
                    {
                        'id': 'header',
                        'type': 'text_header',
                        'title': 'Header',
                        'config': {'text': 'Sales Overview', 'level': 2},
                    },
                ],
            },
        ],
    }
    create = client.post('/api/v1/analysis', json=create_payload)
    analysis_id = create.json()['id']

    response = client.post(
        f'/api/v1/analysis/{analysis_id}/dashboards/overview/run',
        json={'variable_values': {'city_filter': ['NYC', 'LA']}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['variable_state']['city_filter'] == ['NYC', 'LA']
    assert set(payload['widget_dependencies']['dataset']) == {'city_filter'}

    widgets = {widget['widget_id']: widget for widget in payload['widgets']}
    assert widgets['dataset']['dataset']['row_count'] == 2
    assert len(widgets['dataset']['dataset']['rows']) == 2
    assert widgets['metric']['metric']['value'] == 2
    chart = widgets['chart']['chart']
    assert chart['data']
    assert chart['schema'] == {'x': 'String', 'y': 'Int64'}
    for row in chart['data']:
        assert set(row) == {'x', 'y'}
        assert 'city' not in row
        assert 'age' not in row


def test_run_dashboard_applies_chart_selection_filters_to_sibling_widgets(client, sample_datasource: DataSource):
    create_payload = {
        'name': 'Dashboard Selection Analysis',
        'tabs': [_base_tab(sample_datasource)],
        'variables': [
            {
                'id': 'city_filter',
                'label': 'City',
                'type': 'multi_select',
                'default_value': ['NYC', 'LA'],
                'required': True,
                'options': [
                    {'label': 'NYC', 'value': 'NYC'},
                    {'label': 'LA', 'value': 'LA'},
                    {'label': 'Chicago', 'value': 'Chicago'},
                ],
            },
        ],
        'dashboards': [
            {
                'id': 'overview',
                'name': 'Overview',
                'layout': [
                    {'widget_id': 'chart', 'x': 0, 'y': 0, 'w': 6, 'h': 2},
                    {'widget_id': 'dataset', 'x': 6, 'y': 0, 'w': 6, 'h': 2},
                    {'widget_id': 'metric', 'x': 0, 'y': 2, 'w': 4, 'h': 2},
                ],
                'widgets': [
                    {
                        'id': 'chart',
                        'type': 'chart',
                        'title': 'Age by city',
                        'source_tab_id': 'tab-source',
                        'config': {
                            'chart_type': 'bar',
                            'x_column': 'city',
                            'y_column': 'age',
                            'selection_enabled': True,
                            'selection_filters_widgets': True,
                        },
                    },
                    {
                        'id': 'dataset',
                        'type': 'dataset_preview',
                        'title': 'Rows',
                        'source_tab_id': 'tab-source',
                        'config': {'page_size': 25, 'searchable': True},
                    },
                    {
                        'id': 'metric',
                        'type': 'metric_kpi',
                        'title': 'Count',
                        'source_tab_id': 'tab-source',
                        'config': {'label': 'Filtered rows', 'aggregation': 'count'},
                    },
                ],
            },
        ],
    }
    create = client.post('/api/v1/analysis', json=create_payload)
    analysis_id = create.json()['id']

    response = client.post(
        f'/api/v1/analysis/{analysis_id}/dashboards/overview/run',
        json={
            'variable_values': {'city_filter': ['NYC', 'LA']},
            'selection_filters': {'chart': {'column': 'city', 'values': ['NYC']}},
        },
    )

    assert response.status_code == 200
    widgets = {widget['widget_id']: widget for widget in response.json()['widgets']}
    assert widgets['chart']['status'] == 'success'
    chart = widgets['chart']['chart']
    assert chart['config']['selection_enabled'] is True
    assert chart['config']['selection_filters_widgets'] is True
    assert chart['data']
    for row in chart['data']:
        assert set(row) == {'x', 'y'}
        assert 'city' not in row
        assert 'age' not in row
    assert widgets['dataset']['dataset']['row_count'] == 1
    assert widgets['dataset']['dataset']['rows'][0]['city'] == 'NYC'
    assert widgets['metric']['metric']['value'] == 1


def test_run_dashboard_returns_chart_error_instead_of_raw_preview_fallback(client, sample_datasource: DataSource):
    create_payload = {
        'name': 'Dashboard Chart Fallback Analysis',
        'tabs': [_base_tab(sample_datasource)],
        'variables': [
            {
                'id': 'city_filter',
                'label': 'City',
                'type': 'multi_select',
                'default_value': ['NYC', 'LA'],
                'required': True,
                'options': [
                    {'label': 'NYC', 'value': 'NYC'},
                    {'label': 'LA', 'value': 'LA'},
                    {'label': 'Chicago', 'value': 'Chicago'},
                ],
            },
        ],
        'dashboards': [
            {
                'id': 'overview',
                'name': 'Overview',
                'layout': [
                    {'widget_id': 'dataset', 'x': 0, 'y': 0, 'w': 6, 'h': 2},
                    {'widget_id': 'chart', 'x': 6, 'y': 0, 'w': 6, 'h': 2},
                ],
                'widgets': [
                    {
                        'id': 'dataset',
                        'type': 'dataset_preview',
                        'title': 'Rows',
                        'source_tab_id': 'tab-source',
                        'config': {'page_size': 25, 'searchable': True},
                    },
                    {
                        'id': 'chart',
                        'type': 'chart',
                        'title': 'Age by city',
                        'source_tab_id': 'tab-source',
                        'config': {'chart_type': 'bar', 'x_column': 'city', 'y_column': 'age', 'aggregation': 'sum'},
                    },
                ],
            },
        ],
    }
    create = client.post('/api/v1/analysis', json=create_payload)
    analysis_id = create.json()['id']

    with patch('modules.compute.operations.plot.compute_chart_data', side_effect=RuntimeError('chart transform failed')):
        response = client.post(
            f'/api/v1/analysis/{analysis_id}/dashboards/overview/run',
            json={'variable_values': {'city_filter': ['NYC', 'LA']}},
        )

    assert response.status_code == 200
    widgets = {widget['widget_id']: widget for widget in response.json()['widgets']}
    assert widgets['dataset']['status'] == 'success'
    assert widgets['dataset']['dataset']['rows']
    assert widgets['chart']['status'] == 'error'
    assert widgets['chart']['chart'] is None
    assert widgets['chart']['error'] == 'chart transform failed'


def test_run_dashboard_reuses_preview_results_within_request(client, sample_datasource: DataSource):
    create_payload = {
        'name': 'Dashboard Local Preview Cache Analysis',
        'tabs': [_base_tab(sample_datasource)],
        'variables': [
            {
                'id': 'city_filter',
                'label': 'City',
                'type': 'multi_select',
                'default_value': ['NYC', 'LA'],
                'required': True,
                'options': [
                    {'label': 'NYC', 'value': 'NYC'},
                    {'label': 'LA', 'value': 'LA'},
                ],
            },
        ],
        'dashboards': [
            {
                'id': 'overview',
                'name': 'Overview',
                'layout': [
                    {'widget_id': 'dataset', 'x': 0, 'y': 0, 'w': 6, 'h': 2},
                    {'widget_id': 'chart', 'x': 6, 'y': 0, 'w': 6, 'h': 2},
                ],
                'widgets': [
                    {
                        'id': 'dataset',
                        'type': 'dataset_preview',
                        'title': 'Rows',
                        'source_tab_id': 'tab-source',
                        'config': {'page_size': 25, 'searchable': True},
                    },
                    {
                        'id': 'chart',
                        'type': 'chart',
                        'title': 'Age by city',
                        'source_tab_id': 'tab-source',
                        'config': {'chart_type': 'bar', 'x_column': 'city', 'y_column': 'age', 'aggregation': 'sum'},
                    },
                ],
            },
        ],
    }
    create = client.post('/api/v1/analysis', json=create_payload)
    analysis_id = create.json()['id']

    original = dashboard_service.compute_service.preview_step
    calls = 0

    def wrapped_preview_step(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    with patch('modules.analysis.dashboard_service.compute_service.preview_step', side_effect=wrapped_preview_step):
        response = client.post(
            f'/api/v1/analysis/{analysis_id}/dashboards/overview/run',
            json={'variable_values': {'city_filter': ['NYC', 'LA']}},
        )

    assert response.status_code == 200
    widgets = {widget['widget_id']: widget for widget in response.json()['widgets']}
    assert widgets['dataset']['status'] == 'success'
    assert widgets['chart']['status'] == 'success'
    assert calls == 1
