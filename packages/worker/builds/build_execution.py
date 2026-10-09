from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator

from builds.build_live import RuntimeBuild
from dataforge_protocol import compute_pb2, enums_pb2
from operations.step_converter import analysis_pipeline_to_execution_payload
from runtime import compute_service as service
from runtime.compute_manager import COMPUTE_WORKER_ADMISSION_PRIORITY_LIFECYCLE, ComputeWorkerCapacityFull, ProcessManager
from runtime.domain.compute import schemas
from runtime.domain.compute_worker_runs.schemas import ComputeWorkerRunKind
from runtime.domain.datasource.models import DataSourceTargetKind
from runtime.executors import run_compute_in_thread, run_control_in_thread
from runtime.namespace import reset_namespace, set_namespace_context
from runtime.worker_runtime_client import BuildJobLeaseLost, ClaimedBuildJob, WorkerRuntimeClient, async_client_from_env, client_from_env

logger = logging.getLogger(__name__)

_BUILD_CAPACITY_RACE_TIMEOUT_SECONDS = 2.0


@contextlib.asynccontextmanager
async def _work_slot(semaphore: asyncio.Semaphore | None) -> AsyncIterator[None]:
    if semaphore is None:
        yield
        return
    async with semaphore:
        yield


@contextlib.asynccontextmanager
async def _admitted_build_work_slot(
    manager: ProcessManager,
    identity: compute_pb2.ComputeWorkerIdentity,
    *,
    namespace: str,
    work_semaphore: asyncio.Semaphore | None,
) -> AsyncIterator[None]:
    # An engine-backed build already owns one slot in ProcessManager's global
    # COMPUTE_WORKERS budget and one per-identity job slot. Taking the shared
    # semaphore as well can park a reserved worker while another lane is full.
    del work_semaphore
    owns_admission = await manager.await_engine_request_admission(
        identity,
        namespace=namespace,
        priority=COMPUTE_WORKER_ADMISSION_PRIORITY_LIFECYCLE,
    )
    request_reserved = not owns_admission
    try:
        if owns_admission:
            manager.reserve_engine_request(identity, namespace=namespace)
            request_reserved = True
        yield
    finally:
        if request_reserved:
            manager.release_engine_request(identity, namespace=namespace)
        await run_control_in_thread(
            manager.release_spawn_admission,
            identity,
            namespace=namespace,
            owned=owns_admission,
        )


def worker_runtime_client() -> WorkerRuntimeClient:
    return client_from_env()


async def _wait_after_capacity_race(manager: ProcessManager) -> None:
    """Rejoin bounded capacity admission after a build loses a slot race."""
    await manager.wait_for_capacity(timeout_seconds=_BUILD_CAPACITY_RACE_TIMEOUT_SECONDS)


async def _emit_build_event(
    claim: ClaimedBuildJob,
    worker_id: str,
    payload: schemas.BuildEvent,
    *,
    resource_config_json: dict[str, object] | None = None,
) -> None:
    token = set_namespace_context(claim.namespace)
    try:
        client = await async_client_from_env()
        sequence = await client.persist_build_event_async(
            namespace=claim.namespace,
            build_id=claim.build_id,
            job_id=claim.job_id,
            worker_id=worker_id,
            claim_token=claim.claim_token,
            lease_generation=claim.lease_generation,
            event=payload.model_dump(mode="json"),
            resource_config_json=resource_config_json,
        )
        if sequence is None:
            raise BuildJobLeaseLost(f"Build job {claim.job_id} event was rejected because its lease is no longer active")
    finally:
        reset_namespace(token)


async def _run_build_task(
    *,
    manager: ProcessManager,
    claim: ClaimedBuildJob,
    worker_id: str,
    build: RuntimeBuild,
    pipeline: dict,
    triggered_by: str | None,
) -> None:
    token = set_namespace_context(build.namespace)
    try:
        await service.run_analysis_build_stream(
            session=None,
            manager=manager,
            pipeline=pipeline,
            build=build,
            emitter=lambda payload: _emit_build_event(
                claim,
                worker_id,
                payload,
                resource_config_json=build.resource_config_json,
            ),
            triggered_by=triggered_by,
            publication_claim=claim,
            worker_id=worker_id,
        )
    except BuildJobLeaseLost:
        raise
    except Exception as exc:
        logger.error("Active build task error: %s", exc, exc_info=True)
        if build.status == schemas.BuildLifecycleStatus.RUNNING:
            await _emit_build_event(
                claim,
                worker_id,
                schemas.BuildFailedEvent(
                    build_id=build.build_id,
                    analysis_id=build.analysis_id,
                    emitted_at=service._utcnow(),
                    current_kind=ComputeWorkerRunKind.parse(build.current_kind),
                    current_datasource_id=build.current_datasource_id,
                    tab_id=build.current_tab_id,
                    tab_name=build.current_tab_name,
                    current_output_id=build.current_output_id,
                    current_output_name=build.current_output_name,
                    compute_worker_run_id=build.current_compute_worker_run_id,
                    progress=build.progress,
                    elapsed_ms=build.elapsed_ms,
                    total_steps=build.total_steps,
                    tabs_built=len(build.results),
                    results=build.results,
                    duration_ms=build.elapsed_ms,
                    error="Build failed due to an internal error",
                ),
                resource_config_json=build.resource_config_json,
            )
    finally:
        reset_namespace(token)


async def _run_queued_build_job(
    *,
    manager: ProcessManager,
    worker_id: str,
    claim: ClaimedBuildJob,
    work_semaphore: asyncio.Semaphore | None,
) -> None:
    build: RuntimeBuild | None = None
    pipeline: dict | None = None
    starter: schemas.BuildStarter | None = None
    client = await async_client_from_env()
    run = await client.start_build_run_async(
        namespace=claim.namespace,
        build_id=claim.build_id,
        job_id=claim.job_id,
        worker_id=worker_id,
        claim_token=claim.claim_token,
        lease_generation=claim.lease_generation,
    )
    if run is None:
        raise BuildJobLeaseLost(f"Build job {claim.job_id} start was rejected because its lease is no longer active")
    pipeline = {**analysis_pipeline_to_execution_payload(run.analysis_pipeline), "tab_id": run.tab_id}
    starter = schemas.BuildStarter.model_validate(run.starter_json)
    build = RuntimeBuild(
        build_id=run.id,
        analysis_id=run.analysis_id,
        analysis_name=run.analysis_name,
        namespace=run.namespace,
        starter=starter,
        total_tabs=run.total_tabs,
        current_kind=run.current_kind,
        current_datasource_id=run.current_datasource_id,
        current_tab_id=run.current_tab_id,
        current_tab_name=run.current_tab_name,
        current_output_id=run.current_output_id,
        current_output_name=run.current_output_name,
        started_at=run.started_at,
        status=schemas.BuildLifecycleStatus.RUNNING,
    )
    if build is None or pipeline is None or starter is None:
        return
    current_kind = build.current_kind or ""
    compute_worker_run_kind = ComputeWorkerRunKind.parse(build.current_kind)
    is_schedule_ingest = (
        compute_worker_run_kind == ComputeWorkerRunKind.BUILD
        and starter.is_schedule_trigger()
        and len(run.analysis_pipeline.tabs) == 1
        and run.analysis_pipeline.tabs[0].datasource.source_type == enums_pb2.DATA_SOURCE_TYPE_SCHEDULE
    )
    if current_kind == DataSourceTargetKind.RAW.value or is_schedule_ingest:
        datasource_id = build.current_datasource_id
        if datasource_id is None:
            raise ValueError(f"Queued schedule build {build.build_id} missing datasource id")
        try:
            from datasources import execution as datasource_execution
            from runtime.config import settings as worker_settings

            datasource_identity = compute_pb2.ComputeWorkerIdentity(
                scope=enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW,
                reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
                datasource_id=datasource_id,
                resource_id=datasource_id,
            )
            step_id = f"{build.build_id}:ingest"
            step_name = "Ingest"
            await _emit_build_event(
                claim,
                worker_id,
                schemas.BuildStepStartEvent(
                    build_id=build.build_id,
                    analysis_id=build.analysis_id,
                    emitted_at=service._utcnow(),
                    current_kind=ComputeWorkerRunKind.parse(build.current_kind),
                    current_datasource_id=build.current_datasource_id,
                    tab_id=build.current_tab_id,
                    tab_name=build.current_tab_name,
                    current_output_id=build.current_output_id,
                    current_output_name=build.current_output_name,
                    compute_worker_run_id=None,
                    build_step_index=0,
                    step_index=0,
                    step_id=step_id,
                    step_name=step_name,
                    step_type="read",
                    total_steps=1,
                ),
                resource_config_json=build.resource_config_json,
            )
            started = time.perf_counter()
            try:
                async with _admitted_build_work_slot(manager, datasource_identity, namespace=build.namespace, work_semaphore=work_semaphore):
                    refreshed = await run_compute_in_thread(
                        datasource_execution.ingest_datasource_for_schedule,
                        worker_runtime_client(),
                        manager=manager,
                        namespace=build.namespace,
                        database_url=worker_settings.database_url,
                        datasource_id=datasource_id,
                        staging_key=claim.claim_token,
                        worker_id=worker_id,
                        claim_token=claim.claim_token,
                        lease_generation=claim.lease_generation,
                        job_id=claim.job_id,
                        build_id=claim.build_id,
                    )
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                await _emit_build_event(
                    claim,
                    worker_id,
                    schemas.BuildStepFailedEvent(
                        build_id=build.build_id,
                        analysis_id=build.analysis_id,
                        emitted_at=service._utcnow(),
                        current_kind=ComputeWorkerRunKind.parse(build.current_kind),
                        current_datasource_id=build.current_datasource_id,
                        tab_id=build.current_tab_id,
                        tab_name=build.current_tab_name,
                        current_output_id=build.current_output_id,
                        current_output_name=build.current_output_name,
                        compute_worker_run_id=None,
                        build_step_index=0,
                        step_index=0,
                        step_id=step_id,
                        step_name=step_name,
                        step_type="read",
                        error=str(exc),
                        total_steps=1,
                    ),
                    resource_config_json=build.resource_config_json,
                )
                await _emit_build_event(
                    claim,
                    worker_id,
                    schemas.BuildFailedEvent(
                        build_id=build.build_id,
                        analysis_id=build.analysis_id,
                        emitted_at=service._utcnow(),
                        current_kind=ComputeWorkerRunKind.parse(build.current_kind),
                        current_datasource_id=build.current_datasource_id,
                        tab_id=build.current_tab_id,
                        tab_name=build.current_tab_name,
                        current_output_id=build.current_output_id,
                        current_output_name=build.current_output_name,
                        compute_worker_run_id=None,
                        progress=build.progress,
                        elapsed_ms=elapsed_ms,
                        total_steps=1,
                        tabs_built=0,
                        results=[],
                        duration_ms=elapsed_ms,
                        error=str(exc),
                    ),
                    resource_config_json=build.resource_config_json,
                )
                return
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            refreshed_name = refreshed.name or datasource_id
            await _emit_build_event(
                claim,
                worker_id,
                schemas.BuildStepCompleteEvent(
                    build_id=build.build_id,
                    analysis_id=build.analysis_id,
                    emitted_at=service._utcnow(),
                    current_kind=ComputeWorkerRunKind.parse(build.current_kind),
                    current_datasource_id=build.current_datasource_id,
                    tab_id=build.current_tab_id,
                    tab_name=build.current_tab_name,
                    current_output_id=build.current_output_id,
                    current_output_name=refreshed_name,
                    compute_worker_run_id=None,
                    build_step_index=0,
                    step_index=0,
                    step_id=step_id,
                    step_name=step_name,
                    step_type="read",
                    duration_ms=elapsed_ms,
                    total_steps=1,
                ),
                resource_config_json=build.resource_config_json,
            )
            await _emit_build_event(
                claim,
                worker_id,
                schemas.BuildCompleteEvent(
                    build_id=build.build_id,
                    analysis_id=build.analysis_id,
                    emitted_at=service._utcnow(),
                    current_kind=ComputeWorkerRunKind.parse(build.current_kind),
                    current_datasource_id=build.current_datasource_id,
                    tab_id=build.current_tab_id,
                    tab_name=build.current_tab_name,
                    current_output_id=build.current_output_id,
                    current_output_name=refreshed_name,
                    compute_worker_run_id=None,
                    elapsed_ms=elapsed_ms,
                    total_steps=1,
                    tabs_built=1,
                    results=[
                        schemas.BuildTabResult(
                            tab_id=build.current_tab_id or build.build_id,
                            tab_name=build.current_tab_name or refreshed_name,
                            status=schemas.BuildTabStatus.SUCCESS,
                            output_id=build.current_output_id,
                            output_name=refreshed_name,
                        )
                    ],
                    duration_ms=elapsed_ms,
                ),
                resource_config_json=build.resource_config_json,
            )
            return
        except Exception as exc:
            await _emit_build_event(
                claim,
                worker_id,
                schemas.BuildFailedEvent(
                    build_id=build.build_id,
                    analysis_id=build.analysis_id,
                    emitted_at=service._utcnow(),
                    current_kind=ComputeWorkerRunKind.parse(build.current_kind),
                    current_datasource_id=build.current_datasource_id,
                    tab_id=build.current_tab_id,
                    tab_name=build.current_tab_name,
                    current_output_id=build.current_output_id,
                    current_output_name=build.current_output_name,
                    compute_worker_run_id=None,
                    progress=build.progress,
                    elapsed_ms=build.elapsed_ms,
                    total_steps=1,
                    tabs_built=0,
                    results=[],
                    duration_ms=build.elapsed_ms,
                    error=str(exc),
                ),
                resource_config_json=build.resource_config_json,
            )
            return
    triggered_by = starter.user_id or starter.email or starter.display_name or starter.triggered_by
    build_identity = compute_pb2.ComputeWorkerIdentity(
        scope=enums_pb2.COMPUTE_WORKER_SCOPE_BUILD,
        reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_EXCLUSIVE,
        build_id=build.build_id,
        resource_id=build.build_id,
    )
    while True:
        try:
            async with _admitted_build_work_slot(
                manager,
                build_identity,
                namespace=build.namespace,
                work_semaphore=work_semaphore,
            ):
                await _run_build_task(
                    manager=manager,
                    claim=claim,
                    worker_id=worker_id,
                    build=build,
                    pipeline=pipeline,
                    triggered_by=triggered_by,
                )
            return
        except ComputeWorkerCapacityFull:
            await _wait_after_capacity_race(manager)
            continue


async def _cancel_build_engine(manager: ProcessManager, claim: ClaimedBuildJob) -> None:
    """Stop only the engine owned by a cancelled durable build claim.

    Cancellation can be caused by a lost lease or a cooperative child retire.
    ``shutdown_all`` is process-wide and permanently closes the manager, which
    made one interrupted build poison every later build handled by that child.
    The exclusive build engine's shutdown cancels its active engine job before
    stopping it, while leaving the manager available for the next durable claim.
    """
    identity = compute_pb2.ComputeWorkerIdentity(
        scope=enums_pb2.COMPUTE_WORKER_SCOPE_BUILD,
        reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_EXCLUSIVE,
        build_id=claim.build_id,
        resource_id=claim.build_id,
    )
    with contextlib.suppress(Exception):
        await run_control_in_thread(manager.shutdown_compute_worker, identity, namespace=claim.namespace)


async def run_queued_build_job(
    *,
    manager: ProcessManager,
    worker_id: str,
    claim: ClaimedBuildJob,
    work_semaphore: asyncio.Semaphore | None = None,
) -> None:
    """Run one durable build and clean up only its exclusive engine on cancel."""
    try:
        await _run_queued_build_job(
            manager=manager,
            worker_id=worker_id,
            claim=claim,
            work_semaphore=work_semaphore,
        )
    except asyncio.CancelledError:
        await _cancel_build_engine(manager, claim)
        raise


__all__ = ["run_queued_build_job"]
