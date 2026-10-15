from __future__ import annotations

from sqlalchemy import select
from sqlmodel import Session

from backend_core.exceptions import AnalysisCycleError
from backend_core.persistence.analysis.models import AnalysisDataSource
from backend_core.persistence.datasource.models import DataSource
from backend_core.sqlmodel_typing import col


def assert_no_analysis_cycle(session: Session, analysis_id: str, source_analysis_id: str) -> None:
    if analysis_id == source_analysis_id:
        raise AnalysisCycleError('Analysis cannot use itself as a datasource')
    visited: set[str] = set()

    def reaches_analysis(target_id: str) -> bool:
        if target_id == analysis_id:
            return True
        if target_id in visited:
            return False
        visited.add(target_id)
        stmt = select(AnalysisDataSource).where(col(AnalysisDataSource.analysis_id) == target_id)
        for link in session.execute(stmt).scalars().all():
            datasource = session.get(DataSource, link.datasource_id)
            if datasource is not None and datasource.is_analysis_source and reaches_analysis(datasource.analysis_source_id()):
                return True
        return False

    if reaches_analysis(source_analysis_id):
        raise AnalysisCycleError('Analysis datasource introduces a cycle')
