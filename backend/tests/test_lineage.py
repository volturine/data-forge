from datetime import UTC, datetime

from modules.analysis.models import Analysis, AnalysisDataSource
from modules.datasource.models import DataSource


def _create_analysis(analysis_id: str, name: str) -> Analysis:
    now = datetime.now(UTC)
    return Analysis(
        id=analysis_id,
        name=name,
        description=None,
        pipeline_definition={'steps': [], 'tabs': []},
        status='draft',
        created_at=now,
        updated_at=now,
    )


def _create_datasource(
    datasource_id: str,
    name: str,
    source_type: str,
    created_by_analysis_id: str | None = None,
) -> DataSource:
    return DataSource(
        id=datasource_id,
        name=name,
        source_type=source_type,
        config={'branch': 'main'},
        created_at=datetime.now(UTC),
        created_by_analysis_id=created_by_analysis_id,
    )


def _seed_rich_lineage_graph(test_db_session):
    ds_source_a = _create_datasource('ds_source_a', 'Source A', 'file')
    ds_source_b = _create_datasource('ds_source_b', 'Source B', 'file')

    analysis_1 = _create_analysis('analysis_1', 'Analysis 1')
    ds_intermediate = _create_datasource(
        'ds_intermediate',
        'Intermediate',
        'iceberg',
        created_by_analysis_id=analysis_1.id,
    )
    ds_output_1 = _create_datasource(
        'ds_output_1',
        'Output 1',
        'iceberg',
        created_by_analysis_id=analysis_1.id,
    )

    analysis_2 = _create_analysis('analysis_2', 'Analysis 2')
    ds_output_2 = _create_datasource(
        'ds_output_2',
        'Output 2',
        'iceberg',
        created_by_analysis_id=analysis_2.id,
    )

    test_db_session.add(ds_source_a)
    test_db_session.add(ds_source_b)
    test_db_session.add(analysis_1)
    test_db_session.add(ds_intermediate)
    test_db_session.add(ds_output_1)
    test_db_session.add(analysis_2)
    test_db_session.add(ds_output_2)

    test_db_session.add(AnalysisDataSource(analysis_id=analysis_1.id, datasource_id=ds_source_a.id))
    test_db_session.add(AnalysisDataSource(analysis_id=analysis_1.id, datasource_id=ds_intermediate.id))
    test_db_session.add(AnalysisDataSource(analysis_id=analysis_2.id, datasource_id=ds_output_1.id))
    test_db_session.add(AnalysisDataSource(analysis_id=analysis_2.id, datasource_id=ds_source_b.id))

    test_db_session.commit()

    return {
        'ds_source_a': ds_source_a.id,
        'ds_source_b': ds_source_b.id,
        'analysis_1': analysis_1.id,
        'ds_intermediate': ds_intermediate.id,
        'ds_output_1': ds_output_1.id,
        'analysis_2': analysis_2.id,
        'ds_output_2': ds_output_2.id,
    }


def _get_lineage(client, **params):
    response = client.get('/api/v1/datasource/lineage', params=params)
    assert response.status_code == 200
    return response.json()


def test_lineage_node_classification(test_db_session, client):
    ids = _seed_rich_lineage_graph(test_db_session)

    payload = _get_lineage(client, include_internals=True, mode='full')
    nodes = {node['id']: node for node in payload['nodes']}

    assert nodes[f'datasource:{ids["ds_source_a"]}']['node_kind'] == 'source'
    assert nodes[f'datasource:{ids["ds_source_b"]}']['node_kind'] == 'source'
    assert nodes[f'datasource:{ids["ds_output_1"]}']['node_kind'] == 'output'
    assert nodes[f'datasource:{ids["ds_output_2"]}']['node_kind'] == 'output'
    assert nodes[f'datasource:{ids["ds_intermediate"]}']['node_kind'] == 'internal'


def test_lineage_hides_internals_by_default(test_db_session, client):
    ids = _seed_rich_lineage_graph(test_db_session)

    payload = _get_lineage(client)
    node_ids = {node['id'] for node in payload['nodes']}
    edge_types = {edge['type'] for edge in payload['edges']}

    assert f'datasource:{ids["ds_intermediate"]}' not in node_ids
    assert 'chains' not in edge_types
    assert 'consumes_internal' not in edge_types


def test_lineage_shows_internals_when_requested(test_db_session, client):
    ids = _seed_rich_lineage_graph(test_db_session)

    payload = _get_lineage(client, include_internals=True)
    node_ids = {node['id'] for node in payload['nodes']}
    edge_types = {edge['type'] for edge in payload['edges']}

    assert f'datasource:{ids["ds_intermediate"]}' in node_ids
    assert 'chains' in edge_types
    assert 'consumes_internal' in edge_types


def test_lineage_edge_types(test_db_session, client):
    ids = _seed_rich_lineage_graph(test_db_session)

    payload = _get_lineage(client, include_internals=True)
    edges = {(edge['from'], edge['to'], edge['type']) for edge in payload['edges']}

    assert (
        f'datasource:{ids["ds_source_a"]}',
        f'analysis:{ids["analysis_1"]}',
        'uses',
    ) in edges
    assert (
        f'analysis:{ids["analysis_1"]}',
        f'datasource:{ids["ds_output_1"]}',
        'produces',
    ) in edges
    assert (
        f'analysis:{ids["analysis_1"]}',
        f'datasource:{ids["ds_intermediate"]}',
        'chains',
    ) in edges
    assert (
        f'datasource:{ids["ds_intermediate"]}',
        f'analysis:{ids["analysis_1"]}',
        'consumes_internal',
    ) in edges


def test_lineage_upstream_mode(test_db_session, client):
    ids = _seed_rich_lineage_graph(test_db_session)

    payload = _get_lineage(client, target_datasource_id=ids['ds_output_2'], mode='upstream')
    node_ids = {node['id'] for node in payload['nodes']}

    assert f'analysis:{ids["analysis_2"]}' in node_ids
    assert f'datasource:{ids["ds_output_1"]}' in node_ids
    assert f'analysis:{ids["analysis_1"]}' in node_ids
    assert f'datasource:{ids["ds_source_a"]}' in node_ids
    assert f'datasource:{ids["ds_source_b"]}' in node_ids
    assert f'datasource:{ids["ds_output_2"]}' in node_ids
    assert f'datasource:{ids["ds_intermediate"]}' not in node_ids


def test_lineage_downstream_mode(test_db_session, client):
    ids = _seed_rich_lineage_graph(test_db_session)

    payload = _get_lineage(client, target_datasource_id=ids['ds_source_a'], mode='downstream')
    node_ids = {node['id'] for node in payload['nodes']}

    assert f'analysis:{ids["analysis_1"]}' in node_ids
    assert f'datasource:{ids["ds_output_1"]}' in node_ids
    assert f'analysis:{ids["analysis_2"]}' in node_ids
    assert f'datasource:{ids["ds_output_2"]}' in node_ids
    assert f'datasource:{ids["ds_source_b"]}' not in node_ids


def test_lineage_empty_graph(client):
    payload = _get_lineage(client)

    assert payload == {'nodes': [], 'edges': []}


def test_lineage_target_not_found(client):
    payload = _get_lineage(client, target_datasource_id='missing-datasource-id', mode='upstream')

    assert payload == {'nodes': [], 'edges': []}


def test_existing_basic_lineage(test_db_session, client):
    datasource_id = 'ds-lineage-1'
    analysis_id = 'analysis-lineage-1'

    datasource = _create_datasource(datasource_id, 'Source A', 'file')
    analysis = _create_analysis(analysis_id, 'Analysis A')

    test_db_session.add(datasource)
    test_db_session.add(analysis)
    test_db_session.add(AnalysisDataSource(analysis_id=analysis_id, datasource_id=datasource_id))
    test_db_session.commit()

    payload = _get_lineage(client)

    node_ids = {node['id'] for node in payload['nodes']}
    edges = {(edge['from'], edge['to'], edge['type']) for edge in payload['edges']}

    assert f'datasource:{datasource_id}' in node_ids
    assert f'analysis:{analysis_id}' in node_ids
    assert (f'datasource:{datasource_id}', f'analysis:{analysis_id}', 'uses') in edges
