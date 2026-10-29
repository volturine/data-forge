"""Compute worker run factories shared by the build comparison test modules."""

import uuid
from datetime import UTC, datetime

from sqlmodel import Session

from backend_core.persistence.compute_worker_runs.models import ComputeWorkerRun


def create_compute_worker_run(
    session: Session,
    *,
    datasource_id: str | None = None,
    analysis_id: str | None = None,
    kind: str = 'download',
    status: str = 'success',
    result_json: dict | None = None,
    step_timings: dict | None = None,
    duration_ms: int | None = None,
) -> ComputeWorkerRun:
    run = ComputeWorkerRun(
        id=str(uuid.uuid4()),
        analysis_id=analysis_id or str(uuid.uuid4()),
        datasource_id=datasource_id or str(uuid.uuid4()),
        kind=kind,
        status=status,
        request_json={},
        result_json=result_json,
        created_at=datetime.now(UTC).replace(tzinfo=None),
        step_timings=step_timings or {},
        progress=1.0,
        duration_ms=duration_ms,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run
