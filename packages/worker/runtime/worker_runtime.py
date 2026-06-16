from __future__ import annotations

import asyncio
import logging
import os
import socket
import threading
import uuid
from collections.abc import Awaitable, Callable

from runtime.internal_api import WorkerInternalApiClient, client_from_env
from runtime.models.runtime_workers.models import RuntimeWorkerKind

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
    run_job: Callable[[str, str], Awaitable[None]],
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
                handled = await _run_once(worker_id=worker_id, run_job=run_job, client=client)
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
        client.release_build_worker_jobs(worker_id=worker_id)
        client.stop_worker(worker_id=worker_id)


async def _run_once(
    *,
    worker_id: str,
    run_job: Callable[[str, str], Awaitable[None]],
    client: WorkerInternalApiClient,
) -> bool:
    job = client.claim_build_job(worker_id=worker_id)
    if job is None:
        return False

    client.heartbeat_worker(worker_id=worker_id, active_jobs=1)
    try:
        await run_job(job.build_id, job.namespace)
    except Exception as exc:
        logger.error("Build job %s failed: %s", job.build_id, exc, exc_info=True)
        client.fail_build_job(job_id=job.job_id, namespace=job.namespace, error=str(exc))
        raise
    finally:
        client.heartbeat_worker(worker_id=worker_id, active_jobs=0)

    client.finalize_build_job(job_id=job.job_id, build_id=job.build_id, namespace=job.namespace)
    return True


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
