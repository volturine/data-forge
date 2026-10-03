from __future__ import annotations

from fastapi import Request
from sqlmodel import Session

from backend_core.api_execution_budget import run_api_blocking
from backend_core.database import run_settings_db
from backend_core.error_handlers import handle_errors
from modules.mcp.router import MCPRouter

from . import schemas, service

router = MCPRouter(prefix='/runtime', tags=['runtime'])


@router.get('/overview', response_model=schemas.RuntimeOverviewResponse)
@handle_errors(operation='get runtime overview')
async def get_runtime_overview(request: Request) -> schemas.RuntimeOverviewResponse:
    worker_id = getattr(request.app.state, 'api_worker_id', None)
    return await run_api_blocking(_read_runtime_overview, worker_id)


def _read_runtime_overview(worker_id: str | None) -> schemas.RuntimeOverviewResponse:
    return run_settings_db(_build_runtime_overview, worker_id)


def _build_runtime_overview(session: Session, worker_id: str | None) -> schemas.RuntimeOverviewResponse:
    return schemas.RuntimeOverviewResponse(
        mode=service.runtime_mode(),
        api=service.api_process(worker_id),
        workers=service.list_worker_summaries(session),
        engines=service.list_engine_summaries(session),
        queue=service.queue_summary(session),
    )
