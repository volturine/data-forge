from __future__ import annotations

import asyncio
import contextlib
import logging
import multiprocessing
import multiprocessing.process
import os
import signal
import socket
import threading
import time
import uuid
from multiprocessing.synchronize import Event as ProcessEvent

from contracts.build_jobs.live import hub as build_job_hub
from contracts.runtime import ipc as runtime_ipc
from contracts.runtime.ipc import RuntimeListenerKind
from contracts.runtime_workers.models import RuntimeWorkerKind
from core import (
    build_jobs_service as build_job_service,
)
from core import (
    runtime_workers_service as runtime_worker_service,
)
from core.config import settings
from core.database import init_db, run_db, run_settings_db
from core.logging import configure_logging
from core.namespace import reset_namespace, set_namespace_context

from runtime.compute_manager import ProcessManager
from runtime.compute_request_runtime import compute_request_loop
from runtime.engine_notifications import create_snapshot_notifier
from runtime.runtime_notifications import handle_runtime_payload
from runtime.worker_runtime import (
    build_worker_loop,
    runtime_namespaces,
)
from runtime.worker_runtime import (
    worker_id as build_worker_id,
)

logger = logging.getLogger(__name__)
_SPAWN = multiprocessing.get_context("spawn")
_CHILD_COOPERATIVE_STOP_SECONDS = 5.0
_CHILD_TERMINATE_SECONDS = 2.0
_CHILD_KILL_SECONDS = 1.0


class ManagedWorkerProcess:
    def __init__(
        self,
        process: multiprocessing.process.BaseProcess,
        stop_signal: ProcessEvent,
        stopped_signal: ProcessEvent,
    ) -> None:
        self.process = process
        self.stop_signal = stop_signal
        self.stopped_signal = stopped_signal


def _register_manager(worker_id: str) -> None:
    def _register(session) -> None:
        runtime_worker_service.register_worker(
            session,
            worker_id=worker_id,
            kind=RuntimeWorkerKind.BUILD_MANAGER,
            hostname=socket.gethostname(),
            pid=os.getpid(),
            capacity=max(settings.build_worker_max_processes, 0),
        )

    run_settings_db(_register)


def _heartbeat_manager(worker_id: str, active_jobs: int = 0) -> None:
    def _heartbeat(session) -> None:
        runtime_worker_service.heartbeat_worker(session, worker_id=worker_id, active_jobs=active_jobs)

    run_settings_db(_heartbeat)


def _stop_manager(worker_id: str) -> None:
    def _stop(session) -> None:
        runtime_worker_service.mark_worker_stopped(session, worker_id=worker_id)

    run_settings_db(_stop)


def manager_id() -> str:
    return f"build-manager:{uuid.uuid4()}"


def queued_job_count() -> int:
    count = 0
    for namespace in runtime_namespaces():
        token = set_namespace_context(namespace)
        try:
            count += run_db(build_job_service.queued_job_count)
        finally:
            reset_namespace(token)
    return count


def _manager_heartbeat_loop(stop_signal: threading.Event, worker_id: str, *, heartbeat_seconds: float = 5.0) -> None:
    while not stop_signal.wait(heartbeat_seconds):
        _heartbeat_manager(worker_id, active_jobs=0)


async def _watch_process_stop_signal(stop_signal: ProcessEvent, stop_event: asyncio.Event) -> None:
    await asyncio.to_thread(stop_signal.wait)
    stop_event.set()


def _worker_main(stop_signal: ProcessEvent, stopped_signal: ProcessEvent) -> None:
    async def _run() -> None:
        stop_event = asyncio.Event()
        install_stop_handlers(stop_event)
        stop_task = asyncio.create_task(_watch_process_stop_signal(stop_signal, stop_event))
        try:
            await run_build_worker_process(stop_event=stop_event)
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
) -> None:
    await init_db()
    configure_logging()
    logger.info("Starting build worker process...")
    local_stop = stop_event or asyncio.Event()
    worker_id = build_worker_id()
    manager = ProcessManager(
        on_snapshot=create_snapshot_notifier(
            asyncio.get_running_loop(),
            worker_id=worker_id,
        )
    )

    from builds.build_execution import _run_queued_build_job

    async def run_job(build_id: str) -> None:
        await _run_queued_build_job(manager=manager, build_id=build_id)

    task = asyncio.create_task(
        build_worker_loop(
            local_stop,
            worker_id,
            run_job,
            idle_exit_seconds=idle_exit_seconds,
            max_jobs=max_jobs,
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
    process = _SPAWN.Process(target=_worker_main, args=(stop_signal, stopped_signal))
    process.start()
    return ManagedWorkerProcess(process=process, stop_signal=stop_signal, stopped_signal=stopped_signal)


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
        return
    logger.error(
        "Build worker process %s did not stop cooperatively; escalating shutdown",
        child.process.pid,
    )
    child.process.terminate()
    if _wait_for_child_stop(child, timeout_seconds=_CHILD_TERMINATE_SECONDS, require_ack=False):
        return
    logger.error("Build worker process %s ignored terminate(); killing", child.process.pid)
    child.process.kill()
    if _wait_for_child_stop(child, timeout_seconds=_CHILD_KILL_SECONDS, require_ack=False):
        return
    raise RuntimeError(f"Build worker process {child.process.pid} could not be stopped")


def _reap_dead_children(children: dict[int, ManagedWorkerProcess]) -> None:
    stale = [pid for pid, child in children.items() if not child.process.is_alive()]
    for pid in stale:
        child = children.pop(pid)
        child.process.join()


def _next_idle_child_pid(children: dict[int, ManagedWorkerProcess]) -> int | None:
    workers = run_settings_db(runtime_worker_service.list_workers, kind=RuntimeWorkerKind.BUILD_WORKER)
    idle_pids = {worker.pid for worker in workers if worker.stopped_at is None and worker.active_jobs == 0}
    for pid, child in children.items():
        process_pid = child.process.pid
        if process_pid is None:
            continue
        if process_pid in idle_pids:
            return pid
    return None


async def run_build_manager_process(*, stop_event: asyncio.Event | None = None) -> None:
    await init_db()
    configure_logging()
    logger.info("Starting build worker manager process...")
    local_stop = stop_event or asyncio.Event()
    ipc_server = await runtime_ipc.start_api_server(listener=RuntimeListenerKind.JOB)
    ipc_task = None
    if ipc_server is not None:
        ipc_task = asyncio.create_task(runtime_ipc.serve_api_notifications(ipc_server, local_stop, handle_runtime_payload))
    worker_id = manager_id()
    _register_manager(worker_id)
    manager = ProcessManager(
        on_snapshot=create_snapshot_notifier(
            asyncio.get_running_loop(),
            worker_id=worker_id,
        )
    )
    heartbeat_stop = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_manager_heartbeat_loop,
        kwargs={
            "stop_signal": heartbeat_stop,
            "worker_id": worker_id,
        },
        daemon=True,
    )
    heartbeat_thread.start()
    request_tasks = [
        asyncio.create_task(compute_request_loop(local_stop, worker_id=worker_id, manager=manager)) for _ in range(settings.compute_request_concurrency)
    ]
    children: dict[int, ManagedWorkerProcess] = {}
    last_seen = build_job_hub.version()
    try:
        while not local_stop.is_set():
            _reap_dead_children(children)

            queued = await asyncio.to_thread(queued_job_count)
            desired = min(
                settings.build_worker_max_processes,
                max(settings.build_worker_min_processes, queued),
            )
            while len(children) < desired:
                child = _spawn_worker_process()
                children[child.process.pid or id(child.process)] = child
            while len(children) > desired:
                idle_pid = _next_idle_child_pid(children)
                if idle_pid is None:
                    break
                child = children.pop(idle_pid)
                _stop_worker_process(child)

            if len(children) >= desired and queued == 0:
                wait_task = asyncio.create_task(build_job_hub.wait(last_seen))
                stop_task = asyncio.create_task(local_stop.wait())
                done, pending = await asyncio.wait({wait_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                if stop_task in done:
                    continue
                with contextlib.suppress(asyncio.CancelledError):
                    value = await wait_task
                    if isinstance(value, int):
                        last_seen = value
                continue

            await asyncio.sleep(0.1)
    finally:
        local_stop.set()
        heartbeat_stop.set()
        heartbeat_thread.join()
        if ipc_task is not None:
            await asyncio.gather(ipc_task)
        await runtime_ipc.stop_api_server(ipc_server, listener=RuntimeListenerKind.JOB)
        for child in children.values():
            _stop_worker_process(child)
        manager.shutdown_all()
        await asyncio.gather(*request_tasks)
        _stop_manager(worker_id)
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
    stop_event = asyncio.Event()
    install_stop_handlers(stop_event)
    await run_build_manager_process(stop_event=stop_event)


if __name__ == "__main__":
    asyncio.run(main())
