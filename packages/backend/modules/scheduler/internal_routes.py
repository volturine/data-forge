from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status

from backend_contracts.runtime_workers.models import RuntimeWorkerKind
from backend_core import runtime_workers_service as runtime_worker_service
from backend_core.config import settings
from backend_core.database import run_db, run_settings_db
from backend_core.namespace import reset_namespace, set_namespace_context
from backend_core.namespaces_service import list_runtime_namespaces
from modules.scheduler import service
from modules.scheduler.internal_schemas import (
    SchedulerEnqueuedRun,
    SchedulerRegisterRequest,
    SchedulerRunDueResponse,
    SchedulerRunFailure,
    SchedulerWorkerRequest,
    SchedulerWorkerResponse,
)

router = APIRouter(prefix='/internal/scheduler', tags=['internal-scheduler'])


def _require_internal_token(x_internal_token: Annotated[str | None, Header(alias='X-Internal-Token')] = None) -> None:
    if not settings.internal_api_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='INTERNAL_API_TOKEN must be configured before internal runtime endpoints can be used',
        )
    if x_internal_token != settings.internal_api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid internal runtime token')


@router.post('/register', response_model=SchedulerWorkerResponse)
def register_scheduler(payload: SchedulerRegisterRequest, _: None = Depends(_require_internal_token)) -> SchedulerWorkerResponse:
    def _register(session):
        runtime_worker_service.register_worker(
            session,
            worker_id=payload.worker_id,
            kind=RuntimeWorkerKind.SCHEDULER,
            hostname=payload.hostname,
            pid=payload.pid,
            capacity=payload.capacity,
        )

    run_settings_db(_register)
    return SchedulerWorkerResponse(worker_id=payload.worker_id)


@router.post('/heartbeat', response_model=SchedulerWorkerResponse)
def heartbeat_scheduler(payload: SchedulerWorkerRequest, _: None = Depends(_require_internal_token)) -> SchedulerWorkerResponse:
    def _heartbeat(session):
        runtime_worker_service.heartbeat_worker(session, worker_id=payload.worker_id)

    run_settings_db(_heartbeat)
    return SchedulerWorkerResponse(worker_id=payload.worker_id)


@router.post('/stop', response_model=SchedulerWorkerResponse)
def stop_scheduler(payload: SchedulerWorkerRequest, _: None = Depends(_require_internal_token)) -> SchedulerWorkerResponse:
    def _stop(session):
        runtime_worker_service.mark_worker_stopped(session, worker_id=payload.worker_id)

    run_settings_db(_stop)
    return SchedulerWorkerResponse(worker_id=payload.worker_id)


@router.post('/run-due', response_model=SchedulerRunDueResponse)
def run_due_schedules(payload: SchedulerWorkerRequest, _: None = Depends(_require_internal_token)) -> SchedulerRunDueResponse:
    reclaimable_owner_ids = run_settings_db(
        runtime_worker_service.reclaimable_worker_ids,
        kind=RuntimeWorkerKind.SCHEDULER,
    )
    enqueued: list[SchedulerEnqueuedRun] = []
    failures: list[SchedulerRunFailure] = []
    for namespace in run_settings_db(list_runtime_namespaces):
        token = set_namespace_context(namespace)
        try:
            claimed = run_db(
                lambda session: [
                    (schedule.id, schedule.datasource_id)
                    for schedule in service.claim_due_schedules(
                        session,
                        worker_id=payload.worker_id,
                        reclaimable_owner_ids=reclaimable_owner_ids,
                    )
                ]
            )
            for schedule_id, datasource_id in claimed:
                try:

                    def _enqueue(session: Any, target_id: str = schedule_id) -> str:
                        return service.enqueue_schedule_run(
                            session,
                            target_id,
                            worker_id=payload.worker_id,
                        )

                    build_id = run_db(_enqueue)
                    enqueued.append(
                        SchedulerEnqueuedRun(
                            namespace=namespace,
                            schedule_id=schedule_id,
                            datasource_id=datasource_id,
                            build_id=build_id,
                        )
                    )
                except Exception as exc:

                    def _mark_failed(session: Any, target_id: str = schedule_id, error: str = str(exc)) -> None:
                        service.mark_schedule_enqueue_failed(
                            session,
                            target_id,
                            error=error,
                        )

                    run_db(_mark_failed)
                    failures.append(
                        SchedulerRunFailure(
                            namespace=namespace,
                            schedule_id=schedule_id,
                            datasource_id=datasource_id,
                            error=str(exc),
                        )
                    )
        finally:
            reset_namespace(token)
    return SchedulerRunDueResponse(handled=bool(enqueued or failures), enqueued=enqueued, failures=failures)
