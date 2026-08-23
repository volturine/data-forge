import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import delete, desc, func, insert, select
from sqlmodel import Session

from backend_core.analysis_cycles import assert_no_analysis_cycle
from backend_core.exceptions import (
    AnalysisValidationError,
    analysis_not_found,
    analysis_version_not_found,
    datasource_not_found,
)
from backend_core.persistence.analysis.models import Analysis, AnalysisDataSource
from backend_core.persistence.analysis_versions.models import AnalysisVersion
from backend_core.persistence.datasource.models import DataSource
from backend_core.sqlmodel_typing import col
from modules.analysis import service as analysis_service


def create_version(session: Session, analysis: Analysis) -> AnalysisVersion:
    session.execute(select(Analysis).where(col(Analysis.id) == analysis.id).with_for_update()).scalar_one()
    version_id = str(uuid.uuid4())
    now = datetime.now(UTC).replace(tzinfo=None)
    next_version = select(func.coalesce(func.max(AnalysisVersion.version), 0) + 1).where(col(AnalysisVersion.analysis_id) == analysis.id).scalar_subquery()
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
    session.flush()
    version = session.get(AnalysisVersion, version_id)
    if not version:
        raise AnalysisValidationError('Failed to create analysis version')
    return version


def list_versions(session: Session, analysis_id: str) -> list[AnalysisVersion]:
    stmt = select(AnalysisVersion).where(col(AnalysisVersion.analysis_id) == analysis_id)
    stmt = stmt.order_by(desc(col(AnalysisVersion.version)))
    result = session.execute(stmt)
    return cast(list[AnalysisVersion], list(result.scalars().all()))


def get_version(session: Session, analysis_id: str, version: int) -> AnalysisVersion | None:
    stmt = select(AnalysisVersion).where(
        col(AnalysisVersion.analysis_id) == analysis_id,
        col(AnalysisVersion.version) == version,
    )
    result = session.execute(stmt)
    return result.scalar_one_or_none()


def delete_version(session: Session, analysis_id: str, version: int) -> None:
    target = get_version(session, analysis_id, version)
    if not target:
        raise analysis_version_not_found(analysis_id, version)
    session.delete(target)
    session.commit()


def rename_version(session: Session, analysis_id: str, version: int, name: str) -> AnalysisVersion:
    target = get_version(session, analysis_id, version)
    if not target:
        raise analysis_version_not_found(analysis_id, version)
    target.name = name
    session.commit()
    session.refresh(target)
    return target


def restore_version(session: Session, analysis_id: str, version: int) -> Analysis:
    analysis = session.execute(select(Analysis).where(col(Analysis.id) == analysis_id).with_for_update()).scalar_one_or_none()
    if not analysis:
        raise analysis_not_found(analysis_id)

    target = get_version(session, analysis_id, version)
    if not target:
        raise analysis_version_not_found(analysis_id, version)

    # Work on a detached copy end-to-end: validation runs BEFORE anything is
    # mutated (a failed validation must not leave a bogus safety snapshot),
    # and the assignment can never alias the version row's live JSON.
    restored_definition = deepcopy(target.pipeline_definition)
    analysis_service.validate_stored_pipeline_definition(session, restored_definition, analysis_id)

    create_version(session, analysis)

    analysis.name = target.name
    analysis.description = target.description
    analysis.pipeline_definition = restored_definition
    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)
    analysis.revision += 1

    pipeline_definition = analysis.pipeline_definition
    tabs = pipeline_definition.get('tabs', [])

    stmt = delete(AnalysisDataSource).where(col(AnalysisDataSource.analysis_id) == analysis_id)
    session.execute(stmt)
    datasource_ids: list[str] = []
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        datasource = tab.get('datasource')
        if not isinstance(datasource, dict):
            continue
        if datasource.get('analysis_tab_id') is not None:
            continue
        datasource_id = datasource.get('id')
        if datasource_id:
            datasource_ids.append(str(datasource_id))
    for datasource_id in set(datasource_ids):
        ds: DataSource | None = session.get(DataSource, datasource_id)
        if not ds:
            raise datasource_not_found(datasource_id)
        if ds.is_analysis_source:
            source_id = ds.analysis_source_id()
            assert_no_analysis_cycle(session, analysis_id, source_id)
        session.add(
            AnalysisDataSource(
                analysis_id=analysis_id,
                datasource_id=datasource_id,
            ),
        )

    session.commit()
    session.refresh(analysis)
    return analysis
