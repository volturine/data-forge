from __future__ import annotations

import asyncio
import logging
import os
import socket
import threading
import uuid
from collections.abc import Awaitable, Callable

from runtime.domain.runtime_workers.models import RuntimeWorkerKind
from runtime.internal_api import BuildJobLeaseLost, ClaimedBuildJob, WorkerInternalApiClient, client_from_env

logger = logging.getLogger(__name__)


async def _wait_until_stopped(stop_event: asyncio.Event, delay_seconds: float) -> bool:
    stop_task = asyncio.create_task(stop_event.wait())
    delay_task = asyncio.create_task(asyncio.sleep(delay_seconds))
    done, pending = await asyncio.wait({stop_task, delay_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    return stop_task in done


async def build_worker_loop(
    stop_event: asyncio.Event,
    worker_id: str,
    run_job: Callable[[ClaimedBuildJob], Awaitable[None]],
    *,
    client: WorkerInternalApiClient,
    capacity: int = 1,
    heartbeat_seconds: float = 5.0,
    idle_exit_seconds: float | None = None,
    max_jobs: int | None = None,
    poll_interval_seconds: float = 1.0,
) -> None:
    client.register_worker(
        worker_id=worker_id,
        kind=RuntimeWorkerKind.BUILD_WORKER.value,
        hostname=socket.gethostname(),
        pid=os.getpid(),
        capacity=capacity,
    )
    heartbeat_stop = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop_sync,
        kwargs={
            "client": client,
            "stop_signal": heartbeat_stop,
            "worker_id": worker_id,
            "heartbeat_seconds": heartbeat_seconds,
        },
        daemon=True,
    )
    heartbeat_thread.start()
    handled_jobs = 0
    try:
        while not stop_event.is_set():
            try:
                handled = await _run_once(
                    worker_id=worker_id,
                    run_job=run_job,
                    client=client,
                    lease_renewal_seconds=heartbeat_seconds,
                )
                if handled:
                    handled_jobs += 1
                    if max_jobs is not None and handled_jobs >= max_jobs:
                        return
                    continue
                if idle_exit_seconds is not None:
                    if await _wait_until_stopped(stop_event, idle_exit_seconds):
                        continue
                    return
                await _wait_until_stopped(stop_event, poll_interval_seconds)
            except Exception as exc:
                logger.error("Build worker loop error: %s", exc, exc_info=True)
                await asyncio.sleep(0.1)
    finally:
        stop_event.set()
        heartbeat_stop.set()
        heartbeat_thread.join()
        client.stop_worker(worker_id=worker_id)


async def _run_once(
    *,
    worker_id: str,
    run_job: Callable[[ClaimedBuildJob], Awaitable[None]],
    client: WorkerInternalApiClient,
    lease_renewal_seconds: float,
) -> bool:
    clock = asyncio.get_running_loop().time
    claim_started = clock()
    job = client.claim_build_job(worker_id=worker_id)
    if job is None:
        return False

    client.heartbeat_worker(worker_id=worker_id, active_jobs=1)
    try:
        await _run_with_lease(
            job=job,
            worker_id=worker_id,
            run_job=run_job,
            client=client,
            lease_renewal_seconds=min(lease_renewal_seconds, job.lease_ttl_seconds / 3),
            lease_deadline=claim_started + job.lease_ttl_seconds,
        )
    except BuildJobLeaseLost:
        logger.info("Build job %s lease was lost; local execution stopped", job.build_id)
        return True
    except Exception as exc:
        logger.error("Build job %s failed: %s", job.build_id, exc, exc_info=True)
        failed = client.fail_build_job(
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
    finally:
        client.heartbeat_worker(worker_id=worker_id, active_jobs=0)

    finalized = client.finalize_build_job(
        job_id=job.job_id,
        build_id=job.build_id,
        namespace=job.namespace,
        worker_id=worker_id,
        claim_token=job.claim_token,
        lease_generation=job.lease_generation,
    )
    if not finalized:
        logger.info("Build job %s finalization was rejected because its lease is no longer active", job.build_id)
    return True


async def _run_with_lease(
    *,
    job: ClaimedBuildJob,
    worker_id: str,
    run_job: Callable[[ClaimedBuildJob], Awaitable[None]],
    client: WorkerInternalApiClient,
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
        if renewal in done:
            await renewal
            raise RuntimeError(f"Build job {job.job_id} lease renewal stopped unexpectedly")
        await execution
    finally:
        renewal_stop.set()
        if not execution.done():
            execution.cancel()
        await asyncio.gather(execution, renewal, return_exceptions=True)


async def _renew_lease(
    *,
    job: ClaimedBuildJob,
    worker_id: str,
    client: WorkerInternalApiClient,
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
            lease_ttl_seconds = await asyncio.to_thread(
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
            delay = min(1.0, max(remaining / 3, 0.05))
            logger.warning("Build job %s lease renewal failed; retrying before confirmed expiry: %s", job.build_id, exc)
            continue
        if lease_ttl_seconds is None:
            raise BuildJobLeaseLost(f"Build job {job.job_id} lease is no longer active")
        deadline = renewal_started + lease_ttl_seconds
        delay = renewal_seconds


def _heartbeat_loop_sync(*, client: WorkerInternalApiClient, stop_signal: threading.Event, worker_id: str, heartbeat_seconds: float) -> None:
    while not stop_signal.wait(heartbeat_seconds):
        try:
            client.heartbeat_worker(worker_id=worker_id)
        except Exception as exc:
            logger.warning("Build worker heartbeat failed: %s", exc)


def worker_id() -> str:
    return f"local-worker:{uuid.uuid4()}"


def runtime_namespaces() -> list[str]:
    return client_from_env().runtime_namespaces()
