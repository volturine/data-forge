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
from runtime.build_events import build_event
from runtime.compute_manager import COMPUTE_WORKER_ADMISSION_PRIORITY_LIFECYCLE, ComputeWorkerCapacityFull, ProcessManager
from runtime.domain.compute import schemas
from runtime.domain.compute_worker_runs.schemas import ComputeWorkerRunKind
from runtime.domain.datasource.models import DataSourceTargetKind
from runtime.executors import run_compute_in_thread, run_control_in_thread, run_shutdown_in_thread
from runtime.namespace import reset_namespace, set_namespace_context
from runtime.worker_runtime_client import BuildJobLeaseLost, ClaimedBuildJob, async_client_from_env, client_from_env

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def _admitted_build_work_slot(
    manager: ProcessManager,
    identity: compute_pb2.ComputeWorkerIdentity,
    *,
    namespace: str,
) -> AsyncIterator[None]:
    # ProcessManager owns the global worker budget. Keep its admission for this
    # exact identity through the operation rather than adding a second gate.
    owns_admission = await manager.await_engine_request_admission(
        identity,
        namespace=namespace,
        priority=COMPUTE_WORKER_ADMISSION_PRIORITY_LIFECYCLE,
    )
    request_reserved = not owns_admission
    job_slot_acquired = False
    try:
        if owns_admission:
            manager.reserve_engine_request(identity, namespace=namespace)
            request_reserved = True
        await manager.await_engine_job_slot(identity, namespace=namespace)
        job_slot_acquired = True
        yield
    finally:
        try:
            if job_slot_acquired:
                manager.release_engine_job_slot(identity, namespace=namespace)
        finally:
            try:
                if request_reserved:
                    manager.release_engine_request(identity, namespace=namespace)
            finally:
                await run_control_in_thread(
                    manager.release_spawn_admission,
                    identity,
                    namespace=namespace,
                    owned=owns_admission,
                )


async def _emit_build_event(
    claim: ClaimedBuildJob,
    worker_id: str,
    payload: schemas.BuildEvent,
    *,
    build: RuntimeBuild,
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
            event=payload,
            resource_config_json=build.resource_config_json,
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
) -> None:
    token = set_namespace_context(build.namespace)
    try:
        await service.run_analysis_build_stream(
            manager=manager,
            pipeline=pipeline,
            build=build,
            emitter=lambda payload: _emit_build_event(claim, worker_id, payload, build=build),
            publication_claim=claim,
            worker_id=worker_id,
        )
    except BuildJobLeaseLost:
        raise
    except Exception as exc:
        logger.error("Active build task error: %s", exc, exc_info=True)
        await _emit_build_event(
            claim,
            worker_id,
            build_event(
                build,
                build.analysis_id,
                {
                    "type": schemas.BuildEventType.FAILED,
                    "tab_id": build.current_tab_id,
                    "tab_name": build.current_tab_name,
                    "progress": 0.0,
                    "elapsed_ms": 0,
                    "total_steps": build.total_steps,
                    "tabs_built": 0,
                    "results": [],
                    "duration_ms": 0,
                    "error": "Build failed due to an internal error",
                },
            ),
            build=build,
        )
    finally:
        reset_namespace(token)


async def _run_queued_build_job(
    *,
    manager: ProcessManager,
    worker_id: str,
    claim: ClaimedBuildJob,
) -> None:
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
        current_kind=run.current_kind,
        current_datasource_id=run.current_datasource_id,
        current_tab_id=run.current_tab_id,
        current_tab_name=run.current_tab_name,
        current_output_id=run.current_output_id,
        current_output_name=run.current_output_name,
    )
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
                build_event(
                    build,
                    build.analysis_id,
                    {
                        "type": schemas.BuildEventType.STEP_START,
                        "tab_id": build.current_tab_id,
                        "tab_name": build.current_tab_name,
                        "build_step_index": 0,
                        "step_index": 0,
                        "step_id": step_id,
                        "step_name": step_name,
                        "step_type": "read",
                        "total_steps": 1,
                    },
                ),
                build=build,
            )
            started = time.perf_counter()
            try:
                async with _admitted_build_work_slot(manager, datasource_identity, namespace=build.namespace):
                    refreshed = await run_compute_in_thread(
                        datasource_execution.ingest_datasource_for_schedule,
                        client_from_env(),
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
                    build_event(
                        build,
                        build.analysis_id,
                        {
                            "type": schemas.BuildEventType.STEP_FAILED,
                            "tab_id": build.current_tab_id,
                            "tab_name": build.current_tab_name,
                            "build_step_index": 0,
                            "step_index": 0,
                            "step_id": step_id,
                            "step_name": step_name,
                            "step_type": "read",
                            "error": str(exc),
                            "total_steps": 1,
                        },
                    ),
                    build=build,
                )
                await _emit_build_event(
                    claim,
                    worker_id,
                    build_event(
                        build,
                        build.analysis_id,
                        {
                            "type": schemas.BuildEventType.FAILED,
                            "tab_id": build.current_tab_id,
                            "tab_name": build.current_tab_name,
                            "progress": 0.0,
                            "elapsed_ms": elapsed_ms,
                            "total_steps": 1,
                            "tabs_built": 0,
                            "results": [],
                            "duration_ms": elapsed_ms,
                            "error": str(exc),
                        },
                    ),
                    build=build,
                )
                return
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            refreshed_name = refreshed.name or datasource_id
            await _emit_build_event(
                claim,
                worker_id,
                build_event(
                    build,
                    build.analysis_id,
                    {
                        "type": schemas.BuildEventType.STEP_COMPLETE,
                        "tab_id": build.current_tab_id,
                        "tab_name": build.current_tab_name,
                        "current_output_name": refreshed_name,
                        "build_step_index": 0,
                        "step_index": 0,
                        "step_id": step_id,
                        "step_name": step_name,
                        "step_type": "read",
                        "duration_ms": elapsed_ms,
                        "total_steps": 1,
                    },
                ),
                build=build,
            )
            await _emit_build_event(
                claim,
                worker_id,
                build_event(
                    build,
                    build.analysis_id,
                    {
                        "type": schemas.BuildEventType.COMPLETE,
                        "tab_id": build.current_tab_id,
                        "tab_name": build.current_tab_name,
                        "current_output_name": refreshed_name,
                        "elapsed_ms": elapsed_ms,
                        "total_steps": 1,
                        "tabs_built": 1,
                        "results": [
                            schemas.BuildTabResult(
                                tab_id=build.current_tab_id or build.build_id,
                                tab_name=build.current_tab_name or refreshed_name,
                                status=schemas.BuildTabStatus.SUCCESS,
                                output_id=build.current_output_id,
                                output_name=refreshed_name,
                            )
                        ],
                        "duration_ms": elapsed_ms,
                    },
                ),
                build=build,
            )
            return
        except BuildJobLeaseLost:
            raise
        except Exception as exc:
            await _emit_build_event(
                claim,
                worker_id,
                build_event(
                    build,
                    build.analysis_id,
                    {
                        "type": schemas.BuildEventType.FAILED,
                        "tab_id": build.current_tab_id,
                        "tab_name": build.current_tab_name,
                        "progress": 0.0,
                        "elapsed_ms": 0,
                        "total_steps": 1,
                        "tabs_built": 0,
                        "results": [],
                        "duration_ms": 0,
                        "error": str(exc),
                    },
                ),
                build=build,
            )
            return
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
            ):
                await _run_build_task(
                    manager=manager,
                    claim=claim,
                    worker_id=worker_id,
                    build=build,
                    pipeline=pipeline,
                )
            return
        except ComputeWorkerCapacityFull:
            # Rejoin bounded capacity admission after a build loses a slot race.
            await manager.wait_for_capacity(timeout_seconds=2.0)
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
        await run_shutdown_in_thread(manager.shutdown_compute_worker, identity, namespace=claim.namespace)


async def run_queued_build_job(
    *,
    manager: ProcessManager,
    worker_id: str,
    claim: ClaimedBuildJob,
) -> None:
    """Run one durable build and clean up only its exclusive engine on cancel."""
    try:
        await _run_queued_build_job(
            manager=manager,
            worker_id=worker_id,
            claim=claim,
        )
    except asyncio.CancelledError:
        await _cancel_build_engine(manager, claim)
        raise


__all__ = ["run_queued_build_job"]
