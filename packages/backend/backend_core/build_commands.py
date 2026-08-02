from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session

from backend_core import build_jobs_service, build_runs_service
from backend_core.domain.build_jobs.models import BuildJobStatus
from backend_core.domain.build_runs.models import BuildRunStatus
from backend_core.domain.compute import schemas as compute_schemas
from backend_core.domain.engine_runs.schemas import EngineRunKind
from backend_core.persistence.build_jobs.models import BuildJob
from backend_core.transactions import committed
from modules.scheduler import service as scheduler_service


@dataclass(frozen=True)
class BuildClaimCommand:
    job_id: str
    build_id: str
    worker_id: str
    claim_token: str
    lease_generation: int


@dataclass(frozen=True)
class FailedBuildResult:
    job: BuildJob
    namespace: str
    latest_sequence: int | None


def _terminal_outcome(run_status: BuildRunStatus | str, error_message: str | None) -> tuple[BuildJobStatus, str | None] | None:
    status = BuildRunStatus.require(run_status)
    if status == BuildRunStatus.CANCELLED:
        return BuildJobStatus.CANCELLED, None
    if status == BuildRunStatus.COMPLETED:
        return BuildJobStatus.COMPLETED, None
    if status in {BuildRunStatus.FAILED, BuildRunStatus.ORPHANED}:
        return BuildJobStatus.FAILED, error_message
    return None


@committed
def fail_build_job(session: Session, claim: BuildClaimCommand, *, error: str) -> FailedBuildResult | None:
    active_claim = build_jobs_service.lock_active_job_claim(
        session,
        claim.job_id,
        build_id=claim.build_id,
        worker_id=claim.worker_id,
        claim_token=claim.claim_token,
        lease_generation=claim.lease_generation,
    )
    if active_claim is None:
        return None
    run = build_runs_service.get_build_run(session, claim.build_id)
    if run is None:
        return None
    latest_sequence: int | None = None
    outcome = _terminal_outcome(run.status, run.error_message)
    if outcome is None:
        failed_event = compute_schemas.BuildFailedEvent(
            build_id=run.id,
            analysis_id=run.analysis_id,
            emitted_at=datetime.now(UTC),
            current_kind=EngineRunKind.parse(run.current_kind) if run.current_kind is not None else None,
            current_datasource_id=run.current_datasource_id,
            tab_id=run.current_tab_id,
            tab_name=run.current_tab_name,
            current_output_id=run.current_output_id,
            current_output_name=run.current_output_name,
            engine_run_id=run.current_engine_run_id,
            progress=run.progress,
            elapsed_ms=run.elapsed_ms,
            total_steps=run.total_steps,
            tabs_built=0,
            results=[],
            duration_ms=run.elapsed_ms,
            error=error,
        )
        event_row = build_runs_service.stage_build_event(
            session,
            build_id=claim.build_id,
            event=failed_event,
            expected_execution_generation=claim.lease_generation,
        )
        if event_row is None:
            return None
        latest_sequence = event_row.sequence
        outcome = (BuildJobStatus.FAILED, error)
    status, terminal_error = outcome
    job = build_jobs_service.finish_claimed_job(
        session,
        claim.job_id,
        worker_id=claim.worker_id,
        build_id=claim.build_id,
        claim_token=claim.claim_token,
        lease_generation=claim.lease_generation,
        status=status,
        error=terminal_error,
    )
    if job is None:
        return None
    scheduler_service.apply_schedule_run_reconciliation(session, build_id=claim.build_id)
    return FailedBuildResult(job=job, namespace=run.namespace, latest_sequence=latest_sequence)


@committed
def finalize_build_job(session: Session, claim: BuildClaimCommand) -> BuildJob | None:
    active_claim = build_jobs_service.lock_active_job_claim(
        session,
        claim.job_id,
        build_id=claim.build_id,
        worker_id=claim.worker_id,
        claim_token=claim.claim_token,
        lease_generation=claim.lease_generation,
    )
    if active_claim is None:
        return None
    run = build_runs_service.get_build_run(session, claim.build_id)
    if run is None:
        return None
    outcome = _terminal_outcome(run.status, run.error_message)
    if outcome is None:
        return None
    status, error = outcome
    job = build_jobs_service.finish_claimed_job(
        session,
        claim.job_id,
        worker_id=claim.worker_id,
        build_id=claim.build_id,
        claim_token=claim.claim_token,
        lease_generation=claim.lease_generation,
        status=status,
        error=error,
    )
    if job is None:
        return None
    scheduler_service.apply_schedule_run_reconciliation(session, build_id=claim.build_id)
    return job
