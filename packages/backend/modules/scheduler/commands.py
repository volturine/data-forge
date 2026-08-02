from sqlmodel import Session

from backend_core import build_jobs_service as build_job_service, runtime_ipc
from backend_core.domain.scheduler.schemas import ScheduleCreate, ScheduleResponse, ScheduleUpdate
from backend_core.transactions import transaction
from modules.scheduler import service


def create_schedule(session: Session, payload: ScheduleCreate) -> ScheduleResponse:
    with transaction(session):
        schedule = service.stage_create_schedule(session, payload)
    session.refresh(schedule)
    response = service.enrich_schedule_response(session, schedule)
    runtime_ipc.notify_build_job()
    return response


def update_schedule(session: Session, schedule_id: str, payload: ScheduleUpdate) -> ScheduleResponse:
    with transaction(session):
        schedule = service.stage_update_schedule(session, schedule_id, payload)
    session.refresh(schedule)
    response = service.enrich_schedule_response(session, schedule)
    runtime_ipc.notify_build_job()
    return response


def delete_schedule(session: Session, schedule_id: str) -> None:
    with transaction(session):
        service.stage_delete_schedule(session, schedule_id)


def reconcile_expired_build_jobs(session: Session) -> int:
    with transaction(session):
        build_ids = build_job_service.stage_exhausted_jobs(session)
        for build_id in build_ids:
            service.apply_schedule_run_reconciliation(session, build_id=build_id)
    return len(build_ids)
