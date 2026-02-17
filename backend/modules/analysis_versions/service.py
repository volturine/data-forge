import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import delete, desc, func, insert, select
from sqlmodel import Session, col

from core.exceptions import (
    AnalysisCycleError,
    AnalysisNotFoundError,
    AnalysisValidationError,
    AnalysisVersionNotFoundError,
    DataSourceNotFoundError,
)
from modules.analysis.models import Analysis, AnalysisDataSource
from modules.analysis_versions.models import AnalysisVersion
from modules.datasource.models import DataSource


def create_version(session: Session, analysis: Analysis, *, commit: bool = True) -> AnalysisVersion:
    version_id = str(uuid.uuid4())
    now = datetime.now(UTC).replace(tzinfo=None)
    next_version = (
        select(func.coalesce(func.max(AnalysisVersion.version), 0) + 1)
        .where(col(AnalysisVersion.analysis_id) == analysis.id)  # type: ignore[arg-type]
        .scalar_subquery()
    )
    stmt = insert(AnalysisVersion).values(
        id=version_id,
        analysis_id=analysis.id,
        version=next_version,
        name=analysis.name,
        description=analysis.description,
        pipeline_definition=analysis.pipeline_definition,
        created_at=now,
    )
    session.execute(stmt)
    if commit:
        session.commit()
    else:
        session.flush()
    version = session.get(AnalysisVersion, version_id)
    if not version:
        raise AnalysisValidationError('Failed to create analysis version')
    return version


def list_versions(session: Session, analysis_id: str) -> list[AnalysisVersion]:
    stmt = select(AnalysisVersion).where(col(AnalysisVersion.analysis_id) == analysis_id)  # type: ignore[arg-type]
    stmt = stmt.order_by(desc(col(AnalysisVersion.version)))  # type: ignore[arg-type]
    result = session.execute(stmt)
    return cast(list[AnalysisVersion], list(result.scalars().all()))


def get_version(session: Session, analysis_id: str, version: int) -> AnalysisVersion | None:
    stmt = select(AnalysisVersion).where(  # type: ignore[arg-type]
        col(AnalysisVersion.analysis_id) == analysis_id,
        col(AnalysisVersion.version) == version,
    )
    result = session.execute(stmt)
    return result.scalar_one_or_none()


def rename_version(session: Session, analysis_id: str, version: int, name: str) -> AnalysisVersion:
    target = get_version(session, analysis_id, version)
    if not target:
        raise AnalysisVersionNotFoundError(analysis_id, version)
    target.name = name
    session.commit()
    session.refresh(target)
    return target


def restore_version(session: Session, analysis_id: str, version: int) -> Analysis:
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    target = get_version(session, analysis_id, version)
    if not target:
        raise AnalysisVersionNotFoundError(analysis_id, version)

    create_version(session, analysis, commit=False)

    analysis.name = target.name
    analysis.description = target.description
    analysis.pipeline_definition = target.pipeline_definition
    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)

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
            created_by='analysis',
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(datasource)
        tab['datasource_id'] = datasource_id

    stmt = delete(AnalysisDataSource).where(col(AnalysisDataSource.analysis_id) == analysis_id)  # type: ignore[arg-type]
    session.execute(stmt)
    datasource_ids = analysis.pipeline_definition.get('datasource_ids', [])
    if tabs:
        datasource_ids = [tab.get('datasource_id') for tab in tabs if tab.get('datasource_id')]
    for datasource_id in datasource_ids:
        ds: DataSource | None = session.get(DataSource, datasource_id)
        if not ds:
            raise DataSourceNotFoundError(datasource_id)
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
        raise AnalysisCycleError('Analysis cannot use itself as a datasource')
    if _detect_cycle(session, analysis_id, source_analysis_id):
        raise AnalysisCycleError('Analysis datasource introduces a cycle')


def _detect_cycle(session: Session, analysis_id: str, source_analysis_id: str) -> bool:
    visited: set[str] = set()

    def visit(target_id: str) -> bool:
        if target_id == analysis_id:
            return True
        if target_id in visited:
            return False
        visited.add(target_id)
        stmt = select(AnalysisDataSource).where(col(AnalysisDataSource.analysis_id) == target_id)  # type: ignore[arg-type]
        links = session.execute(stmt).scalars().all()  # type: ignore[arg-type]
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
