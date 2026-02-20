from datetime import UTC, datetime

from modules.analysis.models import Analysis, AnalysisDataSource
from modules.datasource.models import DataSource


def test_lineage_returns_nodes_and_edges(test_db_session, client):
    datasource_id = 'ds-lineage-1'
    analysis_id = 'analysis-lineage-1'
    datasource = DataSource(
        id=datasource_id,
        name='Source A',
        source_type='file',
        config={'file_path': '/tmp/file.csv', 'file_type': 'csv', 'options': {}},
        created_at=datetime.now(UTC),
    )
    analysis = Analysis(
        id=analysis_id,
        name='Analysis A',
        description=None,
        pipeline_definition={'steps': [], 'datasource_ids': [datasource_id], 'tabs': []},
        status='draft',
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    test_db_session.add(datasource)
    test_db_session.add(analysis)
    test_db_session.add(AnalysisDataSource(analysis_id=analysis_id, datasource_id=datasource_id))
    test_db_session.commit()

    response = client.get('/api/v1/datasource/lineage')

    assert response.status_code == 200
    payload = response.json()
    assert 'nodes' in payload
    assert 'edges' in payload
    node_ids = {node['id'] for node in payload['nodes']}
    assert f'datasource:{datasource_id}' in node_ids
    assert f'analysis:{analysis_id}' in node_ids
    assert any(edge['to'] == f'analysis:{analysis_id}' for edge in payload['edges'])


def test_lineage_filters_by_output_branch(test_db_session, client):
    datasource_id = 'ds-lineage-output'
    analysis_id = 'analysis-lineage-output'
    datasource = DataSource(
        id=datasource_id,
        name='Output A',
        source_type='iceberg',
        config={'branch': 'dev', 'metadata_path': '/tmp/output'},
        created_by_analysis_id=analysis_id,
        created_by='analysis',
        created_at=datetime.now(UTC),
    )
    analysis = Analysis(
        id=analysis_id,
        name='Analysis A',
        description=None,
        pipeline_definition={
            'steps': [],
            'datasource_ids': [],
            'tabs': [
                {
                    'id': 'tab-1',
                    'name': 'Tab 1',
                    'datasource_id': None,
                    'output_datasource_id': datasource_id,
                    'datasource_config': {
                        'output': {
                            'iceberg': {
                                'table_name': 'tab_1',
                                'namespace': 'outputs',
                                'branch': 'dev',
                            }
                        }
                    },
                    'steps': [],
                }
            ],
        },
        status='draft',
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    test_db_session.add(datasource)
    test_db_session.add(analysis)
    test_db_session.commit()

    response = client.get('/api/v1/datasource/lineage', params={'target_datasource_id': datasource_id, 'branch': 'dev'})

    assert response.status_code == 200
    payload = response.json()
    node_ids = {node['id'] for node in payload['nodes']}
    assert f'datasource:{datasource_id}:dev' in node_ids
