import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import delete, desc, select
from sqlmodel import Session

from modules.analysis.models import Analysis, AnalysisDataSource
from modules.analysis_versions.models import AnalysisVersion
from modules.datasource.models import DataSource


def create_version(session: Session, analysis: Analysis) -> AnalysisVersion:
    latest = session.execute(
        select(AnalysisVersion)
        .where(AnalysisVersion.analysis_id == analysis.id)  # type: ignore[arg-type]
        .order_by(desc(AnalysisVersion.version))  # type: ignore[arg-type]
        .limit(1)
    ).scalar_one_or_none()

    next_version = (latest.version + 1) if latest else 1
    version = AnalysisVersion(
        id=str(uuid.uuid4()),
        analysis_id=analysis.id,
        version=next_version,
        name=analysis.name,
        description=analysis.description,
        pipeline_definition=analysis.pipeline_definition,
        created_at=datetime.now(UTC),
    )

    session.add(version)
    session.commit()
    session.refresh(version)
    return version


def list_versions(session: Session, analysis_id: str) -> list[AnalysisVersion]:
    result = session.execute(
        select(AnalysisVersion)
        .where(AnalysisVersion.analysis_id == analysis_id)  # type: ignore[arg-type]
        .order_by(desc(AnalysisVersion.version))  # type: ignore[arg-type]
    )
    return cast(list[AnalysisVersion], list(result.scalars().all()))


def get_version(session: Session, analysis_id: str, version: int) -> AnalysisVersion | None:
    result = session.execute(
        select(AnalysisVersion).where(  # type: ignore[arg-type]
            AnalysisVersion.analysis_id == analysis_id,  # type: ignore[arg-type]
            AnalysisVersion.version == version,  # type: ignore[arg-type]
        )
    )
    return result.scalar_one_or_none()


def rename_version(session: Session, analysis_id: str, version: int, name: str) -> AnalysisVersion:
    target = get_version(session, analysis_id, version)
    if not target:
        raise ValueError(f'Version {version} not found for analysis {analysis_id}')
    target.name = name
    session.commit()
    session.refresh(target)
    return target


def restore_version(session: Session, analysis_id: str, version: int) -> Analysis:
    analysis = session.execute(select(Analysis).where(Analysis.id == analysis_id)).scalar_one_or_none()  # type: ignore[arg-type]
    if not analysis:
        raise ValueError(f'Analysis {analysis_id} not found')

    target = get_version(session, analysis_id, version)
    if not target:
        raise ValueError(f'Analysis version {version} not found')

    create_version(session, analysis)

    analysis.name = target.name
    analysis.description = target.description
    analysis.pipeline_definition = target.pipeline_definition
    analysis.updated_at = datetime.now(UTC)

    tabs = analysis.pipeline_definition.get('tabs', [])
    for tab in tabs:
        config = tab.get('datasource_config') or {}
        source_analysis_id = config.get('analysis_id')
        if not source_analysis_id:
            continue
        datasource_id = tab.get('datasource_id')
        if datasource_id and session.get(DataSource, datasource_id):
            continue
        datasource_id = str(uuid.uuid4())
        datasource = DataSource(
            id=datasource_id,
            name=tab.get('name') or 'Analysis Source',
            source_type='analysis',
            config={'analysis_id': str(source_analysis_id)},
            created_by_analysis_id=str(source_analysis_id),
            created_at=datetime.now(UTC),
        )
        session.add(datasource)
        tab['datasource_id'] = datasource_id

    session.execute(delete(AnalysisDataSource).where(AnalysisDataSource.analysis_id == analysis_id))  # type: ignore[arg-type]
    datasource_ids = analysis.pipeline_definition.get('datasource_ids', [])
    if tabs:
        datasource_ids = [tab.get('datasource_id') for tab in tabs if tab.get('datasource_id')]
    for datasource_id in datasource_ids:
        ds: DataSource | None = session.get(DataSource, datasource_id)
        if not ds:
            raise ValueError(f'DataSource {datasource_id} not found')
        if ds.source_type == 'analysis':
            source_id = _get_analysis_source_id(ds)
            _ensure_no_cycle(session, analysis_id, source_id)
        session.add(
            AnalysisDataSource(
                analysis_id=analysis_id,
                datasource_id=datasource_id,
            )
        )

    session.commit()
    session.refresh(analysis)

    create_version(session, analysis)

    return analysis


def _get_analysis_source_id(datasource: DataSource) -> str:
    analysis_id = datasource.config.get('analysis_id')
    if not analysis_id:
        raise ValueError(f'Analysis datasource {datasource.id} missing analysis_id')
    return str(analysis_id)


def _ensure_no_cycle(session: Session, analysis_id: str, source_analysis_id: str) -> None:
    if analysis_id == source_analysis_id:
        raise ValueError('Analysis cannot use itself as a datasource')
    if _detect_cycle(session, analysis_id, source_analysis_id):
        raise ValueError('Analysis datasource introduces a cycle')


def _detect_cycle(session: Session, analysis_id: str, source_analysis_id: str) -> bool:
    visited: set[str] = set()

    def visit(target_id: str) -> bool:
        if target_id == analysis_id:
            return True
        if target_id in visited:
            return False
        visited.add(target_id)
        links = (
            session.execute(
                select(AnalysisDataSource).where(AnalysisDataSource.analysis_id == target_id)  # type: ignore[arg-type]
            )
            .scalars()
            .all()
        )
        datasources = [session.get(DataSource, link.datasource_id) for link in links]
        for datasource in datasources:
            if not datasource:
                continue
            if datasource.source_type != 'analysis':
                continue
            next_id = datasource.config.get('analysis_id')
            if not next_id:
                continue
            if visit(str(next_id)):
                return True
        return False

    return visit(source_analysis_id)
