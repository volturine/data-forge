import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.analysis.models import Analysis, AnalysisDataSource
from modules.analysis.schemas import (
    AnalysisCreateSchema,
    AnalysisGalleryItemSchema,
    AnalysisResponseSchema,
    AnalysisUpdateSchema,
    TabSchema,
)
from modules.datasource.models import DataSource


async def create_analysis(
    session: AsyncSession,
    data: AnalysisCreateSchema,
) -> AnalysisResponseSchema:
    analysis_id = str(uuid.uuid4())

    for datasource_id in data.datasource_ids:
        result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
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

    await session.commit()
    await session.refresh(analysis)

    response = AnalysisResponseSchema.model_validate(analysis)
    response.tabs = [TabSchema.model_validate(tab) for tab in analysis.pipeline_definition.get('tabs', [])]
    return response


async def get_analysis(
    session: AsyncSession,
    analysis_id: str,
) -> AnalysisResponseSchema:
    result = await session.execute(select(Analysis).where(Analysis.id == analysis_id))
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise ValueError(f'Analysis {analysis_id} not found')

    response = AnalysisResponseSchema.model_validate(analysis)
    response.tabs = [TabSchema.model_validate(tab) for tab in analysis.pipeline_definition.get('tabs', [])]
    return response


async def list_analyses(
    session: AsyncSession,
) -> list[AnalysisGalleryItemSchema]:
    result = await session.execute(select(Analysis))
    analyses = result.scalars().all()

    return [AnalysisGalleryItemSchema.model_validate(a) for a in analyses]


async def update_analysis(
    session: AsyncSession,
    analysis_id: str,
    data: AnalysisUpdateSchema,
) -> AnalysisResponseSchema:
    result = await session.execute(select(Analysis).where(Analysis.id == analysis_id))
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

    await session.commit()
    await session.refresh(analysis)

    response = AnalysisResponseSchema.model_validate(analysis)
    response.tabs = [TabSchema.model_validate(tab) for tab in analysis.pipeline_definition.get('tabs', [])]
    return response


async def delete_analysis(
    session: AsyncSession,
    analysis_id: str,
) -> None:
    result = await session.execute(select(Analysis).where(Analysis.id == analysis_id))
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise ValueError(f'Analysis {analysis_id} not found')

    await session.execute(delete(AnalysisDataSource).where(AnalysisDataSource.analysis_id == analysis_id))

    await session.delete(analysis)
    await session.commit()


async def link_datasource(
    session: AsyncSession,
    analysis_id: str,
    datasource_id: str,
) -> None:
    result = await session.execute(select(Analysis).where(Analysis.id == analysis_id))
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise ValueError(f'Analysis {analysis_id} not found')

    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise ValueError(f'DataSource {datasource_id} not found')

    result = await session.execute(
        select(AnalysisDataSource).where(
            AnalysisDataSource.analysis_id == analysis_id,
            AnalysisDataSource.datasource_id == datasource_id,
        )
    )
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

    await session.commit()


async def unlink_datasource(
    session: AsyncSession,
    analysis_id: str,
    datasource_id: str,
) -> None:
    result = await session.execute(select(Analysis).where(Analysis.id == analysis_id))
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise ValueError(f'Analysis {analysis_id} not found')

    result = await session.execute(select(DataSource).where(DataSource.id == datasource_id))
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise ValueError(f'DataSource {datasource_id} not found')

    await session.execute(
        delete(AnalysisDataSource).where(
            AnalysisDataSource.analysis_id == analysis_id,
            AnalysisDataSource.datasource_id == datasource_id,
        )
    )

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

    await session.commit()
