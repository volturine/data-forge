from __future__ import annotations

from core.database import get_settings_db
from fastapi import Depends, Request
from sqlmodel import Session

from backend_core.error_handlers import handle_errors
from modules.mcp.router import MCPRouter

from . import schemas, service

router = MCPRouter(prefix="/runtime", tags=["runtime"])


@router.get("/overview", response_model=schemas.RuntimeOverviewResponse)
@handle_errors(operation="get runtime overview")
def get_runtime_overview(request: Request, session: Session = Depends(get_settings_db)) -> schemas.RuntimeOverviewResponse:
    worker_id = getattr(request.app.state, "api_worker_id", None)
    return schemas.RuntimeOverviewResponse(
        mode=service.runtime_mode(),
        api=service.api_process(worker_id),
        workers=service.list_worker_summaries(session),
        engines=service.list_engine_summaries(session),
        queue=service.queue_summary(),
    )
