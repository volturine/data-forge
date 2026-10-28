import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import desc, func, insert, select
from sqlmodel import Session

from backend_core.domain.analysis.pipeline_types import PipelineDefinition
from backend_core.exceptions import analysis_not_found, analysis_version_not_found
from backend_core.persistence.analysis.models import Analysis
from backend_core.persistence.analysis_versions.models import AnalysisVersion
from backend_core.sqlmodel_typing import col
from modules.analysis import service as analysis_service


def create_version(session: Session, analysis: Analysis) -> AnalysisVersion:
    session.execute(select(Analysis).where(col(Analysis.id) == analysis.id).with_for_update()).scalar_one()
    version_id = str(uuid.uuid4())
    now = datetime.now(UTC).replace(tzinfo=None)
    next_version = select(func.coalesce(func.max(AnalysisVersion.version), 0) + 1).where(col(AnalysisVersion.analysis_id) == analysis.id).scalar_subquery()
    stmt = (
        insert(AnalysisVersion)
        .values(
            id=version_id,
            analysis_id=analysis.id,
            version=next_version,
            name=analysis.name,
            description=analysis.description,
            pipeline_definition=analysis.pipeline_definition,
            created_at=now,
        )
        .returning(AnalysisVersion)
    )
    return session.execute(stmt).scalar_one()


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

    # Validation runs before anything is mutated, so a failed restore never
    # leaves a bogus safety snapshot. Restore stores the same normalized
    # pipeline and datasource links that create and update write.
    tabs, datasource_ids = analysis_service.validate_stored_pipeline_definition(session, target.pipeline_definition, analysis_id)

    create_version(session, analysis)

    analysis.name = target.name
    analysis.description = target.description
    analysis.pipeline_definition = PipelineDefinition(tabs=tabs).to_dict()
    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)
    analysis.revision += 1
    analysis_service.replace_datasource_links(session, analysis_id, datasource_ids)

    session.commit()
    session.refresh(analysis)
    return analysis
