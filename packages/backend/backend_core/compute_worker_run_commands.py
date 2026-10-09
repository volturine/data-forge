from typing import Any

from sqlmodel import Session

from backend_core import compute_worker_runs_service
from backend_core.domain.compute_worker_runs.schemas import ComputeWorkerRunResponseSchema
from backend_core.transactions import committed

create_compute_worker_run = committed(compute_worker_runs_service.stage_create_compute_worker_run)


@committed
def update_compute_worker_run(
    session: Session,
    run_id: str,
    **changes: Any,
) -> ComputeWorkerRunResponseSchema:
    result = compute_worker_runs_service.stage_update_compute_worker_run(session, run_id, **changes)
    if isinstance(result, bool):
        raise ValueError('Compute worker run response serialization cannot be disabled on the API command path')
    return result
