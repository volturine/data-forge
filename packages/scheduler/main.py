from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

import grpc

from dataforge_protocol import common_pb2, scheduler_runtime_pb2, scheduler_runtime_pb2_grpc

logger = logging.getLogger(__name__)
_TOKEN_METADATA_KEY = "x-internal-token"
_T = TypeVar("_T")


@dataclass(frozen=True)
class SchedulerSettings:
    internal_grpc_target: str
    internal_api_token: str
    scheduler_check_interval: int
    log_level: str

    @classmethod
    def from_env(cls) -> SchedulerSettings:
        return cls(
            internal_grpc_target=_required_env("INTERNAL_GRPC_TARGET"),
            internal_api_token=_required_env("INTERNAL_API_TOKEN"),
            scheduler_check_interval=_required_positive_int_env("SCHEDULER_CHECK_INTERVAL"),
            log_level=os.environ.get("LOG_LEVEL", "info").lower(),
        )


@dataclass(frozen=True)
class EnqueuedScheduleRun:
    namespace: str
    schedule_id: str
    datasource_id: str
    build_id: str


@dataclass(frozen=True)
class FailedScheduleRun:
    namespace: str
    schedule_id: str
    datasource_id: str
    error: str


@dataclass(frozen=True)
class SchedulerRunDueResult:
    handled: bool
    enqueued: list[EnqueuedScheduleRun]
    failures: list[FailedScheduleRun]


class SchedulerApiClient:
    def __init__(self, *, target: str, token: str, timeout_seconds: float = 30.0, registration_retry_seconds: float = 90.0) -> None:
        self._target = target
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._registration_retry_seconds = registration_retry_seconds
        self._channel = grpc.insecure_channel(target)
        self._stub = scheduler_runtime_pb2_grpc.SchedulerRuntimeServiceStub(self._channel)

    def register(self, *, worker_id: str, hostname: str, pid: int, capacity: int) -> None:
        self._call_registration(
            lambda: self._stub.RegisterScheduler(
                scheduler_runtime_pb2.SchedulerRegisterRequest(
                    worker_id=worker_id,
                    hostname=hostname,
                    pid=pid,
                    capacity=capacity,
                ),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )

    def heartbeat(self, *, worker_id: str) -> None:
        self._call(lambda: self._stub.HeartbeatScheduler(_worker(worker_id), timeout=self._timeout_seconds, metadata=self._metadata()))

    def stop(self, *, worker_id: str) -> None:
        self._call(lambda: self._stub.StopScheduler(_worker(worker_id), timeout=self._timeout_seconds, metadata=self._metadata()))

    def run_due(self, *, worker_id: str) -> SchedulerRunDueResult:
        response = self._call(lambda: self._stub.RunDueSchedules(_worker(worker_id), timeout=self._timeout_seconds, metadata=self._metadata()))
        return SchedulerRunDueResult(
            handled=response.handled,
            enqueued=[
                EnqueuedScheduleRun(namespace=item.namespace, schedule_id=item.schedule_id, datasource_id=item.datasource_id, build_id=item.build_id)
                for item in response.enqueued
            ],
            failures=[
                FailedScheduleRun(namespace=item.namespace, schedule_id=item.schedule_id, datasource_id=item.datasource_id, error=item.error)
                for item in response.failures
            ],
        )

    def close(self) -> None:
        self._channel.close()

    def _metadata(self) -> tuple[tuple[str, str], ...]:
        return ((_TOKEN_METADATA_KEY, self._token),)

    def _call(self, fn: Callable[[], _T]) -> _T:
        try:
            return fn()
        except grpc.RpcError as exc:
            code = exc.code()
            details = exc.details() or f"Backend scheduler gRPC call to {self._target} failed"
            raise RuntimeError(f"Backend scheduler gRPC failed with {code.name}: {details}") from exc

    def _call_registration(self, fn: Callable[[], _T]) -> _T:
        deadline = time.monotonic() + self._registration_retry_seconds
        while True:
            try:
                return self._call(fn)
            except RuntimeError as exc:
                if time.monotonic() >= deadline or "UNAVAILABLE" not in str(exc):
                    raise
                time.sleep(1.0)


async def scheduler_loop(
    stop_event: asyncio.Event,
    worker_id: str,
    *,
    client: SchedulerApiClient,
    check_interval_seconds: int,
    heartbeat_seconds: float = 5.0,
) -> None:
    await asyncio.to_thread(
        client.register,
        worker_id=worker_id,
        hostname=socket.gethostname(),
        pid=os.getpid(),
        capacity=1,
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
    try:
        while not stop_event.is_set():
            try:
                result = await asyncio.to_thread(client.run_due, worker_id=worker_id)
            except RuntimeError as exc:
                logger.info("Backend temporarily unavailable to scheduler; retrying: %s", exc)
                await _sleep_until_tick_or_stop(stop_event, check_interval_seconds)
                continue
            if result.handled:
                _log_run_due_result(result)
                continue
            await _sleep_until_tick_or_stop(stop_event, check_interval_seconds)
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join()
        with contextlib.suppress(RuntimeError):
            await asyncio.to_thread(client.stop, worker_id=worker_id)


def _log_run_due_result(result: SchedulerRunDueResult) -> None:
    for enqueued in result.enqueued:
        logger.info(
            "Scheduler: enqueued schedule %s as build %s (namespace=%s datasource=%s)",
            enqueued.schedule_id,
            enqueued.build_id,
            enqueued.namespace,
            enqueued.datasource_id,
        )
    for failure in result.failures:
        logger.error(
            "Scheduler: enqueue failed for schedule %s (namespace=%s datasource=%s): %s",
            failure.schedule_id,
            failure.namespace,
            failure.datasource_id,
            failure.error,
        )


async def _sleep_until_tick_or_stop(stop_event: asyncio.Event, seconds: int) -> None:
    sleep_task = asyncio.create_task(asyncio.sleep(seconds))
    stop_task = asyncio.create_task(stop_event.wait())
    done, pending = await asyncio.wait({sleep_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        with contextlib.suppress(asyncio.CancelledError):
            _task_result = task.result()


def _heartbeat_loop_sync(*, client: SchedulerApiClient, stop_signal: threading.Event, worker_id: str, heartbeat_seconds: float) -> None:
    while not stop_signal.wait(heartbeat_seconds):
        try:
            client.heartbeat(worker_id=worker_id)
        except Exception:
            logger.exception("Scheduler heartbeat failed")


def scheduler_id() -> str:
    return f"scheduler:{uuid.uuid4()}"


def install_stop_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def _stop() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _stop)


async def main() -> None:
    settings = SchedulerSettings.from_env()
    logging.basicConfig(level=settings.log_level.upper())
    logger.info("Starting scheduler process...")
    stop_event = asyncio.Event()
    install_stop_handlers(stop_event)
    client = SchedulerApiClient(target=settings.internal_grpc_target, token=settings.internal_api_token)
    try:
        await scheduler_loop(
            stop_event,
            scheduler_id(),
            client=client,
            check_interval_seconds=settings.scheduler_check_interval,
        )
    finally:
        client.close()


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} must be configured for the scheduler runtime")
    return value.strip()


def _required_positive_int_env(name: str) -> int:
    raw_value = _required_env(name)
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw_value!r}") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be at least 1, got {value}")
    return value


def _worker(worker_id: str) -> common_pb2.RuntimeWorkerRequest:
    return common_pb2.RuntimeWorkerRequest(worker_id=worker_id)


if __name__ == "__main__":
    asyncio.run(main())
