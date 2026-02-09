import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, delete, select
from sqlmodel import Session

from modules.analysis.models import Analysis, AnalysisDataSource
from modules.analysis.schemas import (
    AnalysisCreateSchema,
    AnalysisGalleryItemSchema,
    AnalysisResponseSchema,
    AnalysisUpdateSchema,
    TabSchema,
)
from modules.datasource.models import DataSource
from modules.locks import service as lock_service


def create_analysis(
    session: Session,  # type: ignore[type-arg]
    data: AnalysisCreateSchema,
) -> AnalysisResponseSchema:
    analysis_id = str(uuid.uuid4())

    for datasource_id in data.datasource_ids:
        result = session.execute(select(DataSource).where(DataSource.id == datasource_id))  # type: ignore[arg-type]
        datasource = result.scalar_one_or_none()
        if not datasource:
            raise ValueError(f'DataSource {datasource_id} not found')

    pipeline_definition = {
        'steps': [step.model_dump() for step in data.pipeline_steps],
        'datasource_ids': data.datasource_ids,
        'tabs': [tab.model_dump() for tab in data.tabs],
    }

    now = datetime.now(UTC)
    analysis = Analysis(
        id=analysis_id,
        name=data.name,
        description=data.description,
        pipeline_definition=pipeline_definition,
        status='draft',
        created_at=now,
        updated_at=now,
    )

    session.add(analysis)

    for datasource_id in data.datasource_ids:
        link = AnalysisDataSource(
            analysis_id=analysis_id,
            datasource_id=datasource_id,
        )
        session.add(link)

    session.commit()
    session.refresh(analysis)

    response = AnalysisResponseSchema.model_validate(analysis)
    response.tabs = [TabSchema.model_validate(tab) for tab in analysis.pipeline_definition.get('tabs', [])]
    return response


def get_analysis(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
) -> AnalysisResponseSchema:
    result = session.execute(select(Analysis).where(Analysis.id == analysis_id))  # type: ignore[arg-type]
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise ValueError(f'Analysis {analysis_id} not found')

    response = AnalysisResponseSchema.model_validate(analysis)
    response.tabs = [TabSchema.model_validate(tab) for tab in analysis.pipeline_definition.get('tabs', [])]
    return response


def list_analyses(
    session: Session,  # type: ignore[type-arg]
) -> list[AnalysisGalleryItemSchema]:
    result = session.execute(select(Analysis))
    analyses = result.scalars().all()

    return [AnalysisGalleryItemSchema.model_validate(a) for a in analyses]


def update_analysis(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    data: AnalysisUpdateSchema,
) -> AnalysisResponseSchema:
    result = session.execute(select(Analysis).where(Analysis.id == analysis_id))  # type: ignore[arg-type]
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise ValueError(f'Analysis {analysis_id} not found')

    if data.name is not None:
        analysis.name = data.name

    if data.description is not None:
        analysis.description = data.description

    if data.pipeline_steps is not None or data.tabs is not None:
        pipeline_definition = {
            'steps': (
                [step.model_dump() for step in data.pipeline_steps]
                if data.pipeline_steps is not None
                else analysis.pipeline_definition.get('steps', [])
            ),
            'datasource_ids': analysis.pipeline_definition.get('datasource_ids', []),
            'tabs': ([tab.model_dump() for tab in data.tabs] if data.tabs is not None else analysis.pipeline_definition.get('tabs', [])),
        }
        analysis.pipeline_definition = pipeline_definition

    if data.status is not None:
        analysis.status = data.status

    analysis.updated_at = datetime.now(UTC)

    session.commit()
    session.refresh(analysis)

    response = AnalysisResponseSchema.model_validate(analysis)
    response.tabs = [TabSchema.model_validate(tab) for tab in analysis.pipeline_definition.get('tabs', [])]
    return response


def delete_analysis(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
) -> None:
    result = session.execute(select(Analysis).where(Analysis.id == analysis_id))  # type: ignore[arg-type]
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise ValueError(f'Analysis {analysis_id} not found')

    session.execute(delete(AnalysisDataSource).where(AnalysisDataSource.analysis_id == analysis_id))  # type: ignore[arg-type]

    session.delete(analysis)
    session.commit()

    lock_service.clear_lock(session, analysis_id)


def link_datasource(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    datasource_id: str,
) -> None:
    result = session.execute(select(Analysis).where(Analysis.id == analysis_id))  # type: ignore[arg-type]
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise ValueError(f'Analysis {analysis_id} not found')

    result = session.execute(select(DataSource).where(DataSource.id == datasource_id))  # type: ignore[arg-type]
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise ValueError(f'DataSource {datasource_id} not found')

    result = session.execute(
        select(AnalysisDataSource).where(
            and_(
                AnalysisDataSource.analysis_id == analysis_id,  # type: ignore[arg-type]
                AnalysisDataSource.datasource_id == datasource_id,  # type: ignore[arg-type]
            )
        )
    )  # type: ignore[arg-type]
    existing = result.scalar_one_or_none()
    if existing:
        return

    link = AnalysisDataSource(
        analysis_id=analysis_id,
        datasource_id=datasource_id,
    )
    session.add(link)

    if datasource_id not in analysis.pipeline_definition.get('datasource_ids', []):
        analysis.pipeline_definition['datasource_ids'] = analysis.pipeline_definition.get('datasource_ids', []) + [datasource_id]
        analysis.updated_at = datetime.now(UTC)

    tabs = analysis.pipeline_definition.get('tabs', [])
    if not any(tab.get('datasource_id') == datasource_id for tab in tabs):
        tabs.append(
            {
                'id': f'tab-{datasource_id}',
                'name': f'Source {len(tabs) + 1}',
                'type': 'datasource',
                'parent_id': None,
                'datasource_id': datasource_id,
                'steps': [],
            }
        )
        analysis.pipeline_definition['tabs'] = tabs
        analysis.updated_at = datetime.now(UTC)

    session.commit()


def unlink_datasource(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    datasource_id: str,
) -> None:
    result = session.execute(select(Analysis).where(Analysis.id == analysis_id))  # type: ignore[arg-type]
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise ValueError(f'Analysis {analysis_id} not found')

    result = session.execute(select(DataSource).where(DataSource.id == datasource_id))  # type: ignore[arg-type]
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise ValueError(f'DataSource {datasource_id} not found')

    session.execute(
        delete(AnalysisDataSource).where(
            and_(
                AnalysisDataSource.analysis_id == analysis_id,  # type: ignore[arg-type]
                AnalysisDataSource.datasource_id == datasource_id,  # type: ignore[arg-type]
            )
        )
    )  # type: ignore[arg-type]

    datasource_ids = analysis.pipeline_definition.get('datasource_ids', [])
    if datasource_id in datasource_ids:
        datasource_ids.remove(datasource_id)
        analysis.pipeline_definition['datasource_ids'] = datasource_ids
        analysis.updated_at = datetime.now(UTC)

    tabs = analysis.pipeline_definition.get('tabs', [])
    next_tabs = [tab for tab in tabs if tab.get('datasource_id') != datasource_id]
    if len(next_tabs) != len(tabs):
        analysis.pipeline_definition['tabs'] = next_tabs
        analysis.updated_at = datetime.now(UTC)

    session.commit()
