from sqlalchemy import desc, select
from sqlmodel import Session

from core.namespace import get_namespace
from modules.analysis.models import Analysis, AnalysisDataSource
from modules.datasource.models import DataSource
from modules.engine_runs.models import EngineRun


def build_lineage(session: Session, target_datasource_id: str | None = None, branch: str | None = None) -> dict:
    datasources = session.execute(select(DataSource)).scalars().all()
    analyses = session.execute(select(Analysis)).scalars().all()

    datasource_map = {ds.id: ds for ds in datasources}
    analysis_map = {analysis.id: analysis for analysis in analyses}

    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def datasource_key(datasource_id: str, branch_name: str | None) -> str:
        if not branch_name:
            return f'datasource:{datasource_id}'
        return f'datasource:{datasource_id}:{branch_name}'

    def add_datasource_node(ds: DataSource, branch_name: str | None = None):
        node_id = datasource_key(ds.id, branch_name)
        if node_id not in nodes:
            name = ds.name
            if branch_name:
                name = f'{name} ({branch_name})'
            nodes[node_id] = {
                'id': node_id,
                'type': 'datasource',
                'name': name,
                'source_type': ds.source_type,
                'branch': branch_name,
            }
        if ds.created_by_analysis_id:
            edges.append(
                {
                    'from': f'analysis:{ds.created_by_analysis_id}',
                    'to': node_id,
                    'type': 'derived',
                }
            )

    def add_analysis_node(analysis: Analysis):
        node_id = f'analysis:{analysis.id}'
        if node_id in nodes:
            return
        nodes[node_id] = {
            'id': node_id,
            'type': 'analysis',
            'name': analysis.name,
            'status': analysis.status,
        }

    def add_dependency_edges(
        analysis_id: str,
        datasource_overrides: dict[str, str | None] | None = None,
        datasource_filter: set[str] | None = None,
    ):
        deps = (
            session.execute(
                select(AnalysisDataSource).where(AnalysisDataSource.analysis_id == analysis_id)  # type: ignore[arg-type]
            )
            .scalars()
            .all()
        )
        for dep in deps:
            if datasource_filter is not None and dep.datasource_id not in datasource_filter:
                continue
            branch_name = None
            if datasource_overrides:
                branch_name = datasource_overrides.get(dep.datasource_id)
            edges.append(
                {
                    'from': datasource_key(dep.datasource_id, branch_name),
                    'to': f'analysis:{analysis_id}',
                    'type': 'uses',
                }
            )

    if not target_datasource_id:
        for ds in datasources:
            add_datasource_node(ds)
        for analysis in analyses:
            add_analysis_node(analysis)
            add_dependency_edges(analysis.id)
        return {'nodes': list(nodes.values()), 'edges': edges}

    if branch is not None:
        branch = str(branch).strip()
        if not branch:
            branch = None

    target_ds = datasource_map.get(target_datasource_id)
    if not target_ds:
        return {'nodes': [], 'edges': []}
    if isinstance(target_ds.config, dict):
        namespace_name = target_ds.config.get('namespace_name')
        if namespace_name and namespace_name != get_namespace():
            return {'nodes': [], 'edges': []}
    target_config = target_ds.config if isinstance(target_ds.config, dict) else {}
    branch_value = branch or (target_config.get('branch') if isinstance(target_config, dict) else None)
    if branch_value is not None:
        branch_value = str(branch_value)
    add_datasource_node(target_ds, branch_value)

    analysis_id = target_ds.created_by_analysis_id
    if not analysis_id:
        return {'nodes': list(nodes.values()), 'edges': edges}
    analysis = analysis_map.get(analysis_id)
    if not analysis:
        return {'nodes': list(nodes.values()), 'edges': edges}

    add_analysis_node(analysis)

    pipeline = None
    tab_override = None
    run_branch = branch_value
    stmt = (
        select(EngineRun)
        .where(EngineRun.datasource_id == target_datasource_id)  # type: ignore[arg-type]
        .where(EngineRun.kind.in_(['datasource_update', 'datasource_create']))  # type: ignore[arg-type, attr-defined]
        .where(EngineRun.status == 'success')  # type: ignore[arg-type]
        .order_by(desc(EngineRun.created_at))  # type: ignore[arg-type]
        .limit(50)
    )
    runs = session.execute(stmt).scalars().all()
    for run in runs:
        payload = run.request_json if isinstance(run.request_json, dict) else {}
        opts = payload.get('iceberg_options') if isinstance(payload, dict) else None
        branch_name = None
        if isinstance(opts, dict):
            branch_name = opts.get('branch')
        if run_branch and branch_name != run_branch:
            continue
        pipeline_value = payload.get('analysis_pipeline') if isinstance(payload, dict) else None
        if isinstance(pipeline_value, dict):
            pipeline = pipeline_value
            tab_override = payload.get('tab_id') if isinstance(payload, dict) else None
        break

    pipeline = pipeline or (analysis.pipeline_definition if isinstance(analysis.pipeline_definition, dict) else {})
    tabs = pipeline.get('tabs', []) if isinstance(pipeline, dict) else []
    sources = pipeline.get('sources') if isinstance(pipeline, dict) else None
    if not isinstance(sources, dict):
        sources = {}

    target_tab_id = str(tab_override) if tab_override else None
    if not target_tab_id:
        for tab in tabs:
            output = tab.get('output') if isinstance(tab, dict) else None
            output_id = output.get('output_datasource_id') if isinstance(output, dict) else None
            if output_id == target_datasource_id:
                target_tab_id = str(tab.get('id')) if tab.get('id') else None
                break
    if not target_tab_id:
        add_dependency_edges(analysis.id)
        return {'nodes': list(nodes.values()), 'edges': edges}

    output_map: dict[str, str] = {}
    output_to_tab: dict[str, str] = {}
    for tab in tabs:
        tab_id = tab.get('id')
        output = tab.get('output') if isinstance(tab, dict) else None
        output_id = output.get('output_datasource_id') if isinstance(output, dict) else None
        if tab_id and output_id:
            output_map[str(tab_id)] = str(output_id)
            output_to_tab[str(output_id)] = str(tab_id)
    tab_map = {tab.get('id'): tab for tab in tabs if tab.get('id')}

    ordered: list[dict] = []
    seen: set[str] = set()
    current_id = str(target_tab_id)
    while current_id:
        if current_id in seen:
            break
        seen.add(current_id)
        current_tab = tab_map.get(current_id)
        if not current_tab:
            break
        ordered.append(current_tab)
        datasource = current_tab.get('datasource') if isinstance(current_tab, dict) else None
        input_id = datasource.get('id') if isinstance(datasource, dict) else None
        upstream_tab_id = None
        if input_id:
            upstream_tab_id = output_to_tab.get(str(input_id))
        if upstream_tab_id:
            current_id = str(upstream_tab_id)
            continue
        break
    ordered.reverse()

    branch_overrides: dict[str, str | None] = {}
    input_ids: set[str] = set()
    for tab in ordered:
        datasource = tab.get('datasource') if isinstance(tab, dict) else None
        input_id = datasource.get('id') if isinstance(datasource, dict) else None
        if not input_id:
            continue
        tab_config = datasource.get('config') if isinstance(datasource, dict) else {}
        output_branch = None
        output_config = tab.get('output') if isinstance(tab.get('output'), dict) else None
        if isinstance(output_config, dict):
            iceberg_cfg = output_config.get('iceberg')
            if isinstance(iceberg_cfg, dict):
                output_branch = iceberg_cfg.get('branch') or run_branch
        output = tab.get('output') if isinstance(tab, dict) else None
        output_id = output.get('output_datasource_id') if isinstance(output, dict) else None
        if output_id:
            branch_value = str(output_branch) if output_branch is not None else None
            branch_overrides[str(output_id)] = branch_value
        base_config = sources.get(str(input_id)) if isinstance(sources, dict) else None
        if not isinstance(base_config, dict):
            base_config = {}
        merged = {**base_config, **(tab_config if isinstance(tab_config, dict) else {})}
        branch_name = merged.get('branch') if isinstance(merged, dict) else None
        if branch_name is not None:
            branch_name = str(branch_name)
        branch_overrides[str(input_id)] = branch_name
        input_ids.add(str(input_id))
        source = datasource_map.get(str(input_id))
        if source:
            add_datasource_node(source, branch_name)

    add_dependency_edges(analysis.id, datasource_overrides=branch_overrides, datasource_filter=input_ids)

    return {'nodes': list(nodes.values()), 'edges': edges}
