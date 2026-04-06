from modules.compute.engine import PolarsComputeEngine


def test_query_plan_merges_eager_segments(test_db_session, tmp_path):
    csv_path = tmp_path / 'plan.csv'
    csv_path.write_text('name,age\nAlice,30\nBob,40\n')
    datasource_config = {'source_type': 'file', 'file_path': str(csv_path), 'file_type': 'csv', 'options': {}}
    steps = [
        {
            'id': 's1',
            'type': 'filter',
            'config': {'conditions': [{'column': 'name', 'operator': 'contains', 'value': 'A', 'value_type': 'string'}], 'logic': 'AND'},
            'depends_on': [],
        },
        {
            'id': 's2',
            'type': 'notification',
            'config': {
                'method': 'email',
                'recipient': 'test@example.com',
                'subscriber_ids': [],
                'bot_token': '',
                'input_columns': ['name'],
                'output_column': 'notification_status',
                'message_template': '{{name}}',
                'subject_template': 'Notification',
                'batch_size': 10,
                'timeout_seconds': 1,
            },
            'depends_on': ['s1'],
        },
        {'id': 's3', 'type': 'select', 'config': {'columns': ['name']}, 'depends_on': ['s2']},
    ]

    result = PolarsComputeEngine._execute_preview(
        datasource_config=datasource_config,
        steps=steps,
        row_limit=10,
        offset=0,
        job_id='job-plan',
        additional_datasources=None,
    )

    plans = result['query_plans']
    assert plans is not None
    assert '-- EAGER STEP (notification) / MATERIALIZE --' not in plans['optimized']
    assert 'query plan includes lazy segments only' not in plans['optimized'].lower()
    assert result['query_plan']


def test_chart_preview_metadata_includes_overlays_and_reference_lines(test_db_session, tmp_path):
    csv_path = tmp_path / 'chart.csv'
    csv_path.write_text('category,value,value2\nA,1,10\nB,2,20\n')
    datasource_config = {'source_type': 'file', 'file_path': str(csv_path), 'file_type': 'csv', 'options': {}}
    steps = [
        {
            'id': 's1',
            'type': 'chart',
            'config': {
                'chart_type': 'bar',
                'x_column': 'category',
                'y_column': 'value',
                'aggregation': 'sum',
                'overlays': [
                    {
                        'chart_type': 'line',
                        'y_column': 'value2',
                        'aggregation': 'sum',
                        'y_axis_position': 'right',
                    },
                ],
                'reference_lines': [{'axis': 'y', 'value': 5.0, 'label': 'target', 'color': '#ff0000'}],
            },
            'depends_on': [],
        },
    ]

    result = PolarsComputeEngine._execute_preview(
        datasource_config=datasource_config,
        steps=steps,
        row_limit=10,
        offset=0,
        job_id='job-chart',
        additional_datasources=None,
    )

    metadata = result.get('metadata')
    assert isinstance(metadata, dict)
    assert isinstance(metadata.get('overlays'), list)
    assert isinstance(metadata.get('reference_lines'), list)
    assert metadata['overlays'][0]['y_column'] == 'value2'
    assert metadata['reference_lines'][0]['label'] == 'target'
