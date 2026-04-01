from collections import deque

from sqlalchemy import select
from sqlmodel import Session

from core.namespace import get_namespace
from modules.analysis.models import Analysis, AnalysisDataSource
from modules.datasource.models import DataSource


def build_lineage(
    session: Session,
    target_datasource_id: str | None = None,
    branch: str | None = None,
    include_internals: bool = False,
    mode: str = 'full',
) -> dict:
    datasources = session.execute(select(DataSource)).scalars().all()
    analyses = session.execute(select(Analysis)).scalars().all()
    deps = session.execute(select(AnalysisDataSource)).scalars().all()

    datasource_map = {ds.id: ds for ds in datasources}
    analysis_map = {analysis.id: analysis for analysis in analyses}

    if branch is not None:
        branch = branch.strip()
        if not branch:
            branch = None

    if target_datasource_id:
        target = datasource_map.get(target_datasource_id)
        if not target:
            return {'nodes': [], 'edges': []}
        if isinstance(target.config, dict):
            namespace_name = target.config.get('namespace_name')
            if namespace_name and namespace_name != get_namespace():
                return {'nodes': [], 'edges': []}

    ds_to_consumers: dict[str, set[str]] = {}
    for dep in deps:
        consumers = ds_to_consumers.setdefault(dep.datasource_id, set())
        consumers.add(dep.analysis_id)

    internal_ids: set[str] = set()
    for ds in datasources:
        producer = ds.created_by_analysis_id
        if not producer:
            continue
        consumers = ds_to_consumers.get(ds.id, set())
        if producer in consumers:
            internal_ids.add(ds.id)

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_keys: set[tuple[str, str, str]] = set()

    def datasource_key(datasource_id: str) -> str:
        return f'datasource:{datasource_id}'

    def analysis_key(analysis_id: str) -> str:
        return f'analysis:{analysis_id}'

    def classify_datasource(ds: DataSource) -> str:
        if ds.id in internal_ids:
            return 'internal'
        if ds.created_by_analysis_id:
            return 'output'
        return 'source'

    def datasource_branch(ds: DataSource) -> str | None:
        if target_datasource_id and ds.id == target_datasource_id and branch is not None:
            return branch
        if not isinstance(ds.config, dict):
            return None
        value = ds.config.get('branch')
        if value is None:
            return None
        return str(value)

    def add_datasource_node(ds: DataSource) -> str:
        node_id = datasource_key(ds.id)
        if node_id in nodes:
            return node_id
        node_branch = datasource_branch(ds)
        nodes[node_id] = {
            'id': node_id,
            'type': 'datasource',
            'node_kind': classify_datasource(ds),
            'name': ds.name,
            'source_type': ds.source_type,
            'branch': node_branch,
        }
        return node_id

    def add_analysis_node(analysis: Analysis) -> str:
        node_id = analysis_key(analysis.id)
        if node_id in nodes:
            return node_id
        nodes[node_id] = {
            'id': node_id,
            'type': 'analysis',
            'node_kind': 'analysis',
            'name': analysis.name,
            'status': analysis.status,
        }
        return node_id

    def add_edge(from_id: str, to_id: str, edge_type: str) -> None:
        key = (from_id, to_id, edge_type)
        if key in edge_keys:
            return
        edge_keys.add(key)
        edges.append({'from': from_id, 'to': to_id, 'type': edge_type})

    for ds in datasources:
        ds_node_id = add_datasource_node(ds)
        producer_id = ds.created_by_analysis_id
        if not producer_id:
            continue
        analysis = analysis_map.get(producer_id)
        if not analysis:
            continue
        analysis_node_id = add_analysis_node(analysis)
        edge_type = 'chains' if ds.id in internal_ids else 'produces'
        add_edge(analysis_node_id, ds_node_id, edge_type)

    for analysis in analyses:
        add_analysis_node(analysis)

    for dep in deps:
        datasource = datasource_map.get(dep.datasource_id)
        analysis = analysis_map.get(dep.analysis_id)
        if not datasource or not analysis:
            continue
        ds_node_id = add_datasource_node(datasource)
        analysis_node_id = add_analysis_node(analysis)
        producer_id = datasource.created_by_analysis_id
        same_analysis_internal = datasource.id in internal_ids and producer_id == analysis.id
        edge_type = 'consumes_internal' if same_analysis_internal else 'uses'
        add_edge(ds_node_id, analysis_node_id, edge_type)

    if mode in {'upstream', 'downstream'} and target_datasource_id:
        target_node_id = datasource_key(target_datasource_id)
        if target_node_id not in nodes:
            return {'nodes': [], 'edges': []}

        include_internal_edges = include_internals
        lineage_types = {'uses', 'produces'}
        if include_internal_edges:
            lineage_types.update({'chains', 'consumes_internal'})

        forward_adj: dict[str, set[str]] = {}
        reverse_adj: dict[str, set[str]] = {}
        for edge in edges:
            edge_type = edge['type']
            if edge_type not in lineage_types:
                continue
            source = edge['from']
            target = edge['to']
            forward_adj.setdefault(source, set()).add(target)
            reverse_adj.setdefault(target, set()).add(source)

        reachable: set[str] = {target_node_id}
        queue: deque[str] = deque([target_node_id])

        while queue:
            current = queue.popleft()
            neighbors = reverse_adj.get(current, set()) if mode == 'upstream' else forward_adj.get(current, set())
            for node_id in neighbors:
                if node_id in reachable:
                    continue
                reachable.add(node_id)
                queue.append(node_id)

        nodes = {node_id: node for node_id, node in nodes.items() if node_id in reachable}
        edges = [edge for edge in edges if edge['from'] in reachable and edge['to'] in reachable]

    if not include_internals:
        internal_node_ids = {node_id for node_id, node in nodes.items() if node.get('node_kind') == 'internal'}
        nodes = {node_id: node for node_id, node in nodes.items() if node_id not in internal_node_ids}
        edges = [
            edge
            for edge in edges
            if edge['type'] not in {'chains', 'consumes_internal'}
            and edge['from'] not in internal_node_ids
            and edge['to'] not in internal_node_ids
        ]

    return {'nodes': list(nodes.values()), 'edges': edges}
