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
