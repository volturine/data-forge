from typing import Any

from sqlmodel import Session

from backend_core import engine_runs_service
from backend_core.domain.engine_runs.schemas import EngineRunResponseSchema
from backend_core.transactions import committed

create_engine_run = committed(engine_runs_service.stage_create_engine_run)


@committed
def update_engine_run(
    session: Session,
    run_id: str,
    **changes: Any,
) -> EngineRunResponseSchema:
    return engine_runs_service.stage_update_engine_run(session, run_id, **changes)
