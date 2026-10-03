from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

import grpc

from dataforge_protocol import common_pb2, scheduler_runtime_pb2, scheduler_runtime_pb2_grpc
from scheduler_grpc.health import DispatcherHealth

logger = logging.getLogger(__name__)
_TOKEN_METADATA_KEY = "x-internal-token"
_T = TypeVar("_T")
# The coordinator records scheduler staleness after 15 seconds. A 5-second RPC
# deadline absorbs the measured 1–3-second control-plane tail without allowing
# a hung heartbeat to suppress liveness detection.
_HEARTBEAT_RPC_TIMEOUT_SECONDS = 5.0


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


@dataclass(frozen=True)
class DueScheduleNamespace:
    namespace: str
    generation: int
    wake_ids: tuple[int, ...] = ()


class SchedulerClient(Protocol):
    async def register(self, *, worker_id: str, hostname: str, pid: int, capacity: int, retry_seconds: float | None = None) -> None: ...
    async def heartbeat(self, *, worker_id: str, timeout_seconds: float | None = None) -> None: ...
    async def stop(self, *, worker_id: str, timeout_seconds: float | None = None) -> None: ...
    async def due_schedule_namespaces(self) -> list[DueScheduleNamespace]: ...
    async def run_due(self, *, worker_id: str, namespace: str, generation: int, wake_ids: tuple[int, ...] = ()) -> SchedulerRunDueResult: ...


class SchedulerApiClient:
    def __init__(self, *, target: str, token: str, timeout_seconds: float = 30.0, registration_retry_seconds: float = 90.0) -> None:
        self._target = target
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._registration_retry_seconds = registration_retry_seconds
        self._channel = grpc.aio.insecure_channel(target)
        self._stub = scheduler_runtime_pb2_grpc.SchedulerRuntimeServiceStub(self._channel)

    async def register(self, *, worker_id: str, hostname: str, pid: int, capacity: int, retry_seconds: float | None = None) -> None:
        await self._call_registration(
            lambda: self._stub.RegisterScheduler(
                scheduler_runtime_pb2.SchedulerRegisterRequest(
                    worker_id=worker_id,
                    hostname=hostname,
                    pid=pid,
                    capacity=capacity,
                ),
                timeout=min(self._timeout_seconds, 5.0),
                metadata=self._metadata(),
            ),
            retry_seconds=retry_seconds,
        )

    async def heartbeat(self, *, worker_id: str, timeout_seconds: float | None = None) -> None:
        timeout = self._timeout_seconds if timeout_seconds is None else min(self._timeout_seconds, max(float(timeout_seconds), 0.1))
        await self._call(lambda: self._stub.HeartbeatScheduler(_worker(worker_id), timeout=timeout, metadata=self._metadata()))

    async def stop(self, *, worker_id: str, timeout_seconds: float | None = None) -> None:
        timeout = self._timeout_seconds if timeout_seconds is None else min(self._timeout_seconds, max(float(timeout_seconds), 0.1))
        await self._call(lambda: self._stub.StopScheduler(_worker(worker_id), timeout=timeout, metadata=self._metadata()))

    async def due_schedule_namespaces(self) -> list[DueScheduleNamespace]:
        response = await self._call(
            lambda: self._stub.ListDueScheduleNamespaces(
                common_pb2.EmptyRequest(),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return [DueScheduleNamespace(namespace=item.namespace, generation=item.generation, wake_ids=tuple(item.wake_ids)) for item in response.namespaces]

    async def run_due(self, *, worker_id: str, namespace: str, generation: int, wake_ids: tuple[int, ...] = ()) -> SchedulerRunDueResult:
        response = await self._call(
            lambda: self._stub.RunDueSchedules(
                scheduler_runtime_pb2.SchedulerRunDueRequest(
                    worker_id=worker_id,
                    target_namespace=namespace,
                    generation=generation,
                    wake_ids=wake_ids,
                ),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
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

    async def close(self) -> None:
        await self._channel.close()

    def _metadata(self) -> tuple[tuple[str, str], ...]:
        return ((_TOKEN_METADATA_KEY, self._token),)

    async def _call(self, fn: Callable[[], Awaitable[_T]]) -> _T:
        try:
            return await fn()
        except grpc.RpcError as exc:
            code = exc.code()
            details = exc.details() or f"Backend scheduler gRPC call to {self._target} failed"
            raise RuntimeError(f"Backend scheduler gRPC failed with {code.name}: {details}") from exc

    async def _call_registration(self, fn: Callable[[], Awaitable[_T]], *, retry_seconds: float | None = None) -> _T:
        deadline = time.monotonic() + (self._registration_retry_seconds if retry_seconds is None else max(retry_seconds, 0.0))
        while True:
            try:
                return await self._call(fn)
            except RuntimeError as exc:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or "UNAVAILABLE" not in str(exc):
                    raise
                await asyncio.sleep(min(1.0, remaining))


async def scheduler_loop(
    stop_event: asyncio.Event,
    worker_id: str,
    *,
    client: SchedulerClient,
    health: DispatcherHealth,
    check_interval_seconds: int,
    heartbeat_seconds: float = 5.0,
) -> None:
    await client.register(
        worker_id=worker_id,
        hostname=socket.gethostname(),
        pid=os.getpid(),
        capacity=1,
    )
    health.registered()
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(
            client=client,
            stop_event=stop_event,
            worker_id=worker_id,
            heartbeat_seconds=heartbeat_seconds,
            health=health,
        ),
        name="scheduler-heartbeat",
    )
    try:
        while not stop_event.is_set():
            try:
                due_namespaces = await client.due_schedule_namespaces()
                health.progress("scheduler")
                for due_namespace in due_namespaces:
                    if stop_event.is_set():
                        break
                    result = await client.run_due(
                        worker_id=worker_id,
                        namespace=due_namespace.namespace,
                        generation=due_namespace.generation,
                        wake_ids=due_namespace.wake_ids,
                    )
                    health.progress("scheduler")
                    if result.handled:
                        _log_run_due_result(result)
            except RuntimeError as exc:
                logger.info("Backend temporarily unavailable to scheduler; retrying: %s", exc)
                await _sleep_until_tick_or_stop(stop_event, check_interval_seconds)
                continue
            await _sleep_until_tick_or_stop(stop_event, check_interval_seconds)
    finally:
        health.stopped()
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
        with contextlib.suppress(RuntimeError):
            await client.stop(worker_id=worker_id)


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


async def _sleep_until_tick_or_stop(stop_event: asyncio.Event, seconds: float) -> None:
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


async def _heartbeat_loop(*, client: SchedulerClient, stop_event: asyncio.Event, worker_id: str, heartbeat_seconds: float, health: DispatcherHealth) -> None:
    needs_registration = False
    while not stop_event.is_set():
        await _sleep_until_tick_or_stop(stop_event, heartbeat_seconds)
        if stop_event.is_set():
            break
        try:
            if needs_registration:
                await client.register(worker_id=worker_id, hostname=socket.gethostname(), pid=os.getpid(), capacity=1, retry_seconds=0.0)
                health.registered()
                needs_registration = False
            await client.heartbeat(worker_id=worker_id, timeout_seconds=_HEARTBEAT_RPC_TIMEOUT_SECONDS)
        except RuntimeError as exc:
            needs_registration = True
            health.registration_changed(False)
            if "DEADLINE_EXCEEDED" in str(exc) or "UNAVAILABLE" in str(exc):
                logger.warning("Scheduler heartbeat delayed; retrying on the next interval: %s", exc)
            else:
                logger.exception("Scheduler heartbeat failed")
        except Exception:
            needs_registration = True
            health.registration_changed(False)
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
    worker_id = scheduler_id()
    health = DispatcherHealth(worker_id, lanes=("scheduler",), max_age_seconds=settings.scheduler_check_interval + 45.0)
    try:
        async with health.serve():
            await scheduler_loop(
                stop_event,
                worker_id,
                client=client,
                health=health,
                check_interval_seconds=settings.scheduler_check_interval,
            )
    finally:
        await client.close()


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


def _worker(worker_id: str, *, namespace: str | None = None) -> common_pb2.RuntimeWorkerRequest:
    return common_pb2.RuntimeWorkerRequest(worker_id=worker_id, target_namespace=namespace or "")


if __name__ == "__main__":
    asyncio.run(main())
