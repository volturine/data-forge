from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import threading
import uuid
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from runtime.compute_manager import ProcessManager
from runtime.compute_request_runtime import (
    ACTIVE_REQUEST_KINDS,
    ENGINE_SHUTDOWN_REQUEST_KINDS,
    compute_request_claim_worker_count,
    compute_request_loop,
    compute_request_worker_count,
)
from runtime.config import settings
from runtime.datasource_delete_runtime import datasource_delete_loop
from runtime.dispatcher_health import DispatcherHealth
from runtime.docker_engine import reconcile_deployment_containers, validate_engine_runtime_readiness
from runtime.domain.runtime_workers.models import RuntimeWorkerKind
from runtime.engine_notifications import create_snapshot_notifier
from runtime.executors import run_control_in_thread
from runtime.logging import configure_logging
from runtime.namespace import get_namespace, reset_namespace, set_namespace_context
from runtime.runtime_ipc import serve_runtime_notifications, start_runtime_listener, stop_runtime_listener
from runtime.runtime_notifications import handle_runtime_payload
from runtime.storage_cleanup_runtime import storage_cleanup_loop
from runtime.worker_runtime import (
    NamespaceRecovery,
    RuntimeNamespaceDirectory,
    build_worker_loop,
)
from runtime.worker_runtime_client import (
    BackendWorkerRpcError,
    ClaimedBuildJob,
    WorkerRuntimeClient,
    client_from_env,
    run_worker_heartbeat_loop,
    shutdown_compute_request_lease_batcher,
)
from worker_grpc.data_plane_server import ThreadedDataPlaneServer, start_data_plane_grpc_server_in_thread

logger = logging.getLogger(__name__)
_MIN_RUNTIME_RECOVERY_SECONDS = 5.0
# Hot-path work uses explicit compute/control pools. Keep asyncio's fallback
# executor small for startup, shutdown, and occasional lifecycle glue.
_DEFAULT_EXECUTOR_WORKERS = 4
_SHUTDOWN_CONTROL_CONCURRENCY = 4
_COORDINATOR_GENERATION_POLL_SECONDS = 5.0
_DISPATCH_LANES = ("compute-active", "compute-shutdown", "build", "datasource-delete", "outbox-cleanup")


def worker_runtime_client() -> WorkerRuntimeClient:
    return client_from_env()


def coordinator_id() -> str:
    return f"runtime-coordinator:{uuid.uuid4()}"


def _manager_heartbeat_loop(
    stop_signal: threading.Event,
    worker_id: str,
    *,
    client: WorkerRuntimeClient,
    health: DispatcherHealth,
    on_reconnected: Callable[[], None] | None = None,
    heartbeat_seconds: float = 5.0,
) -> None:
    run_worker_heartbeat_loop(
        client=client,
        stop_signal=stop_signal,
        worker_id=worker_id,
        kind=RuntimeWorkerKind.COORDINATOR.value,
        hostname=os.uname().nodename,
        pid=os.getpid(),
        capacity=settings.compute_workers,
        heartbeat_seconds=heartbeat_seconds,
        on_reconnected=on_reconnected,
        on_registration_changed=health.registration_changed,
    )


def _configure_blocking_executor(*, max_workers: int, thread_name_prefix: str) -> None:
    """Bound fallback ``asyncio.to_thread`` work outside the hot path."""
    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=thread_name_prefix))


async def _supervise_runtime_loop(
    stop_event: asyncio.Event,
    name: str,
    run: Callable[[], Awaitable[None]],
    *,
    health: DispatcherHealth,
) -> None:
    delay = 0.25
    while not stop_event.is_set():
        try:
            await run()
            if stop_event.is_set():
                return
            raise RuntimeError(f"Runtime loop {name} exited unexpectedly")
        except asyncio.CancelledError:
            health.failed(name)
            raise
        except Exception:
            health.failed(name)
            logger.exception("Runtime loop %s failed; restarting in %.2fs", name, delay)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
                return
            except TimeoutError:
                delay = min(delay * 2, 5.0)


async def run_runtime_coordinator(
    *,
    stop_event: asyncio.Event | None = None,
    coordinator_generation: int | None = None,
    coordinator_guard: Callable[[], None] | None = None,
) -> None:
    worker_id = coordinator_id()
    health = DispatcherHealth(
        worker_id,
        lanes=_DISPATCH_LANES,
        max_age_seconds=max(90.0, float(settings.runtime_reconciliation_poll_interval_seconds) + 60.0),
    )
    async with health.serve():
        await _run_runtime_coordinator(
            stop_event=stop_event,
            coordinator_generation=coordinator_generation,
            coordinator_guard=coordinator_guard,
            worker_id=worker_id,
            health=health,
        )


async def _run_runtime_coordinator(
    *,
    stop_event: asyncio.Event | None,
    coordinator_generation: int | None,
    coordinator_guard: Callable[[], None] | None,
    worker_id: str,
    health: DispatcherHealth,
) -> None:
    configure_logging()
    _configure_blocking_executor(max_workers=_DEFAULT_EXECUTOR_WORKERS, thread_name_prefix="runtime-default")
    logger.info("Starting runtime coordinator...")
    await run_control_in_thread(validate_engine_runtime_readiness)
    if coordinator_generation is not None:
        os.environ["RUNTIME_COORDINATOR_GENERATION"] = str(coordinator_generation)
    removed = await run_control_in_thread(
        reconcile_deployment_containers,
        coordinator_generation=coordinator_generation,
        coordinator_guard=coordinator_guard,
    )
    if removed:
        logger.warning("Removed %s orphaned engine container(s) during startup", removed)
    local_stop = stop_event or asyncio.Event()
    client = worker_runtime_client()
    recovery_poll_seconds = max(
        _MIN_RUNTIME_RECOVERY_SECONDS,
        float(settings.runtime_reconciliation_poll_interval_seconds),
    )
    # Each queue only recovers namespaces with work of its own kind. Without
    # this filter, every idle build lane probes the build queue whenever any
    # preview is pending, multiplying control-plane claims by compute capacity.
    compute_namespace_directory = RuntimeNamespaceDirectory(
        client,
        refresh_seconds=recovery_poll_seconds,
        work_kinds=("compute",),
    )
    build_namespace_directory = RuntimeNamespaceDirectory(
        client,
        refresh_seconds=recovery_poll_seconds,
        work_kinds=("build",),
    )
    datasource_delete_namespace_directory = RuntimeNamespaceDirectory(
        client,
        refresh_seconds=recovery_poll_seconds,
        work_kinds=("datasource_delete",),
    )
    storage_cleanup_namespace_directory = RuntimeNamespaceDirectory(
        client,
        refresh_seconds=recovery_poll_seconds,
        work_kinds=("storage_cleanup",),
    )
    compute_request_recovery = NamespaceRecovery(
        client.reconcile_expired_compute_requests,
        work_name="exhausted compute requests",
        interval_seconds=recovery_poll_seconds,
    )
    build_job_recovery = NamespaceRecovery(
        client.reconcile_expired_build_jobs,
        work_name="expired build jobs",
        interval_seconds=recovery_poll_seconds,
    )
    snapshot_notifier = create_snapshot_notifier(
        namespace_provider=get_namespace,
        worker_id=worker_id,
    )
    manager = ProcessManager(
        on_snapshot=snapshot_notifier,
        supervisor_id=worker_id,
        # This is the only manager for the application-wide runtime. Parked
        # warm workers are a bounded unassigned reserve; assigned workers still
        # acquire from the same advisory-lock slot set.
        warm_worker_target=settings.compute_warm_workers,
        coordinator_generation=coordinator_generation,
        coordinator_guard=coordinator_guard,
    )
    runtime_listener = None
    runtime_listener_task: asyncio.Task[None] | None = None
    data_plane_server: ThreadedDataPlaneServer | None = None
    try:
        warm_worker_timeout = max(float(settings.engine_start_timeout_seconds) * 4, 120.0)
        warm_workers_ready = await run_control_in_thread(
            manager.wait_for_warm_workers_ready,
            timeout_seconds=warm_worker_timeout,
        )
        if not warm_workers_ready:
            logger.warning(
                "Warm compute worker reserve was not ready after %.1fs; starting manager with %s worker(s)",
                warm_worker_timeout,
                manager.warm_worker_count,
            )
        if local_stop.is_set():
            await run_control_in_thread(manager.shutdown_all)
            await run_control_in_thread(snapshot_notifier.close)
            return
        data_plane_server = start_data_plane_grpc_server_in_thread()
        try:
            runtime_listener = await start_runtime_listener()
            runtime_listener_task = asyncio.create_task(serve_runtime_notifications(runtime_listener, local_stop, handle_runtime_payload))
        except Exception as exc:
            # Polling remains a recovery path if Postgres LISTEN is unavailable
            # during startup. Normal operation should be notification-driven.
            logger.warning("Worker runtime notifications unavailable; using recovery polling: %s", exc)
        await run_control_in_thread(
            client.register_worker,
            worker_id=worker_id,
            kind=RuntimeWorkerKind.COORDINATOR.value,
            hostname=os.uname().nodename,
            pid=os.getpid(),
            capacity=settings.compute_workers,
        )
        health.registered()
    except BaseException:
        if runtime_listener_task is not None:
            runtime_listener_task.cancel()
            await asyncio.gather(runtime_listener_task, return_exceptions=True)
        await stop_runtime_listener(runtime_listener)
        if data_plane_server is not None:
            with contextlib.suppress(Exception):
                await data_plane_server.stop(grace=1.0)
        await run_control_in_thread(manager.shutdown_all)
        await run_control_in_thread(snapshot_notifier.close)
        raise

    assert data_plane_server is not None
    heartbeat_stop = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_manager_heartbeat_loop,
        kwargs={
            "client": client,
            "stop_signal": heartbeat_stop,
            "worker_id": worker_id,
            "on_reconnected": manager.resynchronize_snapshots,
            "health": health,
        },
        daemon=True,
    )
    heartbeat_thread.start()
    request_worker_count = compute_request_worker_count()
    # Keep claim transactions below one shared control-plane budget. A browser
    # burst is durable queue work, not a reason to create one claim per tab.
    # Reserve one bounded claim lane for cleanup. Preview/build claim bursts
    # must not prevent shutdown requests from freeing engine capacity.
    active_claim_semaphore = asyncio.Semaphore(compute_request_claim_worker_count())
    shutdown_claim_semaphore = asyncio.Semaphore(1)
    # One application-wide work budget covers previews, datasource jobs,
    # lifecycle work, and builds. Every lane can use the full budget when
    # needed; the shared gate prevents idle queue reservations and overcommit.
    compute_work_semaphore = asyncio.Semaphore(request_worker_count)
    request_lanes = [
        (ACTIVE_REQUEST_KINDS, request_worker_count, active_claim_semaphore, compute_work_semaphore),
        (
            ENGINE_SHUTDOWN_REQUEST_KINDS,
            min(request_worker_count, _SHUTDOWN_CONTROL_CONCURRENCY),
            shutdown_claim_semaphore,
            None,
        ),
    ]
    request_tasks = []
    for lane, (allowed_kinds, max_concurrency, claim_semaphore, work_semaphore) in enumerate(request_lanes):
        lane_name = _DISPATCH_LANES[lane]

        async def run_request_lane(
            allowed_kinds=allowed_kinds,
            max_concurrency=max_concurrency,
            claim_semaphore=claim_semaphore,
            work_semaphore=work_semaphore,
            lane_name=lane_name,
        ) -> None:
            await compute_request_loop(
                local_stop,
                worker_id=worker_id,
                manager=manager,
                allowed_kinds=allowed_kinds,
                claim_semaphore=claim_semaphore,
                poll_for_work=True,
                max_concurrency=max_concurrency,
                work_semaphore=work_semaphore,
                namespace_directory=compute_namespace_directory,
                recovery=compute_request_recovery,
                on_progress=partial(health.progress, lane_name),
            )

        request_tasks.append(
            asyncio.create_task(
                _supervise_runtime_loop(local_stop, lane_name, run_request_lane, health=health),
                name=f"compute-request-supervisor-{lane}",
            )
        )
    datasource_delete_task = asyncio.create_task(
        _supervise_runtime_loop(
            local_stop,
            "datasource-delete",
            lambda: datasource_delete_loop(
                local_stop,
                manager=manager,
                namespace_directory=datasource_delete_namespace_directory,
                on_progress=partial(health.progress, "datasource-delete"),
            ),
            health=health,
        )
    )
    storage_cleanup_task = asyncio.create_task(
        _supervise_runtime_loop(
            local_stop,
            "outbox-cleanup",
            lambda: storage_cleanup_loop(
                local_stop,
                manager=manager,
                namespace_directory=storage_cleanup_namespace_directory,
                on_progress=partial(health.progress, "outbox-cleanup"),
            ),
            health=health,
        ),
        name="storage-cleanup-dispatcher",
    )
    from builds.build_execution import run_queued_build_job

    # One dispatcher claims build jobs serially, then runs them concurrently
    # up to the same application-wide compute budget as preview work.
    async def run_build(claim: ClaimedBuildJob) -> None:
        token = set_namespace_context(claim.namespace)
        try:
            await run_queued_build_job(
                manager=manager,
                worker_id=worker_id,
                claim=claim,
                work_semaphore=compute_work_semaphore,
            )
        finally:
            reset_namespace(token)

    async def run_build_dispatcher() -> None:
        await build_worker_loop(
            local_stop,
            worker_id,
            run_build,
            client=client,
            capacity=request_worker_count,
            heartbeat_seconds=float(settings.engine_heartbeat_interval_seconds),
            poll_interval_seconds=recovery_poll_seconds,
            on_reconnected=manager.resynchronize_snapshots,
            namespace_directory=build_namespace_directory,
            recovery=build_job_recovery,
            announce_worker=False,
            on_progress=partial(health.progress, "build"),
        )

    build_tasks = [
        asyncio.create_task(
            _supervise_runtime_loop(local_stop, "build", run_build_dispatcher, health=health),
            name="build-dispatcher",
        )
    ]

    try:
        await local_stop.wait()
    finally:
        health.stopped()
        local_stop.set()
        heartbeat_stop.set()
        await run_control_in_thread(heartbeat_thread.join)
        # Closing the manager first rejects parked capacity admissions. Waiting
        # for request tasks before this point can deadlock shutdown forever.
        await run_control_in_thread(manager.shutdown_all)
        await asyncio.gather(*request_tasks, datasource_delete_task, storage_cleanup_task, *build_tasks, return_exceptions=True)
        await run_control_in_thread(shutdown_compute_request_lease_batcher)
        if runtime_listener_task is not None:
            await asyncio.gather(runtime_listener_task, return_exceptions=True)
        await stop_runtime_listener(runtime_listener)
        await data_plane_server.stop(grace=1.0)
        await run_control_in_thread(snapshot_notifier.close)
        with contextlib.suppress(Exception):
            await run_control_in_thread(client.stop_worker, worker_id=worker_id, timeout_seconds=2.0)
    logger.info("Runtime coordinator shutdown complete generation=%s", coordinator_generation)


def install_stop_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def _stop() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _stop)


async def _wait_for_coordinator_generation(stop_event: asyncio.Event, client: WorkerRuntimeClient) -> int | None:
    retry_seconds = 0.25
    while not stop_event.is_set():
        try:
            return await run_control_in_thread(client.get_coordinator_generation)
        except BackendWorkerRpcError as exc:
            if exc.error_code not in {"UNAVAILABLE", "DEADLINE_EXCEEDED"}:
                raise
            logger.info("Runtime coordinator unavailable; worker manager waiting to connect: %s", exc.error)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=retry_seconds)
        except TimeoutError:
            retry_seconds = min(retry_seconds * 2, 2.0)
    return None


async def _watch_coordinator_generation(
    process_stop_event: asyncio.Event,
    generation_stop_event: asyncio.Event,
    client: WorkerRuntimeClient,
    generation: int,
) -> None:
    while not process_stop_event.is_set():
        try:
            active_generation = await run_control_in_thread(client.get_coordinator_generation)
        except BackendWorkerRpcError as exc:
            if exc.error_code not in {"UNAVAILABLE", "DEADLINE_EXCEEDED"}:
                logger.warning("Worker coordinator generation check failed permanently: %s", exc.error)
                generation_stop_event.set()
                return
            logger.info("Runtime coordinator temporarily unavailable; preserving worker state generation=%s", generation)
        else:
            if active_generation != generation:
                logger.info("Runtime coordinator generation changed old=%s new=%s", generation, active_generation)
                generation_stop_event.set()
                return

        try:
            await asyncio.wait_for(process_stop_event.wait(), timeout=_COORDINATOR_GENERATION_POLL_SECONDS)
        except TimeoutError:
            continue


async def _run_worker_generation(
    process_stop_event: asyncio.Event,
    client: WorkerRuntimeClient,
    generation: int,
) -> None:
    generation_stop_event = asyncio.Event()
    runtime_task = asyncio.create_task(
        run_runtime_coordinator(
            stop_event=generation_stop_event,
            coordinator_generation=generation,
            coordinator_guard=lambda: client.assert_coordinator_generation(generation),
        ),
        name=f"worker-runtime-generation-{generation}",
    )
    monitor_task = asyncio.create_task(
        _watch_coordinator_generation(process_stop_event, generation_stop_event, client, generation),
        name=f"worker-generation-monitor-{generation}",
    )
    process_stop_task = asyncio.create_task(process_stop_event.wait(), name="worker-process-stop")
    primary_error: BaseException | None = None
    try:
        done, _pending = await asyncio.wait(
            {runtime_task, monitor_task, process_stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if process_stop_task in done or monitor_task in done:
            generation_stop_event.set()
        if monitor_task in done:
            await monitor_task
        await runtime_task
    except BaseException as exc:
        primary_error = exc
    finally:
        generation_stop_event.set()
        for task in (monitor_task, process_stop_task):
            if not task.done():
                task.cancel()
        results = await asyncio.gather(runtime_task, monitor_task, process_stop_task, return_exceptions=True)

    if primary_error is not None:
        raise primary_error
    runtime_result = results[0]
    if isinstance(runtime_result, BaseException) and not isinstance(runtime_result, asyncio.CancelledError):
        raise runtime_result


async def main() -> None:
    stop_event = asyncio.Event()
    install_stop_handlers(stop_event)
    client = worker_runtime_client()
    while not stop_event.is_set():
        generation = await _wait_for_coordinator_generation(stop_event, client)
        if generation is None:
            return
        os.environ["RUNTIME_COORDINATOR_GENERATION"] = str(generation)
        try:
            await _run_worker_generation(stop_event, client, generation)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Worker manager generation failed; waiting for coordinator recovery generation=%s", generation)
        finally:
            os.environ.pop("RUNTIME_COORDINATOR_GENERATION", None)
        if not stop_event.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=1.0)


if __name__ == "__main__":
    asyncio.run(main())
