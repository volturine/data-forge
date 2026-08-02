import contextlib
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session

from backend_core import build_jobs_service, build_runs_service, engine_runs_service, runtime_outbox_service
from backend_core.domain.compute import schemas
from backend_core.persistence.build_runs.models import BuildEvent
from backend_core.transactions import committed
from modules.datasource import service as datasource_service
from modules.scheduler import service as scheduler_service


class BuildCancellationConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class OutputPlaceholder:
    result_id: str
    tab_id: str
    name: str | None
    source_type: datasource_service.DataSourceType
    config: dict[str, object] | None


@dataclass(frozen=True)
class StartBuildCommand:
    build_id: str
    namespace: str
    analysis_id: str
    analysis_name: str
    request_json: dict[str, object]
    starter_json: dict[str, object]
    current_kind: str
    current_datasource_id: str | None
    current_tab_id: str | None
    current_tab_name: str | None
    current_output_id: str | None
    current_output_name: str | None
    total_tabs: int
    started_at: datetime
    placeholders: list[OutputPlaceholder]


@committed
def start_build(session: Session, command: StartBuildCommand) -> None:
    for placeholder in command.placeholders:
        datasource_service.create_placeholder_output_datasource(
            session,
            result_id=placeholder.result_id,
            analysis_id=command.analysis_id,
            analysis_tab_id=placeholder.tab_id,
            name=placeholder.name,
            source_type=placeholder.source_type,
            config=placeholder.config,
        )
    build_runs_service.stage_build_run(
        session,
        build_id=command.build_id,
        namespace=command.namespace,
        analysis_id=command.analysis_id,
        analysis_name=command.analysis_name,
        request_json=command.request_json,
        starter_json=command.starter_json,
        status=build_runs_service.BuildRunStatus.QUEUED,
        current_kind=command.current_kind,
        current_datasource_id=command.current_datasource_id,
        current_tab_id=command.current_tab_id,
        current_tab_name=command.current_tab_name,
        current_output_id=command.current_output_id,
        current_output_name=command.current_output_name,
        total_tabs=command.total_tabs,
        created_at=command.started_at,
        started_at=command.started_at,
    )
    build_jobs_service.stage_job(session, build_id=command.build_id, namespace=command.namespace)
    runtime_outbox_service.enqueue_api_build_notification(session, namespace=command.namespace, build_id=command.build_id, latest_sequence=0)
    runtime_outbox_service.enqueue_build_job_notification(session)


@committed
def cancel_build(
    session: Session,
    *,
    detail: schemas.ActiveBuildDetail,
    event: schemas.BuildCancelledEvent,
) -> BuildEvent:
    job = build_jobs_service.get_job_by_build_id(session, detail.build_id)
    if job is None:
        raise BuildCancellationConflict('Active build has no cancellable job')
    job_status = build_jobs_service.BuildJobStatus.require(job.status)
    if job_status != build_jobs_service.BuildJobStatus.QUEUED and not job_status.is_active:
        raise BuildCancellationConflict('Build job became terminal before cancellation')
    cancelled_job = build_jobs_service.stage_job_cancelled(session, job.id)
    if build_jobs_service.BuildJobStatus.require(cancelled_job.status) != build_jobs_service.BuildJobStatus.CANCELLED:
        raise BuildCancellationConflict('Build job became terminal before cancellation')
    event_row = build_runs_service.stage_build_event(
        session,
        build_id=detail.build_id,
        event=event,
        resource_config_json=detail.resource_config.model_dump(mode='json') if detail.resource_config is not None else None,
        authoritative_execution_generation=cancelled_job.lease_generation,
    )
    if event_row is None:
        raise BuildCancellationConflict('Build became terminal before cancellation')
    if detail.current_engine_run_id is not None:
        run = engine_runs_service.get_engine_run(session, detail.current_engine_run_id)
        if run is not None and run.status == engine_runs_service.EngineRunStatus.RUNNING:
            with contextlib.suppress(ValueError):
                engine_runs_service.stage_cancel_engine_run(
                    session,
                    detail.current_engine_run_id,
                    cancelled_by=event.cancelled_by,
                )
    scheduler_service.apply_schedule_run_reconciliation(session, build_id=detail.build_id)
    return event_row
