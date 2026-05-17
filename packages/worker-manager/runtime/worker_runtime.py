from __future__ import annotations

import asyncio
import logging
import os
import socket
import threading
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from contracts.build_runs.models import BuildRunStatus
from contracts.runtime import ipc as runtime_ipc
from contracts.runtime.ipc import RuntimeListenerKind, RuntimePayloadKind
from contracts.runtime_workers.models import RuntimeWorkerKind
from contracts.scheduler.models import Schedule
from core import (
    build_jobs_service as build_job_service,
)
from core import (
    build_runs_service as build_run_service,
)
from core import (
    runtime_workers_service as runtime_worker_service,
)
from core.database import run_db, run_settings_db
from core.namespace import reset_namespace, set_namespace_context
from core.namespaces_service import list_runtime_namespaces

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaimedJob:
    id: str
    build_id: str
    namespace: str


async def _wait_until_stopped(stop_event: asyncio.Event, delay_seconds: float) -> bool:
    stop_task = asyncio.create_task(stop_event.wait())
    delay_task = asyncio.create_task(asyncio.sleep(delay_seconds))
    done, pending = await asyncio.wait({stop_task, delay_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    return stop_task in done


async def _wait_for_build_job_signal(stop_event: asyncio.Event, wake_event: asyncio.Event) -> None:
    stop_task = asyncio.create_task(stop_event.wait())
    wake_task = asyncio.create_task(wake_event.wait())
    done, pending = await asyncio.wait({stop_task, wake_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    if wake_task in done:
        wake_event.clear()


async def build_worker_loop(
    stop_event: asyncio.Event,
    worker_id: str,
    run_job: Callable[[str], Awaitable[None]],
    *,
    capacity: int = 1,
    heartbeat_seconds: float = 5.0,
    idle_exit_seconds: float | None = None,
    max_jobs: int | None = None,
) -> None:
    _register_worker(worker_id=worker_id, capacity=capacity)
    heartbeat_stop = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop_sync,
        kwargs={
            "stop_signal": heartbeat_stop,
            "worker_id": worker_id,
            "heartbeat_seconds": heartbeat_seconds,
        },
        daemon=True,
    )
    heartbeat_thread.start()
    ipc_server = await runtime_ipc.start_api_server(listener=RuntimeListenerKind.JOB)
    if ipc_server is None:
        raise RuntimeError("Build worker requires runtime IPC listener")
    wake_event = asyncio.Event()

    async def handle_runtime_payload(payload: dict[str, object]) -> None:
        if RuntimePayloadKind.from_payload(payload) == RuntimePayloadKind.JOB:
            wake_event.set()

    ipc_task = asyncio.create_task(runtime_ipc.serve_api_notifications(ipc_server, stop_event, handle_runtime_payload))
    handled_jobs = 0
    try:
        while not stop_event.is_set():
            try:
                handled = await _run_once(worker_id=worker_id, run_job=run_job)
                if handled:
                    handled_jobs += 1
                    if max_jobs is not None and handled_jobs >= max_jobs:
                        return
                    continue
                if idle_exit_seconds is not None:
                    if await _wait_until_stopped(stop_event, idle_exit_seconds):
                        continue
                    return
                await _wait_for_build_job_signal(stop_event, wake_event)
            except Exception as exc:
                logger.error("Build worker loop error: %s", exc, exc_info=True)
                await asyncio.sleep(0.1)
    finally:
        stop_event.set()
        await asyncio.gather(ipc_task, return_exceptions=True)
        await runtime_ipc.stop_api_server(ipc_server, listener=RuntimeListenerKind.JOB)
        heartbeat_stop.set()
        heartbeat_thread.join()
        _release_worker_jobs(worker_id)
        _stop_worker(worker_id)


async def _run_once(
    *,
    worker_id: str,
    run_job: Callable[[str], Awaitable[None]],
) -> bool:
    job = next_job(worker_id)
    if job is None:
        return False

    _heartbeat_worker(worker_id=worker_id, active_jobs=1)
    token = set_namespace_context(job.namespace)
    try:
        await run_job(job.build_id)
    except Exception as exc:
        logger.error("Build job %s failed: %s", job.build_id, exc, exc_info=True)
        error = str(exc)

        def _mark_failed(session):
            return build_job_service.mark_job_failed(session, job.id, error=error)

        run_db(_mark_failed)
        raise
    finally:
        _heartbeat_worker(worker_id=worker_id, active_jobs=0)
        reset_namespace(token)

    def _finalize(session):
        run = build_run_service.get_build_run(session, job.build_id)
        if run is None:
            return build_job_service.mark_job_failed(session, job.id, error="Build run missing")
        if run.status == BuildRunStatus.CANCELLED:
            result = build_job_service.mark_job_cancelled(session, job.id)
        elif run.status == BuildRunStatus.COMPLETED:
            result = build_job_service.mark_job_completed(session, job.id)
        elif run.status in {BuildRunStatus.FAILED, BuildRunStatus.ORPHANED}:
            result = build_job_service.mark_job_failed(session, job.id, error=run.error_message)
        else:
            result = build_job_service.mark_job_failed(session, job.id, error=f"Unexpected build status: {run.status.value}")
        _reconcile_schedule_run(session, build_id=job.build_id)
        return result

    run_db(_finalize)
    return True


def next_job(worker_id: str) -> ClaimedJob | None:
    reclaimable_owner_ids = run_settings_db(
        runtime_worker_service.reclaimable_worker_ids,
        kind=RuntimeWorkerKind.BUILD_WORKER,
    )
    for namespace in runtime_namespaces():
        token = set_namespace_context(namespace)
        try:

            def _claim(session):
                job = build_job_service.claim_next_job(
                    session,
                    worker_id=worker_id,
                    reclaimable_owner_ids=reclaimable_owner_ids,
                )
                if job is None:
                    return None
                return ClaimedJob(id=job.id, build_id=job.build_id, namespace=job.namespace)

            job = run_db(_claim)
        finally:
            reset_namespace(token)
        if job is not None:
            return job
    return None


def runtime_namespaces() -> list[str]:
    return run_settings_db(list_runtime_namespaces)


def _reconcile_schedule_run(session, *, build_id: str) -> None:
    run = build_run_service.get_build_run(session, build_id)
    if run is None or run.schedule_id is None:
        return
    if run.status not in {
        BuildRunStatus.COMPLETED,
        BuildRunStatus.FAILED,
        BuildRunStatus.CANCELLED,
        BuildRunStatus.ORPHANED,
    }:
        return
    schedule = session.get(Schedule, run.schedule_id)
    if schedule is None:
        return
    completed = run.completed_at or run.updated_at
    stamp = completed.replace(tzinfo=None) if completed.tzinfo is not None else completed
    schedule.lease_owner = None
    schedule.lease_expires_at = None
    if run.status == BuildRunStatus.COMPLETED:
        schedule.last_run = stamp
        schedule.last_success_at = stamp
        schedule.last_successful_build_id = run.id
    else:
        schedule.last_failure_at = stamp
    session.add(schedule)


def _register_worker(*, worker_id: str, capacity: int) -> None:
    def _register(session):
        return runtime_worker_service.register_worker(
            session,
            worker_id=worker_id,
            kind=RuntimeWorkerKind.BUILD_WORKER,
            hostname=socket.gethostname(),
            pid=os.getpid(),
            capacity=capacity,
        )

    run_settings_db(_register)


def _heartbeat_worker(*, worker_id: str, active_jobs: int | None = None) -> None:
    def _heartbeat(session):
        return runtime_worker_service.heartbeat_worker(session, worker_id=worker_id, active_jobs=active_jobs)

    run_settings_db(_heartbeat)


def _stop_worker(worker_id: str) -> None:
    def _stop(session):
        return runtime_worker_service.mark_worker_stopped(session, worker_id=worker_id)

    run_settings_db(_stop)


def _release_worker_jobs(worker_id: str) -> None:
    for namespace in runtime_namespaces():
        token = set_namespace_context(namespace)
        try:

            def _release(session):
                return build_job_service.release_worker_jobs(session, worker_id=worker_id)

            run_db(_release)
        finally:
            reset_namespace(token)


def _heartbeat_loop_sync(*, stop_signal: threading.Event, worker_id: str, heartbeat_seconds: float) -> None:
    while not stop_signal.wait(heartbeat_seconds):
        _heartbeat_worker(worker_id=worker_id)


def worker_id() -> str:
    return f"local-worker:{uuid.uuid4()}"
