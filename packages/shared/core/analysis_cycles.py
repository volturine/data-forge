from __future__ import annotations

from sqlalchemy import select
from sqlmodel import Session, col

from contracts.analysis.models import AnalysisDataSource
from contracts.datasource.models import DataSource
from core.exceptions import AnalysisCycleError


def detect_analysis_cycle(session: Session, analysis_id: str, source_analysis_id: str) -> bool:
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
            if datasource is None or not datasource.is_analysis_source:
                continue
            if visit(datasource.analysis_source_id()):
                return True
        return False

    return visit(source_analysis_id)


def assert_no_analysis_cycle(session: Session, analysis_id: str, source_analysis_id: str) -> None:
    if analysis_id == source_analysis_id:
        raise AnalysisCycleError('Analysis cannot use itself as a datasource')
    if detect_analysis_cycle(session, analysis_id, source_analysis_id):
        raise AnalysisCycleError('Analysis datasource introduces a cycle')
