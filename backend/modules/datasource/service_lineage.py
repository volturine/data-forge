from sqlalchemy import select
from sqlmodel import Session

from modules.analysis.models import Analysis, AnalysisDataSource
from modules.datasource.models import DataSource


def build_lineage(session: Session) -> dict:
    datasources = session.execute(select(DataSource)).scalars().all()
    analyses = session.execute(select(Analysis)).scalars().all()

    nodes: list[dict] = []
    edges: list[dict] = []

    for ds in datasources:
        node_id = f'datasource:{ds.id}'
        nodes.append(
            {
                'id': node_id,
                'type': 'datasource',
                'name': ds.name,
                'source_type': ds.source_type,
            }
        )
        if ds.created_by_analysis_id:
            edges.append(
                {
                    'from': f'analysis:{ds.created_by_analysis_id}',
                    'to': node_id,
                    'type': 'derived',
                }
            )

    for analysis in analyses:
        node_id = f'analysis:{analysis.id}'
        nodes.append(
            {
                'id': node_id,
                'type': 'analysis',
                'name': analysis.name,
                'status': analysis.status,
            }
        )
        deps = (
            session.execute(
                select(AnalysisDataSource).where(AnalysisDataSource.analysis_id == analysis.id)  # type: ignore[arg-type]
            )
            .scalars()
            .all()
        )
        for dep in deps:
            edges.append(
                {
                    'from': f'datasource:{dep.datasource_id}',
                    'to': node_id,
                    'type': 'uses',
                }
            )

    return {'nodes': nodes, 'edges': edges}
