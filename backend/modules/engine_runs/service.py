import uuid
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlmodel import Session

from modules.engine_runs.models import EngineRun
from modules.engine_runs.schemas import EngineRunCreateSchema, EngineRunResponseSchema
from modules.engine_runs.utils import normalize_step_timings


def create_engine_run(
    session: Session,
    payload: EngineRunCreateSchema,
) -> EngineRunResponseSchema:
    run = EngineRun(
        id=payload.id,
        analysis_id=payload.analysis_id,
        datasource_id=payload.datasource_id,
        kind=payload.kind,
        status=payload.status,
        request_json=payload.request_json,
        result_json=payload.result_json,
        error_message=payload.error_message,
        created_at=payload.created_at,
        completed_at=payload.completed_at,
        duration_ms=payload.duration_ms,
        step_timings=normalize_step_timings(payload.step_timings),
        query_plan=payload.query_plan,
        progress=payload.progress,
        current_step=payload.current_step,
        triggered_by=payload.triggered_by,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return EngineRunResponseSchema.model_validate(run)


def create_engine_run_payload(
    analysis_id: str | None,
    datasource_id: str,
    kind: str,
    status: str,
    request_json: dict,
    result_json: dict | None = None,
    error_message: str | None = None,
    created_at: datetime | None = None,
    completed_at: datetime | None = None,
    duration_ms: int | None = None,
    step_timings: dict | None = None,
    query_plan: str | None = None,
    progress: float = 0.0,
    current_step: str | None = None,
    triggered_by: str | None = None,
) -> EngineRunCreateSchema:
    return EngineRunCreateSchema(
        id=str(uuid.uuid4()),
        analysis_id=analysis_id,
        datasource_id=datasource_id,
        kind=kind,
        status=status,
        request_json=request_json,
        result_json=result_json,
        error_message=error_message,
        created_at=created_at or datetime.now(UTC),
        completed_at=completed_at,
        duration_ms=duration_ms,
        step_timings=step_timings or {},
        query_plan=query_plan,
        progress=progress,
        current_step=current_step,
        triggered_by=triggered_by,
    )


def list_engine_runs(
    session: Session,
    analysis_id: str | None = None,
    datasource_id: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[EngineRunResponseSchema]:
    stmt = select(EngineRun)
    # SQLModel type annotations not fully compatible with Pydantic v2 - needed for .where() calls
    if analysis_id is not None:
        stmt = stmt.where(EngineRun.analysis_id == analysis_id)  # type: ignore[arg-type]
    if datasource_id is not None:
        stmt = stmt.where(EngineRun.datasource_id == datasource_id)  # type: ignore[arg-type]
    if kind is not None:
        stmt = stmt.where(EngineRun.kind == kind)  # type: ignore[arg-type]
    if status is not None:
        stmt = stmt.where(EngineRun.status == status)  # type: ignore[arg-type]

    stmt = stmt.order_by(desc(EngineRun.created_at)).limit(limit).offset(offset)  # type: ignore[arg-type]
    result = session.execute(stmt)
    runs = result.scalars().all()
    response: list[EngineRunResponseSchema] = []
    for run in runs:
        payload = run.model_dump()
        payload['step_timings'] = normalize_step_timings(run.step_timings)
        response.append(EngineRunResponseSchema.model_validate(payload))
    return response
