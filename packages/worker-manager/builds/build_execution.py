from __future__ import annotations

import asyncio
import logging

from contracts.compute import schemas
from contracts.datasource.models import DataSourceTargetKind
from contracts.engine_runs.schemas import EngineRunKind
from core import build_event_service
from core import build_runs_service as build_run_service
from core.database import get_db
from core.namespace import reset_namespace, set_namespace_context

from builds.build_live import ActiveBuild
from runtime import compute_service as service
from runtime.compute_manager import ProcessManager

logger = logging.getLogger(__name__)


async def _emit_active_build_event(
    namespace: str,
    build_id: str,
    payload: schemas.BuildEvent,
    *,
    resource_config_json: dict[str, object] | None = None,
) -> None:
    token = set_namespace_context(namespace)
    session_gen = get_db()
    session = next(session_gen)
    try:
        await build_event_service.persist_build_event(
            session,
            namespace=namespace,
            build_id=build_id,
            event=payload,
            resource_config_json=resource_config_json,
        )
    finally:
        session.close()
        session_gen.close()
        reset_namespace(token)


async def _run_active_build_task(
    *,
    manager: ProcessManager,
    build: ActiveBuild,
    pipeline: dict,
    triggered_by: str | None,
) -> None:
    token = set_namespace_context(build.namespace)
    session_gen = None
    session = None
    try:
        session_gen = get_db()
        session = next(session_gen)
        await service.run_analysis_build_stream(
            session=session,
            manager=manager,
            pipeline=pipeline,
            build=build,
            emitter=lambda payload: _emit_active_build_event(
                build.namespace,
                build.build_id,
                payload,
                resource_config_json=build.resource_config_json,
            ),
            triggered_by=triggered_by,
        )
    except Exception as exc:
        logger.error("Active build task error: %s", exc, exc_info=True)
        if build.status == schemas.ActiveBuildStatus.RUNNING:
            await _emit_active_build_event(
                build.namespace,
                build.build_id,
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
        if session is not None:
            session.close()
        if session_gen is not None:
            session_gen.close()
        reset_namespace(token)


async def _run_queued_build_job(*, manager: ProcessManager, build_id: str) -> None:
    session_gen = get_db()
    session = next(session_gen)
    build: ActiveBuild | None = None
    pipeline: dict | None = None
    starter: schemas.BuildStarter | None = None
    request_payload: schemas.BuildRequest | None = None
    try:
        run = build_run_service.get_build_run(session, build_id)
        if run is None:
            return
        marked = build_run_service.mark_build_running(session, build_id, now=service._utcnow())
        if marked is None or marked.status != build_run_service.BuildRunStatus.RUNNING:
            return
        request_payload = schemas.BuildRequest.model_validate(run.request_json)
        pipeline = request_payload.pipeline_payload()
        starter = schemas.BuildStarter.model_validate(run.starter_json)
        build = ActiveBuild(
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
            status=schemas.ActiveBuildStatus.RUNNING,
        )
    finally:
        session.close()
        session_gen.close()
    if build is None or pipeline is None or starter is None or request_payload is None:
        return
    await build_event_service.publish_build_notification(build.namespace, build_id, latest_sequence=0)
    current_kind = build.current_kind or ""
    engine_run_kind = EngineRunKind.parse(build.current_kind)
    is_schedule_build = engine_run_kind == EngineRunKind.BUILD and starter.triggered_by == "schedule"
    if current_kind == DataSourceTargetKind.RAW.value or is_schedule_build:
        datasource_id = build.current_datasource_id
        if datasource_id is None:
            raise ValueError(f"Queued schedule build {build.build_id} missing datasource id")
        session_gen = get_db()
        session = next(session_gen)
        try:
            try:
                from datasources import datasource_service

                if current_kind == DataSourceTargetKind.RAW.value:
                    refreshed = await asyncio.to_thread(
                        datasource_service.refresh_external_datasource,
                        session,
                        datasource_id,
                    )
                else:
                    refreshed = await asyncio.to_thread(
                        datasource_service.refresh_datasource_for_schedule,
                        session,
                        datasource_id,
                    )
                await _emit_active_build_event(
                    build.namespace,
                    build.build_id,
                    schemas.BuildCompleteEvent(
                        build_id=build.build_id,
                        analysis_id=build.analysis_id,
                        emitted_at=service._utcnow(),
                        current_kind=EngineRunKind.parse(build.current_kind),
                        current_datasource_id=build.current_datasource_id,
                        tab_id=build.current_tab_id,
                        tab_name=build.current_tab_name,
                        current_output_id=build.current_output_id,
                        current_output_name=refreshed.name,
                        engine_run_id=None,
                        elapsed_ms=build.elapsed_ms,
                        total_steps=0,
                        tabs_built=1,
                        results=[
                            schemas.BuildTabResult(
                                tab_id=build.current_tab_id or build.build_id,
                                tab_name=build.current_tab_name or refreshed.name,
                                status=schemas.BuildTabStatus.SUCCESS,
                                output_id=build.current_output_id,
                                output_name=refreshed.name,
                            )
                        ],
                        duration_ms=build.elapsed_ms,
                    ),
                    resource_config_json=build.resource_config_json,
                )
                return
            except Exception as exc:
                await _emit_active_build_event(
                    build.namespace,
                    build.build_id,
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
        finally:
            session.close()
            session_gen.close()
    await _run_active_build_task(
        manager=manager,
        build=build,
        pipeline=pipeline,
        triggered_by=starter.user_id or starter.email or starter.display_name or starter.triggered_by,
    )


__all__ = ["_run_queued_build_job"]
