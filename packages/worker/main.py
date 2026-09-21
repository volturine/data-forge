from __future__ import annotations

import asyncio
import contextlib
import logging
import multiprocessing
import multiprocessing.process
import os
import signal
import threading
import time
import uuid
from multiprocessing.synchronize import Event as ProcessEvent

from runtime.compute_manager import ProcessManager
from runtime.compute_request_runtime import (
    ENGINE_LIFECYCLE_REQUEST_KINDS,
    INTERACTIVE_ENGINE_REQUEST_KINDS,
    NON_ENGINE_REQUEST_KINDS,
    compute_request_lane_count,
    compute_request_loop,
    compute_request_worker_count,
)
from runtime.config import settings
from runtime.datasource_delete_runtime import datasource_delete_loop
from runtime.docker_engine import reconcile_deployment_containers, validate_engine_runtime_readiness
from runtime.domain.build_jobs.live import hub as build_job_hub
from runtime.domain.runtime_workers.models import RuntimeWorkerKind
from runtime.engine_notifications import create_snapshot_notifier
from runtime.logging import configure_logging
from runtime.namespace import get_namespace, reset_namespace, set_namespace_context
from runtime.runtime_ipc import serve_runtime_notifications, start_runtime_listener, stop_runtime_listener
from runtime.runtime_notifications import handle_runtime_payload
from runtime.worker_runtime import (
    build_worker_loop,
    worker_id as build_worker_id,
)
from runtime.worker_runtime_client import ClaimedBuildJob, WorkerRuntimeClient, client_from_env
from worker_grpc.data_plane_server import start_data_plane_grpc_server_in_thread

logger = logging.getLogger(__name__)
_SPAWN = multiprocessing.get_context("spawn")
_CHILD_COOPERATIVE_STOP_SECONDS = 5.0
_CHILD_TERMINATE_SECONDS = 2.0
_CHILD_KILL_SECONDS = 1.0
_MIN_RUNTIME_RECOVERY_SECONDS = 5.0


def worker_runtime_client() -> WorkerRuntimeClient:
    return client_from_env()


class ManagedWorkerProcess:
    def __init__(
        self,
        process: multiprocessing.process.BaseProcess,
        stop_signal: ProcessEvent,
        stopped_signal: ProcessEvent,
        worker_id: str = "",
    ) -> None:
        self.process = process
        self.stop_signal = stop_signal
        self.stopped_signal = stopped_signal
        self.worker_id = worker_id


def manager_id() -> str:
    return f"build-manager:{uuid.uuid4()}"


def _manager_heartbeat_loop(
    stop_signal: threading.Event,
    worker_id: str,
    *,
    client: WorkerRuntimeClient,
    heartbeat_seconds: float = 5.0,
) -> None:
    while not stop_signal.wait(heartbeat_seconds):
        try:
            client.heartbeat_worker(worker_id=worker_id, active_jobs=0)
        except Exception as error:
            # A backend restart or transient outage must not kill the heartbeat
            # thread; the next tick retries against the current backend.
            logger.warning("Runtime worker heartbeat failed: %s", error)


async def _watch_process_stop_signal(stop_signal: ProcessEvent, stop_event: asyncio.Event) -> None:
    await asyncio.to_thread(stop_signal.wait)
    stop_event.set()


def _worker_main(stop_signal: ProcessEvent, stopped_signal: ProcessEvent, worker_id: str) -> None:
    async def _run() -> None:
        stop_event = asyncio.Event()
        install_stop_handlers(stop_event)
        stop_task = asyncio.create_task(_watch_process_stop_signal(stop_signal, stop_event))
        try:
            await run_build_worker_process(stop_event=stop_event, worker_id=worker_id)
        finally:
            stop_event.set()
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
            stopped_signal.set()

    asyncio.run(_run())


async def run_build_worker_process(
    *,
    stop_event: asyncio.Event | None = None,
    idle_exit_seconds: float | None = None,
    max_jobs: int | None = None,
    worker_id: str | None = None,
) -> None:
    configure_logging()
    logger.info("Starting build worker process...")
    local_stop = stop_event or asyncio.Event()
    worker_id = worker_id or build_worker_id()
    manager = ProcessManager(
        on_snapshot=create_snapshot_notifier(
            asyncio.get_running_loop(),
            namespace_provider=get_namespace,
            worker_id=worker_id,
        ),
        supervisor_id=worker_id,
        # The manager process owns the interactive request warm pool. Build
        # children share the Docker daemon and must not each create another
        # copy of the configured warm pool. They also cannot consume the
        # globally reserved warm slots, so interactive requests retain two
        # admission slots after the warm engines are claimed.
        warm_pool_size=0,
        global_reserved_slots=settings.engine_warm_pool_size,
    )

    from builds.build_execution import run_queued_build_job

    client = worker_runtime_client()

    async def run_job(job: ClaimedBuildJob) -> None:
        token = set_namespace_context(job.namespace)
        try:
            await run_queued_build_job(manager=manager, worker_id=worker_id, claim=job)
        finally:
            reset_namespace(token)

    task = asyncio.create_task(
        build_worker_loop(
            local_stop,
            worker_id,
            run_job,
            client=client,
            idle_exit_seconds=idle_exit_seconds,
            max_jobs=max_jobs,
            poll_interval_seconds=settings.runtime_reconciliation_poll_interval_seconds,
        )
    )
    try:
        return await task
    finally:
        local_stop.set()
        if not task.done():
            await asyncio.gather(task)
        manager.shutdown_all()
        logger.info("Build worker process shutdown complete")


def _spawn_worker_process() -> ManagedWorkerProcess:
    stop_signal = _SPAWN.Event()
    stopped_signal = _SPAWN.Event()
    worker_id = build_worker_id()
    process = _SPAWN.Process(target=_worker_main, args=(stop_signal, stopped_signal, worker_id))
    process.start()
    return ManagedWorkerProcess(process=process, stop_signal=stop_signal, stopped_signal=stopped_signal, worker_id=worker_id)


def _wait_for_child_stop(child: ManagedWorkerProcess, *, timeout_seconds: float, require_ack: bool) -> bool:
    deadline = time.monotonic() + timeout_seconds
    acknowledged = not require_ack
    if require_ack and child.process.is_alive():
        acknowledged = child.stopped_signal.wait(max(0.0, deadline - time.monotonic()))
        if not acknowledged and child.process.is_alive():
            return False
    remaining = max(0.0, deadline - time.monotonic())
    child.process.join(timeout=remaining)
    if child.process.is_alive():
        return False
    child.process.join()
    if require_ack and not acknowledged:
        logger.error(
            "Build worker process %s exited without sending a stop acknowledgement",
            child.process.pid,
        )
    return True


def _stop_worker_process(child: ManagedWorkerProcess) -> None:
    child.stop_signal.set()
    if _wait_for_child_stop(child, timeout_seconds=_CHILD_COOPERATIVE_STOP_SECONDS, require_ack=True):
        if child.worker_id:
            reconcile_deployment_containers(supervisor_id=child.worker_id)
        return
    logger.error(
        "Build worker process %s did not stop cooperatively; escalating shutdown",
        child.process.pid,
    )
    child.process.terminate()
    if _wait_for_child_stop(child, timeout_seconds=_CHILD_TERMINATE_SECONDS, require_ack=False):
        if child.worker_id:
            reconcile_deployment_containers(supervisor_id=child.worker_id)
        return
    logger.error("Build worker process %s ignored terminate(); killing", child.process.pid)
    child.process.kill()
    if _wait_for_child_stop(child, timeout_seconds=_CHILD_KILL_SECONDS, require_ack=False):
        if child.worker_id:
            reconcile_deployment_containers(supervisor_id=child.worker_id)
        return
    raise RuntimeError(f"Build worker process {child.process.pid} could not be stopped")


def _reap_dead_children(children: dict[int, ManagedWorkerProcess]) -> None:
    stale = [pid for pid, child in children.items() if not child.process.is_alive()]
    for pid in stale:
        child = children.pop(pid)
        child.process.join()
        if child.worker_id:
            reconcile_deployment_containers(supervisor_id=child.worker_id)


def _next_idle_child_pid(children: dict[int, ManagedWorkerProcess], *, client: WorkerRuntimeClient) -> int | None:
    idle_pids = client.idle_build_worker_pids()
    for pid, child in children.items():
        process_pid = child.process.pid
        if process_pid is None:
            continue
        if process_pid in idle_pids:
            return pid
    return None


async def run_build_manager_process(*, stop_event: asyncio.Event | None = None) -> None:
    configure_logging()
    logger.info("Starting build worker manager process...")
    local_stop = stop_event or asyncio.Event()
    client = worker_runtime_client()
    worker_id = manager_id()
    manager = ProcessManager(
        on_snapshot=create_snapshot_notifier(
            asyncio.get_running_loop(),
            namespace_provider=get_namespace,
            worker_id=worker_id,
        ),
        supervisor_id=worker_id,
        # This is the only manager for the application-wide interactive pool.
        # Build children deliberately pass warm_pool_size=0 below.
        warm_pool_size=settings.engine_warm_pool_size,
    )
    runtime_listener = None
    runtime_listener_task: asyncio.Task[None] | None = None
    try:
        warm_pool_timeout = max(float(settings.engine_start_timeout_seconds) * 4, 120.0)
        warm_pool_ready = await asyncio.to_thread(
            manager.wait_for_warm_pool_ready,
            timeout_seconds=warm_pool_timeout,
        )
        if not warm_pool_ready:
            logger.warning(
                "Initial engine warm pool was not ready after %.1fs; starting manager with %s warm engine(s)",
                warm_pool_timeout,
                manager.warm_pool_count,
            )
        if local_stop.is_set():
            manager.shutdown_all()
            return
        data_plane_server = start_data_plane_grpc_server_in_thread()
        try:
            runtime_listener = await asyncio.to_thread(start_runtime_listener)
            runtime_listener_task = asyncio.create_task(serve_runtime_notifications(runtime_listener, local_stop, handle_runtime_payload))
        except Exception as exc:
            # Polling remains a recovery path if Postgres LISTEN is unavailable
            # during startup. Normal operation should be notification-driven.
            logger.warning("Worker runtime notifications unavailable; using recovery polling: %s", exc)
    except BaseException:
        if runtime_listener_task is not None:
            runtime_listener_task.cancel()
            await asyncio.gather(runtime_listener_task, return_exceptions=True)
        await asyncio.to_thread(stop_runtime_listener, runtime_listener)
        manager.shutdown_all()
        raise

    client.register_worker(
        worker_id=worker_id,
        kind=RuntimeWorkerKind.BUILD_MANAGER.value,
        hostname=os.uname().nodename,
        pid=os.getpid(),
        capacity=max(settings.build_worker_max_processes, 0),
    )
    heartbeat_stop = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_manager_heartbeat_loop,
        kwargs={
            "client": client,
            "stop_signal": heartbeat_stop,
            "worker_id": worker_id,
        },
        daemon=True,
    )
    heartbeat_thread.start()
    request_worker_count = compute_request_worker_count()
    request_lane_count = compute_request_lane_count()
    # Keep request lanes plentiful enough to absorb a browser burst, while
    # serializing the expensive claim transactions to a small shared control
    # plane.  Without this gate every lane in all three request groups wakes
    # on the same notification and competes for the database pool.
    claim_semaphore = asyncio.Semaphore(min(request_worker_count, 8))
    # Claim each work class independently at the configured concurrency. The
    # runtime gives datasource and engine work separate bounded executors, so
    # parked engine admissions cannot prevent datasource work from executing
    # and datasource bursts cannot serialize engine requests.
    # Keep capacity-waiting lifecycle/prewarm requests from occupying every
    # lane that can claim interactive previews. Shutdown stays in the
    # non-engine lane because it frees capacity and never waits for a slot.
    # Each lane advances the namespace cursor independently so a busy default
    # namespace cannot starve work submitted to another namespace.
    # Only the first lane in each class performs periodic recovery polling.
    # Notifications wake all lanes for normal work, while three recovery polls
    # per interval are enough to find requests staged while the worker was
    # disconnected without creating a database claim storm.
    request_lanes = [
        *((NON_ENGINE_REQUEST_KINDS, offset, offset == 0) for offset in range(request_lane_count)),
        *((INTERACTIVE_ENGINE_REQUEST_KINDS, request_lane_count + offset, offset == 0) for offset in range(request_lane_count)),
        *((ENGINE_LIFECYCLE_REQUEST_KINDS, (2 * request_lane_count) + offset, offset == 0) for offset in range(request_lane_count)),
    ]
    request_tasks = [
        asyncio.create_task(
            compute_request_loop(
                local_stop,
                worker_id=worker_id,
                manager=manager,
                allowed_kinds=allowed_kinds,
                compute_namespace_offset=namespace_offset,
                claim_semaphore=claim_semaphore,
                poll_for_work=poll_for_work,
            )
        )
        for allowed_kinds, namespace_offset, poll_for_work in request_lanes
    ]
    datasource_delete_task = asyncio.create_task(datasource_delete_loop(local_stop, manager=manager))
    children: dict[int, ManagedWorkerProcess] = {}
    last_build_job_version = build_job_hub.version()
    recovery_poll_seconds = max(
        _MIN_RUNTIME_RECOVERY_SECONDS,
        float(settings.runtime_reconciliation_poll_interval_seconds),
    )
    try:
        while not local_stop.is_set():
            _reap_dead_children(children)
            try:
                await asyncio.to_thread(client.dispatch_runtime_outbox)
                queued = await asyncio.to_thread(client.queued_build_job_count)
            except Exception as exc:
                logger.info("Backend temporarily unavailable to build manager; retrying: %s", exc)
                await asyncio.sleep(min(settings.runtime_reconciliation_poll_interval_seconds, 1.0))
                continue
            desired = min(
                settings.build_worker_max_processes,
                max(settings.build_worker_min_processes, queued),
            )
            while len(children) < desired:
                child = _spawn_worker_process()
                children[child.process.pid or id(child.process)] = child
            while len(children) > desired:
                idle_pid = _next_idle_child_pid(children, client=client)
                if idle_pid is None:
                    break
                child = children.pop(idle_pid)
                _stop_worker_process(child)

            if len(children) >= desired and queued == 0:
                stop_task = asyncio.create_task(local_stop.wait())
                build_job_task = asyncio.create_task(build_job_hub.wait(last_build_job_version))
                poll_task = asyncio.create_task(asyncio.sleep(recovery_poll_seconds))
                done, pending = await asyncio.wait(
                    {stop_task, build_job_task, poll_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                if stop_task in done:
                    continue
                if build_job_task in done:
                    with contextlib.suppress(asyncio.CancelledError):
                        version = build_job_task.result()
                        if isinstance(version, int):
                            last_build_job_version = version
                continue

            # While jobs are queued, reconcile frequently enough to stop idle
            # children after completion. The steady state is the notification
            # or five-second recovery path above, not a one-second namespace
            # scan in every worker lane.
            await asyncio.sleep(0.25)
    finally:
        local_stop.set()
        heartbeat_stop.set()
        heartbeat_thread.join()
        for child in children.values():
            _stop_worker_process(child)
        # Closing the manager first rejects parked capacity admissions. Waiting
        # for request tasks before this point can deadlock shutdown forever.
        manager.shutdown_all()
        await asyncio.gather(*request_tasks, datasource_delete_task, return_exceptions=True)
        if runtime_listener_task is not None:
            await asyncio.gather(runtime_listener_task, return_exceptions=True)
        await asyncio.to_thread(stop_runtime_listener, runtime_listener)
        await data_plane_server.stop(grace=1.0)
        client.stop_worker(worker_id=worker_id)
        logger.info("Build worker manager shutdown complete")


def install_stop_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def _stop() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _stop)


async def main() -> None:
    multiprocessing.freeze_support()
    await asyncio.to_thread(validate_engine_runtime_readiness)
    removed = await asyncio.to_thread(reconcile_deployment_containers)
    if removed:
        logger.warning("Removed %s orphaned engine container(s) during startup", removed)
    stop_event = asyncio.Event()
    install_stop_handlers(stop_event)
    await run_build_manager_process(stop_event=stop_event)


if __name__ == "__main__":
    asyncio.run(main())
