from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlmodel import Session

from backend_core.persistence.analysis.models import Analysis
from backend_core.sqlmodel_typing import sa
from backend_core.validation import AnalysisId, parse_analysis_id
from modules.locks import service as lock_service


class RevisionedAnalysis(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def revision(self) -> int: ...


@dataclass(frozen=True)
class AnalysisRevisionSnapshot:
    id: str
    revision: int


def etag(analysis: RevisionedAnalysis) -> str:
    return etag_for(analysis.id, analysis.revision)


def etag_for(analysis_id: str, revision: int) -> str:
    return f'"analysis-{analysis_id}-{revision}"'


def version(analysis: RevisionedAnalysis) -> str:
    return str(analysis.revision)


def matches_if_none_match(header: str | None, current_etag: str) -> bool:
    if header is None:
        return False
    expected = current_etag.strip('"')
    for token in header.split(','):
        candidate = token.strip()
        if candidate == '*':
            return True
        if candidate.startswith('W/'):
            candidate = candidate[2:].strip()
        if candidate.strip('"') == expected:
            return True
    return False


def set_response_headers(response: Response, analysis: RevisionedAnalysis) -> None:
    response.headers['ETag'] = etag(analysis)
    response.headers['X-Analysis-Version'] = version(analysis)


def validate(current_revision: int, analysis_id: str, if_match: str | None) -> None:
    if if_match is None:
        raise HTTPException(status_code=428, detail='If-Match analysis revision is required')
    normalized = if_match.strip()
    if normalized in {str(current_revision), f'"analysis-{analysis_id}-{current_revision}"'}:
        return
    raise HTTPException(status_code=412, detail='Analysis version mismatch')


def require(
    analysis_id: AnalysisId,
    if_match: str | None,
    session: Session,
    owner_id: str | None,
) -> Analysis:
    """Validate a mutation against its caller-owned transaction/session."""
    parsed_id = parse_analysis_id(analysis_id)
    try:
        lock_service.ensure_mutation_lock(session, 'analysis', parsed_id, owner_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    analysis = session.execute(select(Analysis).where(sa(Analysis.id == parsed_id)).with_for_update()).scalar_one_or_none()
    if analysis is None:
        raise HTTPException(status_code=404, detail=f'Analysis {parsed_id} not found')
    validate(analysis.revision, analysis.id, if_match)
    return analysis
