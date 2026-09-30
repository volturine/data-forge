from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import queue
import socket
import threading
import uuid
from collections import deque
from collections.abc import Awaitable, Callable

from runtime.domain.runtime_workers.models import RuntimeWorkerKind
from runtime.executors import run_control_in_thread, run_lease_in_thread
from runtime.worker_runtime_client import (
    BuildJobLeaseLost,
    ClaimedBuildJob,
    WorkerRuntimeClient,
    run_worker_heartbeat_loop,
)

logger = logging.getLogger(__name__)
_BUILD_SHUTDOWN_GRACE_SECONDS = 0.5


async def _wait_until_stopped(stop_event: asyncio.Event, delay_seconds: float) -> bool:
    stop_task = asyncio.create_task(stop_event.wait())
    delay_task = asyncio.create_task(asyncio.sleep(delay_seconds))
    done, pending = await asyncio.wait({stop_task, delay_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    return stop_task in done


class RuntimeNamespaceDirectory:
    """Share one bounded pending-work snapshot between recovery lanes.

    Claims are always directed to one namespace. The directory reads the
    indexed durable work table only for missed-notification recovery. All
    request classes consume that snapshot in round-robin order. A lock around
    refresh also prevents four lanes waking at the same instant from issuing
    duplicate recovery RPCs. Build children use directed hints instead of
    owning a cursor.
    """

    def __init__(
        self,
        client: WorkerRuntimeClient,
        *,
        refresh_seconds: float = 5.0,
        namespace_hint_queue: object | None = None,
        work_kinds: tuple[str, ...] = (),
    ) -> None:
        self._client = client
        self._refresh_seconds = max(refresh_seconds, 1.0)
        self._namespace_hint_queue = namespace_hint_queue
        self._work_kinds = work_kinds
        self._local_hints: deque[str] = deque()
        self._namespaces: list[str] = []
        self._cursor = 0
        self._next_refresh = 0.0
        self._lock = asyncio.Lock()

    def enqueue_hint(self, namespace: str) -> None:
        if namespace:
            self._local_hints.append(namespace)

    def _next_queued_hint(self) -> str | None:
        if self._local_hints:
            return self._local_hints.popleft()
        if self._namespace_hint_queue is None:
            return None
        get_nowait = getattr(self._namespace_hint_queue, "get_nowait", None)
        if not callable(get_nowait):
            raise TypeError("Namespace hint queue must provide get_nowait()")
        try:
            hint = get_nowait()
        except EOFError, OSError, queue.Empty:
            return None
        return hint if isinstance(hint, str) and hint else None

    async def _refresh_locked(self) -> None:
        now = asyncio.get_running_loop().time()
        if now >= self._next_refresh:
            if self._work_kinds:
                namespaces = await run_control_in_thread(
                    self._client.pending_runtime_work_namespaces,
                    work_kinds=self._work_kinds,
                )
            else:
                namespaces = await run_control_in_thread(self._client.pending_runtime_work_namespaces)
            self._namespaces = list(dict.fromkeys(namespace for namespace in namespaces if namespace))
            self._cursor = self._cursor % len(self._namespaces) if self._namespaces else 0
            self._next_refresh = now + self._refresh_seconds

    async def snapshot(self) -> list[str]:
        """Return the current directory without issuing duplicate refreshes."""
        async with self._lock:
            await self._refresh_locked()
            return list(self._namespaces)

    async def next_namespace(self) -> str | None:
        queued_hint = self._next_queued_hint()
        if self._namespace_hint_queue is not None:
            # Build children receive directed namespace hints from the
            # manager. They never refresh the complete tenant directory. The
            # manager's recovery cursor is the durable five-second backstop
            # for missed notifications and child restarts.
            return queued_hint
        async with self._lock:
            await self._refresh_locked()
            if not self._namespaces:
                return None
            namespace = self._namespaces[self._cursor % len(self._namespaces)]
            self._cursor += 1
            return namespace


class NamespaceRecovery:
    """Rate-limit one durable recovery operation per namespace."""

    def __init__(self, operation: Callable[..., int], *, work_name: str, interval_seconds: float) -> None:
        self._operation = operation
        self._work_name = work_name
        self._interval_seconds = max(float(interval_seconds), 0.1)
        self._last_attempt: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def reconcile(self, namespace: str) -> None:
        now = asyncio.get_running_loop().time()
        async with self._lock:
            last_attempt = self._last_attempt.get(namespace)
            if last_attempt is not None and now - last_attempt < self._interval_seconds:
                return
            self._last_attempt[namespace] = now
        try:
            reconciled = await run_control_in_thread(self._operation, namespace=namespace)
        except Exception as exc:
            logger.warning("%s recovery failed for namespace %s: %s", self._work_name, namespace, exc)
            return
        if reconciled:
            logger.info("Reconciled %s %s in namespace %s", reconciled, self._work_name, namespace)


async def build_worker_loop(
    stop_event: asyncio.Event,
    worker_id: str,
    run_job: Callable[[ClaimedBuildJob], Awaitable[None]],
    *,
    client: WorkerRuntimeClient,
    capacity: int = 1,
    heartbeat_seconds: float = 5.0,
    idle_exit_seconds: float | None = None,
    max_jobs: int | None = None,
    poll_interval_seconds: float = 1.0,
    on_reconnected: Callable[[], None] | None = None,
    process_idle_signal: Callable[[bool], None] | None = None,
    namespace_hint_queue: object | None = None,
    namespace_directory: RuntimeNamespaceDirectory | None = None,
    recovery: NamespaceRecovery | None = None,
    announce_worker: bool = True,
    on_progress: Callable[[], None] | None = None,
) -> None:
    concurrency = max(1, min(capacity, max_jobs) if max_jobs is not None else capacity)

    def mark_process_busy() -> None:
        if process_idle_signal is not None:
            process_idle_signal(False)

    def mark_process_idle() -> None:
        if process_idle_signal is not None:
            process_idle_signal(True)

    if announce_worker:
        await run_control_in_thread(
            client.register_worker,
            worker_id=worker_id,
            kind=RuntimeWorkerKind.BUILD_WORKER.value,
            hostname=socket.gethostname(),
            pid=os.getpid(),
            capacity=capacity,
        )
    heartbeat_stop = threading.Event()
    active_job = threading.Event()
    heartbeat_thread: threading.Thread | None = None
    if announce_worker:
        heartbeat_thread = threading.Thread(
            target=run_worker_heartbeat_loop,
            kwargs={
                "client": client,
                "stop_signal": heartbeat_stop,
                "worker_id": worker_id,
                "kind": RuntimeWorkerKind.BUILD_WORKER.value,
                "hostname": socket.gethostname(),
                "pid": os.getpid(),
                "capacity": capacity,
                "heartbeat_seconds": heartbeat_seconds,
                "active_jobs": lambda: int(active_job.is_set()),
                "on_reconnected": on_reconnected,
            },
            daemon=True,
        )
        heartbeat_thread.start()
    handled_jobs = 0
    active_tasks: dict[asyncio.Task[None], str] = {}
    if namespace_directory is None:
        namespace_directory = RuntimeNamespaceDirectory(
            client,
            refresh_seconds=max(poll_interval_seconds, 5.0),
            namespace_hint_queue=namespace_hint_queue,
        )
    idle_started = asyncio.get_running_loop().time()
    mark_process_busy()

    async def collect_finished(done: set[asyncio.Task[None]]) -> None:
        nonlocal handled_jobs, idle_started
        for task in done:
            namespace = active_tasks.pop(task)
            try:
                task.result()
            except Exception as exc:
                logger.error("Build job execution failed: %s", exc, exc_info=True)
            else:
                handled_jobs += 1
                idle_started = asyncio.get_running_loop().time()
                namespace_directory.enqueue_hint(namespace)
        active_job_count = len(active_tasks)
        if active_job_count:
            active_job.set()
            mark_process_busy()
        else:
            active_job.clear()
            mark_process_idle()
        await run_control_in_thread(client.heartbeat_worker, worker_id=worker_id, active_jobs=active_job_count)

    try:
        while not stop_event.is_set() and (max_jobs is None or handled_jobs < max_jobs):
            if on_progress is not None:
                on_progress()
            while len(active_tasks) < concurrency and not stop_event.is_set() and (max_jobs is None or handled_jobs + len(active_tasks) < max_jobs):
                try:
                    namespace = await namespace_directory.next_namespace()
                    if namespace is None:
                        break
                    if stop_event.is_set():
                        break
                    mark_process_busy()
                    if recovery is not None:
                        await recovery.reconcile(namespace)
                    claim_started = asyncio.get_running_loop().time()
                    job = await run_control_in_thread(client.claim_build_job, worker_id=worker_id, namespace=namespace)
                    if on_progress is not None:
                        on_progress()
                    if job is None:
                        break
                    lease_deadline = job.lease_deadline_monotonic if job.lease_deadline_monotonic is not None else claim_started + job.lease_ttl_seconds
                    task = asyncio.create_task(
                        _run_claimed_build_job(
                            job=job,
                            worker_id=worker_id,
                            run_job=run_job,
                            client=client,
                            lease_renewal_seconds=heartbeat_seconds,
                            lease_deadline=lease_deadline,
                        )
                    )
                    active_tasks[task] = namespace
                    active_job.set()
                    await run_control_in_thread(client.heartbeat_worker, worker_id=worker_id, active_jobs=len(active_tasks))
                except Exception as exc:
                    logger.error("Build worker loop error: %s", exc, exc_info=True)
                    await asyncio.sleep(0.1)
                    break

            if active_tasks:
                stop_task = asyncio.create_task(stop_event.wait())
                try:
                    done, _pending = await asyncio.wait(
                        {*active_tasks, stop_task},
                        timeout=poll_interval_seconds,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if stop_task not in done:
                        finished = {task for task in active_tasks if task in done}
                        if finished:
                            await collect_finished(finished)
                finally:
                    if not stop_task.done():
                        stop_task.cancel()
                    await asyncio.gather(stop_task, return_exceptions=True)
                continue

            mark_process_idle()
            if idle_exit_seconds is not None:
                remaining_idle = idle_exit_seconds - (asyncio.get_running_loop().time() - idle_started)
                if remaining_idle <= 0:
                    return
                await _wait_until_stopped(stop_event, min(poll_interval_seconds, remaining_idle))
            else:
                await _wait_until_stopped(stop_event, poll_interval_seconds)

        if active_tasks:
            await asyncio.wait(
                set(active_tasks),
                timeout=_BUILD_SHUTDOWN_GRACE_SECONDS,
            )
            finished_builds: set[asyncio.Task[None]] = set()
            for task in active_tasks:
                if task.done():
                    finished_builds.add(task)
            if finished_builds:
                await collect_finished(finished_builds)

    finally:
        tasks = list(active_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        mark_process_idle()
        stop_event.set()
        heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join()
        if announce_worker:
            with contextlib.suppress(Exception):
                await run_control_in_thread(client.stop_worker, worker_id=worker_id, timeout_seconds=2.0)


async def _run_claimed_build_job(
    *,
    job: ClaimedBuildJob,
    worker_id: str,
    run_job: Callable[[ClaimedBuildJob], Awaitable[None]],
    client: WorkerRuntimeClient,
    lease_renewal_seconds: float,
    lease_deadline: float,
) -> None:
    try:
        await _run_with_lease(
            job=job,
            worker_id=worker_id,
            run_job=run_job,
            client=client,
            lease_renewal_seconds=min(lease_renewal_seconds, job.lease_ttl_seconds / 3),
            lease_deadline=lease_deadline,
        )
    except BuildJobLeaseLost:
        logger.info("Build job %s lease was lost; local execution stopped", job.build_id)
        return
    except Exception as exc:
        logger.error("Build job %s failed: %s", job.build_id, exc, exc_info=True)
        failed = await run_control_in_thread(
            client.fail_build_job,
            job_id=job.job_id,
            build_id=job.build_id,
            namespace=job.namespace,
            worker_id=worker_id,
            claim_token=job.claim_token,
            lease_generation=job.lease_generation,
            error=str(exc),
        )
        if not failed:
            logger.info("Build job %s failure was rejected because its lease is no longer active", job.build_id)
        raise

    finalized = await run_control_in_thread(
        client.finalize_build_job,
        job_id=job.job_id,
        build_id=job.build_id,
        namespace=job.namespace,
        worker_id=worker_id,
        claim_token=job.claim_token,
        lease_generation=job.lease_generation,
    )
    if not finalized:
        logger.info("Build job %s finalization was rejected because its lease is no longer active or its run is not terminal", job.build_id)


async def _run_with_lease(
    *,
    job: ClaimedBuildJob,
    worker_id: str,
    run_job: Callable[[ClaimedBuildJob], Awaitable[None]],
    client: WorkerRuntimeClient,
    lease_renewal_seconds: float,
    lease_deadline: float,
) -> None:
    if lease_deadline <= asyncio.get_running_loop().time():
        raise BuildJobLeaseLost(f"Build job {job.job_id} lease expired before execution could start")
    renewal_stop = asyncio.Event()
    execution: asyncio.Future[None] = asyncio.ensure_future(run_job(job))
    renewal = asyncio.create_task(
        _renew_lease(
            job=job,
            worker_id=worker_id,
            client=client,
            stop_event=renewal_stop,
            renewal_seconds=lease_renewal_seconds,
            lease_deadline=lease_deadline,
        )
    )
    try:
        done, _pending = await asyncio.wait({execution, renewal}, return_when=asyncio.FIRST_COMPLETED)
        if execution in done:
            await execution
            return
        if renewal in done:
            await renewal
            raise RuntimeError(f"Build job {job.job_id} lease renewal stopped unexpectedly")
    finally:
        renewal_stop.set()
        if not execution.done():
            execution.cancel()
        await asyncio.gather(execution, renewal, return_exceptions=True)


async def _renew_lease(
    *,
    job: ClaimedBuildJob,
    worker_id: str,
    client: WorkerRuntimeClient,
    stop_event: asyncio.Event,
    renewal_seconds: float,
    lease_deadline: float,
) -> None:
    clock = asyncio.get_running_loop().time
    deadline = lease_deadline
    delay = min(renewal_seconds, max((deadline - clock()) / 3, 0))
    while not await _wait_until_stopped(stop_event, delay):
        remaining = deadline - clock()
        if remaining <= 0:
            raise BuildJobLeaseLost(f"Build job {job.job_id} lease renewal was not confirmed before expiry")
        renewal_started = clock()
        try:
            lease_ttl_seconds = await run_lease_in_thread(
                client.renew_build_job_lease,
                job_id=job.job_id,
                namespace=job.namespace,
                worker_id=worker_id,
                claim_token=job.claim_token,
                lease_generation=job.lease_generation,
                timeout_seconds=remaining,
            )
        except Exception as exc:
            remaining = deadline - clock()
            if remaining <= 0:
                raise BuildJobLeaseLost(f"Build job {job.job_id} lease renewal was not confirmed before expiry") from exc
            delay = min(1.0, remaining, max(remaining / 3, 0.001))
            logger.warning("Build job %s lease renewal failed; retrying before confirmed expiry: %s", job.build_id, exc)
            continue
        if lease_ttl_seconds is None:
            raise BuildJobLeaseLost(f"Build job {job.job_id} lease is no longer active")
        deadline = renewal_started + lease_ttl_seconds
        delay = renewal_seconds


def worker_id() -> str:
    return f"local-worker:{uuid.uuid4()}"
