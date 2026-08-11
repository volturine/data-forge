from __future__ import annotations

import asyncio
import logging

from builds.build_live import RuntimeBuild
from dataforge_protocol import enums_pb2
from operations.step_converter import analysis_pipeline_to_execution_payload
from runtime import compute_service as service
from runtime.compute_manager import EngineCapacityFull, ProcessManager
from runtime.domain.compute import schemas
from runtime.domain.datasource.models import DataSourceTargetKind
from runtime.domain.engine_runs.schemas import EngineRunKind
from runtime.namespace import reset_namespace, set_namespace_context
from runtime.worker_runtime_client import BuildJobLeaseLost, ClaimedBuildJob, WorkerRuntimeClient, client_from_env

logger = logging.getLogger(__name__)


def worker_runtime_client() -> WorkerRuntimeClient:
    return client_from_env()


async def _emit_build_event(
    claim: ClaimedBuildJob,
    worker_id: str,
    payload: schemas.BuildEvent,
    *,
    resource_config_json: dict[str, object] | None = None,
) -> None:
    token = set_namespace_context(claim.namespace)
    try:
        sequence = await asyncio.to_thread(
            worker_runtime_client().persist_build_event,
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
                    current_kind=EngineRunKind.parse(build.current_kind),
                    current_datasource_id=build.current_datasource_id,
                    tab_id=build.current_tab_id,
                    tab_name=build.current_tab_name,
                    current_output_id=build.current_output_id,
                    current_output_name=build.current_output_name,
                    engine_run_id=build.current_engine_run_id,
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


async def run_queued_build_job(*, manager: ProcessManager, worker_id: str, claim: ClaimedBuildJob) -> None:
    build: RuntimeBuild | None = None
    pipeline: dict | None = None
    starter: schemas.BuildStarter | None = None
    run = await asyncio.to_thread(
        worker_runtime_client().start_build_run,
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
    engine_run_kind = EngineRunKind.parse(build.current_kind)
    is_schedule_ingest = (
        engine_run_kind == EngineRunKind.BUILD
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

            refreshed = await asyncio.to_thread(
                datasource_execution.ingest_datasource_for_schedule,
                worker_runtime_client(),
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
            refreshed_name = refreshed.name or datasource_id
            await _emit_build_event(
                claim,
                worker_id,
                schemas.BuildCompleteEvent(
                    build_id=build.build_id,
                    analysis_id=build.analysis_id,
                    emitted_at=service._utcnow(),
                    current_kind=EngineRunKind.parse(build.current_kind),
                    current_datasource_id=build.current_datasource_id,
                    tab_id=build.current_tab_id,
                    tab_name=build.current_tab_name,
                    current_output_id=build.current_output_id,
                    current_output_name=refreshed_name,
                    engine_run_id=None,
                    elapsed_ms=build.elapsed_ms,
                    total_steps=0,
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
                    duration_ms=build.elapsed_ms,
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
                    current_kind=EngineRunKind.parse(build.current_kind),
                    current_datasource_id=build.current_datasource_id,
                    tab_id=build.current_tab_id,
                    tab_name=build.current_tab_name,
                    current_output_id=build.current_output_id,
                    current_output_name=build.current_output_name,
                    engine_run_id=None,
                    progress=build.progress,
                    elapsed_ms=build.elapsed_ms,
                    total_steps=0,
                    tabs_built=0,
                    results=[],
                    duration_ms=build.elapsed_ms,
                    error=str(exc),
                ),
                resource_config_json=build.resource_config_json,
            )
            return
    triggered_by = starter.user_id or starter.email or starter.display_name or starter.triggered_by
    while True:
        try:
            await _run_build_task(
                manager=manager,
                claim=claim,
                worker_id=worker_id,
                build=build,
                pipeline=pipeline,
                triggered_by=triggered_by,
            )
            return
        except EngineCapacityFull:
            # Park this build worker until a slot frees — do not fail the job.
            await manager.wait_for_capacity()


__all__ = ["run_queued_build_job"]
