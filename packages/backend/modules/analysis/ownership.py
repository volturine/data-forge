"""Object-level ownership gate for analysis resources.

Placement choice: enforcement lives at the data-access boundary
(`require_analysis_revision` plus the version-mutating routes) rather than in
each endpoint, so every mutating path is covered uniformly. Records with an
owner may only be mutated by that owner while AUTH_REQUIRED is on; ownerless
records (legacy/local mode) stay writable for any authenticated user because
local mode cannot attribute owners retroactively.
"""

from fastapi import HTTPException
from sqlmodel import Session

from backend_core.auth_config import settings as auth_settings
from backend_core.persistence.analysis.models import Analysis


def ensure_mutation_allowed(owner_id: str | None, user_id: str | None) -> None:
    if not auth_settings.auth_required or owner_id is None:
        return
    if user_id != owner_id:
        raise HTTPException(status_code=403, detail='Only the owner can modify this resource')


def ensure_analysis_mutation_allowed(session: Session, analysis_id: str, user_id: str | None) -> None:
    analysis = session.get(Analysis, analysis_id)
    if analysis is not None:
        ensure_mutation_allowed(analysis.owner_id, user_id)
