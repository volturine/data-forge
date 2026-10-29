from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol, cast

import grpc

from dataforge_protocol import common_pb2, scheduler_runtime_pb2, scheduler_runtime_pb2_grpc
from scheduler_grpc.health import DispatcherHealth

logger = logging.getLogger(__name__)
_TOKEN_METADATA_KEY = "x-internal-token"
# The coordinator records scheduler staleness after 15 seconds. A 5-second RPC
# deadline absorbs the measured 1–3-second control-plane tail without allowing
# a hung heartbeat to suppress liveness detection.
_HEARTBEAT_RPC_TIMEOUT_SECONDS = 5.0


class SchedulerRpcError(RuntimeError):
    def __init__(self, code: grpc.StatusCode, details: str) -> None:
        super().__init__(f"Backend scheduler gRPC failed with {code.name}: {details}")
        self.code = code


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


class SchedulerClient(Protocol):
    async def register(self, *, worker_id: str, hostname: str, pid: int, capacity: int, retry_seconds: float | None = None) -> None: ...
    async def heartbeat(self, *, worker_id: str, timeout_seconds: float | None = None) -> None: ...
    async def stop(self, *, worker_id: str) -> None: ...
    async def due_schedule_namespaces(self) -> list[scheduler_runtime_pb2.SchedulerDueNamespace]: ...
    async def run_due(
        self,
        *,
        worker_id: str,
        namespace: str,
        generation: int,
        wake_ids: tuple[int, ...] = (),
    ) -> scheduler_runtime_pb2.SchedulerRunDueResponse: ...


class SchedulerApiClient:
    def __init__(self, *, target: str, token: str, timeout_seconds: float = 30.0, registration_retry_seconds: float = 90.0) -> None:
        self._target = target
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._registration_retry_seconds = registration_retry_seconds
        self._channel = grpc.aio.insecure_channel(target)
        self._stub = scheduler_runtime_pb2_grpc.SchedulerRuntimeServiceStub(self._channel)

    async def register(self, *, worker_id: str, hostname: str, pid: int, capacity: int, retry_seconds: float | None = None) -> None:
        request = scheduler_runtime_pb2.SchedulerRegisterRequest(worker_id=worker_id, hostname=hostname, pid=pid, capacity=capacity)
        retry_window = self._registration_retry_seconds if retry_seconds is None else max(retry_seconds, 0.0)
        await self._unary("RegisterScheduler", request, timeout=min(self._timeout_seconds, 5.0), retry_seconds=retry_window)

    async def heartbeat(self, *, worker_id: str, timeout_seconds: float | None = None) -> None:
        timeout = self._timeout_seconds if timeout_seconds is None else min(self._timeout_seconds, max(float(timeout_seconds), 0.1))
        await self._unary("HeartbeatScheduler", _worker(worker_id), timeout=timeout)

    async def stop(self, *, worker_id: str) -> None:
        await self._unary("StopScheduler", _worker(worker_id))

    async def due_schedule_namespaces(self) -> list[scheduler_runtime_pb2.SchedulerDueNamespace]:
        response = await self._unary("ListDueScheduleNamespaces", common_pb2.EmptyRequest())
        return list(response.namespaces)

    async def run_due(
        self,
        *,
        worker_id: str,
        namespace: str,
        generation: int,
        wake_ids: tuple[int, ...] = (),
    ) -> scheduler_runtime_pb2.SchedulerRunDueResponse:
        request = scheduler_runtime_pb2.SchedulerRunDueRequest(worker_id=worker_id, target_namespace=namespace, generation=generation, wake_ids=wake_ids)
        return cast(scheduler_runtime_pb2.SchedulerRunDueResponse, await self._unary("RunDueSchedules", request))

    async def close(self) -> None:
        await self._channel.close()

    async def _unary(self, method: str, request: Any, *, timeout: float | None = None, retry_seconds: float = 0.0) -> Any:
        """Call one scheduler-runtime RPC, retrying UNAVAILABLE until ``retry_seconds`` have elapsed."""
        rpc = getattr(self._stub, method)
        deadline = time.monotonic() + retry_seconds
        while True:
            try:
                return await rpc(request, timeout=self._timeout_seconds if timeout is None else timeout, metadata=((_TOKEN_METADATA_KEY, self._token),))
            except grpc.RpcError as exc:
                code = exc.code()
                remaining = deadline - time.monotonic()
                if code != grpc.StatusCode.UNAVAILABLE or remaining <= 0:
                    details = exc.details() or f"Backend scheduler gRPC call to {self._target} failed"
                    raise SchedulerRpcError(code, details) from exc
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
                        wake_ids=tuple(due_namespace.wake_ids),
                    )
                    health.progress("scheduler")
                    if result.handled:
                        _log_run_due_result(result)
            except RuntimeError as exc:
                logger.info("Backend temporarily unavailable to scheduler; retrying: %s", exc)
            await _sleep_until_tick_or_stop(stop_event, check_interval_seconds)
    finally:
        health.stopped()
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
        with contextlib.suppress(RuntimeError):
            await client.stop(worker_id=worker_id)


def _log_run_due_result(result: scheduler_runtime_pb2.SchedulerRunDueResponse) -> None:
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
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop_event.wait(), seconds)


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
        except Exception as exc:
            needs_registration = True
            health.registration_changed(False)
            if isinstance(exc, SchedulerRpcError) and exc.code in {grpc.StatusCode.DEADLINE_EXCEEDED, grpc.StatusCode.UNAVAILABLE}:
                logger.warning("Scheduler heartbeat delayed; retrying on the next interval: %s", exc)
            else:
                logger.exception("Scheduler heartbeat failed")


def install_stop_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)


async def main() -> None:
    settings = SchedulerSettings.from_env()
    logging.basicConfig(level=settings.log_level.upper())
    logger.info("Starting scheduler process...")
    stop_event = asyncio.Event()
    install_stop_handlers(stop_event)
    client = SchedulerApiClient(target=settings.internal_grpc_target, token=settings.internal_api_token)
    worker_id = f"scheduler:{uuid.uuid4()}"
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


def _worker(worker_id: str) -> common_pb2.RuntimeWorkerRequest:
    return common_pb2.RuntimeWorkerRequest(worker_id=worker_id)


if __name__ == "__main__":
    asyncio.run(main())
