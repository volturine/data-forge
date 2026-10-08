"""gRPC client from worker processes to the API WorkerRuntime service."""

from __future__ import annotations

import asyncio
import base64
import contextvars
import hashlib
import logging
import os
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from concurrent.futures import Future as ThreadFuture
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar, cast
from weakref import WeakKeyDictionary

import grpc

from dataforge_protocol import (
    analysis_pb2,
    common_pb2,
    compute_pb2,
    datasource_pb2,
    enums_pb2,
    runtime_coordinator_pb2,
    runtime_coordinator_pb2_grpc,
    worker_runtime_pb2,
    worker_runtime_pb2_grpc,
)
from runtime.domain.compute.base import ComputeWorkerStatusInfo
from runtime.protocol_mapping import (
    datasource_record_payload as _datasource_record_payload,
    datetime_to_timestamp,
    dict_to_struct,
    enum_to_proto_value,
    optional_struct_to_dict,
    optional_timestamp_to_datetime,
    proto_value_to_enum_name,
    schema_info_payload as _schema_info_payload,
    schema_info_proto as _schema_info_proto,
    struct_to_dict,
)

_TOKEN_METADATA_KEY = "x-internal-token"
_COORDINATOR_GENERATION_METADATA_KEY = "x-runtime-coordinator-generation"
logger = logging.getLogger(__name__)
_HEARTBEAT_RPC_TIMEOUT_SECONDS = 5.0
_CONTROL_RPC_TIMEOUT_SECONDS = 15.0
_BUILD_LIFECYCLE_RETRY_SECONDS = 30.0
_TRANSIENT_RECONNECT_CODES = frozenset({"UNAVAILABLE", "DEADLINE_EXCEEDED"})

_channel_lock = threading.Lock()
_channels: dict[str, grpc.Channel] = {}
_COMPUTE_LEASE_BATCH_WINDOW_SECONDS = 0.025
_COMPUTE_LEASE_BATCH_MAX_ITEMS = 256


@dataclass
class _ComputeLeaseRenewalCall:
    client: WorkerRuntimeClient
    namespace: str
    worker_id: str
    request_id: str
    claim_token: str
    lease_generation: int
    timeout_seconds: float
    group_key: tuple[object, ...]
    result: asyncio.Future[int | None]


class _ComputeLeaseRenewalBatcher:
    """Coalesce loop-owned lease waiters into one bounded runtime RPC per namespace."""

    def __init__(self, *, batch_window_seconds: float = _COMPUTE_LEASE_BATCH_WINDOW_SECONDS) -> None:
        self._loop = asyncio.get_running_loop()
        self._pending: deque[_ComputeLeaseRenewalCall] = deque()
        self._batch_window_seconds = max(float(batch_window_seconds), 0.0)
        self._closed = False
        self._task: asyncio.Task[None] | None = None

    async def renew(
        self,
        client: WorkerRuntimeClient,
        *,
        request_id: str,
        namespace: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        timeout_seconds: float,
    ) -> int | None:
        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("Compute lease batcher must be used on its owning event loop")
        if self._closed:
            raise RuntimeError("Compute request lease batcher is shut down")
        call = _ComputeLeaseRenewalCall(
            client=client,
            namespace=namespace,
            worker_id=worker_id,
            request_id=request_id,
            claim_token=claim_token,
            lease_generation=lease_generation,
            timeout_seconds=max(float(timeout_seconds), 0.1),
            group_key=(client._target, client._metadata(), namespace, worker_id),
            result=self._loop.create_future(),
        )
        self._pending.append(call)
        if self._task is None:
            self._task = self._loop.create_task(self._run())
        try:
            return await call.result
        except asyncio.CancelledError:
            call.result.cancel()
            raise

    async def close(self) -> None:
        self._closed = True
        if self._task is not None:
            await self._task

    async def _run(self) -> None:
        while True:
            if not self._pending:
                self._task = None
                return
            if self._batch_window_seconds:
                await asyncio.sleep(self._batch_window_seconds)
            first = self._pending.popleft()
            calls: list[_ComputeLeaseRenewalCall] = []
            remaining: deque[_ComputeLeaseRenewalCall] = deque()
            if not first.result.cancelled():
                calls.append(first)
            while self._pending:
                call = self._pending.popleft()
                if call.result.cancelled():
                    continue
                if call.group_key == first.group_key and len(calls) < _COMPUTE_LEASE_BATCH_MAX_ITEMS:
                    calls.append(call)
                else:
                    remaining.append(call)
            self._pending = remaining
            if not calls:
                continue
            try:
                renewed = await first.client._renew_compute_request_leases_batch_async(
                    namespace=first.namespace,
                    worker_id=first.worker_id,
                    renewals=[(call.request_id, call.claim_token, call.lease_generation) for call in calls],
                    timeout_seconds=min(call.timeout_seconds for call in calls),
                )
            except Exception as exc:
                for call in calls:
                    if not call.result.done():
                        call.result.set_exception(exc)
            else:
                for call in calls:
                    if not call.result.done():
                        call.result.set_result(renewed.get(call.request_id))


_compute_lease_batcher_lock = threading.Lock()
_compute_lease_batchers: WeakKeyDictionary[asyncio.AbstractEventLoop, _ComputeLeaseRenewalBatcher] = WeakKeyDictionary()
_async_runtime_clients: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[tuple[str, str], WorkerRuntimeClient]] = WeakKeyDictionary()


def _get_compute_lease_batcher(loop: asyncio.AbstractEventLoop) -> _ComputeLeaseRenewalBatcher:
    with _compute_lease_batcher_lock:
        batcher = _compute_lease_batchers.get(loop)
        if batcher is None:
            batcher = _ComputeLeaseRenewalBatcher()
            _compute_lease_batchers[loop] = batcher
        return batcher


async def shutdown_compute_request_lease_batcher() -> None:
    loop = asyncio.get_running_loop()
    with _compute_lease_batcher_lock:
        batcher = _compute_lease_batchers.pop(loop, None)
    if batcher is not None:
        await batcher.close()


def _shared_channel(target: str) -> grpc.Channel:
    """One channel per target for the whole process.

    gRPC channels are thread-safe and multiplex concurrent calls. The runtime
    creates a client per hop (metadata lookups, engine runs, snapshots), so a
    channel per client meant a DNS, TCP and HTTP/2 handshake on every call and
    a socket left open until garbage collection.
    """
    with _channel_lock:
        channel = _channels.get(target)
        if channel is None:
            channel = grpc.insecure_channel(target)
            _channels[target] = channel
        return channel


def _claim_lease_timing(
    lease_expires_at: datetime,
    lease_ttl_seconds: int,
    *,
    wall_now: datetime | None = None,
    monotonic_now: float | None = None,
) -> tuple[float, float]:
    """Convert the absolute DB expiry into a conservative local deadline."""
    current_monotonic_time = time.monotonic() if monotonic_now is None else monotonic_now
    current_wall_time = wall_now or datetime.now(UTC)
    remaining = min(float(lease_ttl_seconds), (lease_expires_at - current_wall_time).total_seconds())
    if remaining <= 0:
        raise ValueError("Claim lease expired before it reached the worker")
    return remaining, current_monotonic_time + remaining


_T = TypeVar("_T")


@dataclass(frozen=True)
class ClaimedBuildJob:
    job_id: str
    build_id: str
    namespace: str
    claim_token: str
    lease_generation: int
    lease_expires_at: datetime
    attempt: int
    lease_ttl_seconds: float
    lease_deadline_monotonic: float | None = None


@dataclass(frozen=True)
class StartedBuildRun:
    id: str
    namespace: str
    analysis_id: str
    analysis_name: str
    analysis_pipeline: analysis_pb2.AnalysisPipelinePayload
    tab_id: str | None
    starter_json: dict[str, object]
    resource_config_json: dict[str, object] | None
    current_kind: str | None
    current_datasource_id: str | None
    current_tab_id: str | None
    current_tab_name: str | None
    current_output_id: str | None
    current_output_name: str | None
    started_at: datetime
    total_tabs: int


@dataclass(frozen=True)
class PendingDatasourceDelete:
    namespace: str
    datasource_id: str


@dataclass(frozen=True)
class TelegramTarget:
    chat_id: str
    bot_token: str


@dataclass(frozen=True)
class DatasourceMetadata:
    found: bool
    id: str | None
    name: str | None
    source_type: str | None
    config: dict[str, object] | None
    schema_cache: dict[str, object] | None
    is_hidden: bool | None
    revision: int | None = None
    description: str | None = None
    column_descriptions: dict[str, str] | None = None
    created_by: str | None = None


_datasource_metadata_snapshot: contextvars.ContextVar[Mapping[tuple[str, str], DatasourceMetadata] | None] = contextvars.ContextVar(
    "worker_datasource_metadata_snapshot",
    default=None,
)


def set_datasource_metadata_snapshot(
    snapshot: Mapping[tuple[str, str], DatasourceMetadata],
) -> contextvars.Token[Mapping[tuple[str, str], DatasourceMetadata] | None]:
    return _datasource_metadata_snapshot.set(snapshot)


def reset_datasource_metadata_snapshot(
    token: contextvars.Token[Mapping[tuple[str, str], DatasourceMetadata] | None],
) -> None:
    _datasource_metadata_snapshot.reset(token)


def frozen_datasource_metadata(namespace: str, datasource_id: str) -> DatasourceMetadata | None:
    snapshot = _datasource_metadata_snapshot.get()
    if snapshot is None:
        return None
    if (namespace, datasource_id) not in snapshot:
        from runtime.exceptions import StaleComputeInputError

        raise StaleComputeInputError(datasource_id, expected_revision=0, actual_revision=None)
    return snapshot[(namespace, datasource_id)]


@dataclass(frozen=True)
class HealthCheckSpec:
    id: str
    name: str
    check_type: str
    config: dict[str, object]
    critical: bool


@dataclass(frozen=True)
class ClaimedComputeRequest:
    id: str
    namespace: str
    kind: enums_pb2.ComputeRequestKind
    command_envelope: compute_pb2.ComputeCommandEnvelope
    worker_id: str
    claim_token: str
    lease_generation: int
    lease_expires_at: datetime
    attempt: int
    lease_ttl_seconds: float
    lease_deadline_monotonic: float | None = None
    command_hash: str | None = None


@dataclass(frozen=True)
class StorageCleanupClaim:
    namespace: str
    event_id: str
    claim_token: str
    lease_generation: int
    resource_id: str
    url: str
    is_prefix: bool
    catalog_identifier: str | None = None
    catalog_type: str | None = None
    catalog_uri: str | None = None
    warehouse: str | None = None
    catalog_namespace: str | None = None
    catalog_table: str | None = None
    catalog_family_prefix: str | None = None

    def protocol_claim(self) -> worker_runtime_pb2.WorkerStorageCleanupClaimRequest:
        return worker_runtime_pb2.WorkerStorageCleanupClaimRequest(
            namespace=self.namespace,
            event_id=self.event_id,
            claim_token=self.claim_token,
            lease_generation=self.lease_generation,
        )


@dataclass(frozen=True)
class ComputeWorkerRunFinalization:
    run_id: str
    fields: Mapping[str, object]
    merge_result_json: bool = False


class BackendWorkerRpcError(RuntimeError):
    def __init__(
        self,
        *,
        status_code: int,
        error: str,
        error_code: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(error)
        self.status_code = status_code
        self.error = error
        self.error_code = error_code
        self.details = details or {}


class BuildJobLeaseLost(RuntimeError):
    pass


class WorkerRuntimeClient:
    def __init__(self, *, target: str, token: str, timeout_seconds: float = 120.0, registration_retry_seconds: float = 90.0) -> None:
        self._target = target
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._registration_retry_seconds = registration_retry_seconds
        self._channel = _shared_channel(target)
        self._stub = worker_runtime_pb2_grpc.WorkerRuntimeServiceStub(self._channel)
        self._coordinator_stub = runtime_coordinator_pb2_grpc.RuntimeCoordinatorServiceStub(self._channel)
        self._aio_loop: asyncio.AbstractEventLoop | None = None
        self._aio_channel: grpc.aio.Channel | None = None
        self._aio_stub: Any | None = None
        self._aio_coordinator_stub: Any | None = None
        self._coordinator_assertions_lock = threading.Lock()
        self._coordinator_assertions: dict[int, ThreadFuture[int]] = {}

    def _async_stubs(self) -> tuple[Any, Any]:
        loop = asyncio.get_running_loop()
        if self._aio_channel is None:
            self._aio_loop = loop
            self._aio_channel = grpc.aio.insecure_channel(self._target)
            self._aio_stub = worker_runtime_pb2_grpc.WorkerRuntimeServiceStub(self._aio_channel)
            self._aio_coordinator_stub = runtime_coordinator_pb2_grpc.RuntimeCoordinatorServiceStub(self._aio_channel)
        elif self._aio_loop is not loop:
            raise RuntimeError("Async runtime RPCs must stay on the worker service event loop")
        return self._aio_stub, self._aio_coordinator_stub

    async def _call_async[T](self, call: Awaitable[T], *, operation: str = "unknown") -> T:
        started = time.perf_counter()
        task = asyncio.ensure_future(call)
        try:
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                    except BaseException:
                        break
                if task.done() and not task.cancelled():
                    try:
                        task.result()
                    except BaseException:
                        logger.warning("Worker async runtime RPC failed while cancellation was settling operation=%s", operation)
                raise
        except grpc.RpcError as exc:
            raise _rpc_error_from_grpc_error(exc, target=self._target) from exc
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            if elapsed_ms >= 1000:
                logger.warning(
                    "Worker async runtime RPC was slow operation=%s duration_ms=%.1f target=%s",
                    operation,
                    elapsed_ms,
                    self._target,
                )

    async def aclose(self) -> None:
        channel = self._aio_channel
        if channel is None:
            return
        if self._aio_loop is not asyncio.get_running_loop():
            raise RuntimeError("Async runtime channel must close on its owning event loop")
        await channel.close()
        self._aio_channel = None
        self._aio_stub = None
        self._aio_coordinator_stub = None
        self._aio_loop = None

    def get_coordinator_generation(self) -> int:
        request = common_pb2.EmptyRequest()
        response = self._call(
            lambda: self._coordinator_stub.GetCoordinatorGeneration(
                request,
                timeout=self._control_timeout(),
                metadata=self._token_metadata(),
            )
        )
        return response.generation

    async def get_coordinator_generation_async(self) -> int:
        _worker_stub, coordinator_stub = self._async_stubs()
        response = await self._call_async(
            coordinator_stub.GetCoordinatorGeneration(
                common_pb2.EmptyRequest(),
                timeout=self._control_timeout(),
                metadata=self._token_metadata(),
            ),
            operation="GetCoordinatorGeneration",
        )
        return response.generation

    def assert_coordinator_generation(self, generation: int) -> None:
        with self._coordinator_assertions_lock:
            result = self._coordinator_assertions.get(generation)
            owns_assertion = result is None
            if result is None:
                result = ThreadFuture()
                self._coordinator_assertions[generation] = result

        if owns_assertion:
            try:
                request = runtime_coordinator_pb2.RuntimeCoordinatorGenerationRequest(generation=generation)
                response = self._call(
                    lambda: self._coordinator_stub.AssertCoordinatorGeneration(
                        request,
                        timeout=self._control_timeout(),
                        metadata=self._metadata_for_generation(generation),
                    )
                )
                result.set_result(response.generation)
            except BaseException as exc:
                result.set_exception(exc)
                raise
            finally:
                with self._coordinator_assertions_lock:
                    if self._coordinator_assertions.get(generation) is result:
                        del self._coordinator_assertions[generation]

        active_generation = result.result()
        if active_generation != generation:
            raise BackendWorkerRpcError(
                status_code=grpc.StatusCode.FAILED_PRECONDITION.value[0],
                error=f"Runtime coordinator generation {generation} is fenced by {active_generation}",
                error_code="FAILED_PRECONDITION",
            )

    def register_worker(
        self,
        *,
        worker_id: str,
        kind: str,
        hostname: str,
        pid: int,
        capacity: int,
        active_jobs: int = 0,
        retry_seconds: float | None = None,
    ) -> None:
        request = worker_runtime_pb2.RuntimeWorkerRegisterRequest(
            worker_id=worker_id,
            kind=enum_to_proto_value("RUNTIME_WORKER_KIND", kind),
            hostname=hostname,
            pid=pid,
            capacity=capacity,
            active_jobs=active_jobs,
        )
        registration_timeout = min(
            self._timeout_seconds,
            _CONTROL_RPC_TIMEOUT_SECONDS if retry_seconds is None else min(max(float(retry_seconds), 0.25), _CONTROL_RPC_TIMEOUT_SECONDS),
        )
        self._call_registration(
            lambda: self._stub.RegisterWorker(request, timeout=registration_timeout, metadata=self._metadata()),
            retry_seconds=retry_seconds,
        )

    async def register_worker_async(
        self,
        *,
        worker_id: str,
        kind: str,
        hostname: str,
        pid: int,
        capacity: int,
        active_jobs: int = 0,
        retry_seconds: float | None = None,
    ) -> None:
        request = worker_runtime_pb2.RuntimeWorkerRegisterRequest(
            worker_id=worker_id,
            kind=enum_to_proto_value("RUNTIME_WORKER_KIND", kind),
            hostname=hostname,
            pid=pid,
            capacity=capacity,
            active_jobs=active_jobs,
        )
        timeout = min(
            self._timeout_seconds,
            _CONTROL_RPC_TIMEOUT_SECONDS if retry_seconds is None else min(max(float(retry_seconds), 0.25), _CONTROL_RPC_TIMEOUT_SECONDS),
        )
        retry_window = self._registration_retry_seconds if retry_seconds is None else max(retry_seconds, 0.0)
        deadline = asyncio.get_running_loop().time() + retry_window
        delay = 0.25
        worker_stub, _coordinator_stub = self._async_stubs()
        while True:
            try:
                await self._call_async(
                    worker_stub.RegisterWorker(request, timeout=timeout, metadata=self._metadata()),
                    operation="RegisterWorker",
                )
                return
            except BackendWorkerRpcError as exc:
                remaining = deadline - asyncio.get_running_loop().time()
                if exc.error_code not in _TRANSIENT_RECONNECT_CODES or remaining <= 0:
                    raise
                await asyncio.sleep(min(delay, remaining))
                delay = min(delay * 2, 2.0)

    def heartbeat_worker(self, *, worker_id: str, active_jobs: int | None = None, timeout_seconds: float | None = None) -> None:
        request = worker_runtime_pb2.RuntimeWorkerHeartbeatRequest(worker_id=worker_id)
        if active_jobs is not None:
            request.active_jobs = active_jobs
        timeout = self._control_timeout(timeout_seconds)
        self._call(lambda: self._stub.HeartbeatWorker(request, timeout=timeout, metadata=self._metadata()))

    async def heartbeat_worker_async(self, *, worker_id: str, active_jobs: int | None = None, timeout_seconds: float | None = None) -> None:
        request = worker_runtime_pb2.RuntimeWorkerHeartbeatRequest(worker_id=worker_id)
        if active_jobs is not None:
            request.active_jobs = active_jobs
        timeout = self._control_timeout(timeout_seconds)
        worker_stub, _coordinator_stub = self._async_stubs()
        await self._call_async(
            worker_stub.HeartbeatWorker(request, timeout=timeout, metadata=self._metadata()),
            operation="HeartbeatWorker",
        )

    def stop_worker(self, *, worker_id: str, timeout_seconds: float | None = None) -> None:
        timeout = self._control_timeout(timeout_seconds)
        self._call(lambda: self._stub.StopWorker(_worker(worker_id), timeout=timeout, metadata=self._metadata()))

    async def stop_worker_async(self, *, worker_id: str, timeout_seconds: float | None = None) -> None:
        timeout = self._control_timeout(timeout_seconds)
        worker_stub, _coordinator_stub = self._async_stubs()
        await self._call_async(
            worker_stub.StopWorker(_worker(worker_id), timeout=timeout, metadata=self._metadata()),
            operation="StopWorker",
        )

    def claim_build_job(self, *, worker_id: str, namespace: str) -> ClaimedBuildJob | None:
        response = self._call(
            lambda: self._stub.ClaimBuildJob(
                common_pb2.RuntimeWorkerRequest(worker_id=worker_id, protocol_version=2, target_namespace=namespace),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            )
        )
        if not response.HasField("job"):
            return None
        lease_expires_at = optional_timestamp_to_datetime(response.job, "lease_expires_at")
        if lease_expires_at is None:
            raise ValueError(f"Claimed build job {response.job.job_id} has no lease expiry")
        if lease_expires_at.tzinfo is None:
            lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
        lease_ttl_seconds, lease_deadline = _claim_lease_timing(lease_expires_at, response.job.lease_ttl_seconds)
        return ClaimedBuildJob(
            job_id=response.job.job_id,
            build_id=response.job.build_id,
            namespace=response.job.namespace,
            claim_token=response.job.claim_token,
            lease_generation=response.job.lease_generation,
            lease_expires_at=lease_expires_at,
            attempt=response.job.attempt,
            lease_ttl_seconds=lease_ttl_seconds,
            lease_deadline_monotonic=lease_deadline,
        )

    async def claim_build_job_async(self, *, worker_id: str, namespace: str) -> ClaimedBuildJob | None:
        request = common_pb2.RuntimeWorkerRequest(worker_id=worker_id, protocol_version=2, target_namespace=namespace)
        worker_stub, _coordinator_stub = self._async_stubs()
        response = await self._call_async(
            worker_stub.ClaimBuildJob(request, timeout=self._control_timeout(), metadata=self._metadata()),
            operation="ClaimBuildJob",
        )
        if not response.HasField("job"):
            return None
        job = response.job
        lease_expires_at = optional_timestamp_to_datetime(job, "lease_expires_at")
        if lease_expires_at is None:
            raise ValueError(f"Claimed build job {job.job_id} has no lease expiry")
        if lease_expires_at.tzinfo is None:
            lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
        lease_ttl_seconds, lease_deadline = _claim_lease_timing(lease_expires_at, job.lease_ttl_seconds)
        return ClaimedBuildJob(
            job_id=job.job_id,
            build_id=job.build_id,
            namespace=job.namespace,
            claim_token=job.claim_token,
            lease_generation=job.lease_generation,
            lease_expires_at=lease_expires_at,
            attempt=job.attempt,
            lease_ttl_seconds=lease_ttl_seconds,
            lease_deadline_monotonic=lease_deadline,
        )

    def renew_build_job_lease(
        self,
        *,
        job_id: str,
        namespace: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        timeout_seconds: float,
    ) -> int | None:
        response = self._call(
            lambda: self._stub.RenewBuildJobLease(
                worker_runtime_pb2.WorkerBuildJobClaimRequest(
                    job_id=job_id,
                    namespace=namespace,
                    claim_token=claim_token,
                    lease_generation=lease_generation,
                    worker_id=worker_id,
                ),
                timeout=min(self._control_timeout(), max(float(timeout_seconds), 0.1)),
                metadata=self._metadata(),
            )
        )
        if not response.renewed:
            return None
        if not response.HasField("lease_ttl_seconds"):
            raise ValueError(f"Renewed build job {job_id} has no lease TTL")
        return int(response.lease_ttl_seconds)

    async def renew_build_job_lease_async(
        self,
        *,
        job_id: str,
        namespace: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        timeout_seconds: float,
    ) -> int | None:
        request = worker_runtime_pb2.WorkerBuildJobClaimRequest(
            job_id=job_id,
            namespace=namespace,
            claim_token=claim_token,
            lease_generation=lease_generation,
            worker_id=worker_id,
        )
        worker_stub, _coordinator_stub = self._async_stubs()
        response = await self._call_async(
            worker_stub.RenewBuildJobLease(
                request,
                timeout=min(self._control_timeout(), max(float(timeout_seconds), 0.1)),
                metadata=self._metadata(),
            ),
            operation="RenewBuildJobLease",
        )
        if not response.renewed:
            return None
        if not response.HasField("lease_ttl_seconds"):
            raise ValueError(f"Renewed build job {job_id} has no lease TTL")
        return int(response.lease_ttl_seconds)

    def claim_compute_request(
        self,
        *,
        worker_id: str,
        allowed_kinds: frozenset[enums_pb2.ComputeRequestKind],
        namespace: str,
    ) -> ClaimedComputeRequest | None:
        response = self._call(
            lambda: self._stub.ClaimComputeRequest(
                common_pb2.RuntimeWorkerRequest(
                    worker_id=worker_id,
                    protocol_version=2,
                    allowed_compute_request_kinds=sorted(allowed_kinds),
                    target_namespace=namespace,
                ),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            )
        )
        if not response.HasField("request"):
            return None
        command = response.request.command
        lease_expires_at = optional_timestamp_to_datetime(response.request, "lease_expires_at")
        if lease_expires_at is None:
            raise ValueError(f"Claimed compute request {response.request.id} has no lease expiry")
        if lease_expires_at.tzinfo is None:
            lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
        lease_ttl_seconds, lease_deadline = _claim_lease_timing(lease_expires_at, response.request.lease_ttl_seconds)
        return ClaimedComputeRequest(
            id=response.request.id,
            namespace=response.request.namespace,
            kind=command.kind,
            command_envelope=command,
            worker_id=worker_id,
            claim_token=response.request.claim_token,
            lease_generation=response.request.lease_generation,
            lease_expires_at=lease_expires_at,
            attempt=response.request.attempt,
            lease_ttl_seconds=lease_ttl_seconds,
            lease_deadline_monotonic=lease_deadline,
            command_hash=hashlib.sha256(command.command.SerializeToString(deterministic=True)).hexdigest(),
        )

    async def claim_compute_request_async(
        self,
        *,
        worker_id: str,
        allowed_kinds: frozenset[enums_pb2.ComputeRequestKind],
        namespace: str,
    ) -> ClaimedComputeRequest | None:
        request = common_pb2.RuntimeWorkerRequest(
            worker_id=worker_id,
            protocol_version=2,
            allowed_compute_request_kinds=sorted(allowed_kinds),
            target_namespace=namespace,
        )
        worker_stub, _coordinator_stub = self._async_stubs()
        response = await self._call_async(
            worker_stub.ClaimComputeRequest(request, timeout=self._control_timeout(), metadata=self._metadata()),
            operation="ClaimComputeRequest",
        )
        if not response.HasField("request"):
            return None
        claim = response.request
        command = claim.command
        lease_expires_at = optional_timestamp_to_datetime(claim, "lease_expires_at")
        if lease_expires_at is None:
            raise ValueError(f"Claimed compute request {claim.id} has no lease expiry")
        if lease_expires_at.tzinfo is None:
            lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
        lease_ttl_seconds, lease_deadline = _claim_lease_timing(lease_expires_at, claim.lease_ttl_seconds)
        return ClaimedComputeRequest(
            id=claim.id,
            namespace=claim.namespace,
            kind=command.kind,
            command_envelope=command,
            worker_id=worker_id,
            claim_token=claim.claim_token,
            lease_generation=claim.lease_generation,
            lease_expires_at=lease_expires_at,
            attempt=claim.attempt,
            lease_ttl_seconds=lease_ttl_seconds,
            lease_deadline_monotonic=lease_deadline,
            command_hash=hashlib.sha256(command.command.SerializeToString(deterministic=True)).hexdigest(),
        )

    async def renew_compute_request_lease(
        self,
        *,
        request_id: str,
        namespace: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        timeout_seconds: float,
    ) -> int | None:
        loop = asyncio.get_running_loop()
        return await _get_compute_lease_batcher(loop).renew(
            self,
            request_id=request_id,
            namespace=namespace,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_generation=lease_generation,
            timeout_seconds=timeout_seconds,
        )

    def _renew_compute_request_leases_batch(
        self,
        *,
        namespace: str,
        worker_id: str,
        renewals: Sequence[tuple[str, str, int]],
        timeout_seconds: float,
    ) -> dict[str, int | None]:
        request = worker_runtime_pb2.WorkerRenewComputeRequestLeasesRequest(
            namespace=namespace,
            worker_id=worker_id,
            renewals=[
                worker_runtime_pb2.WorkerComputeRequestLeaseRenewal(
                    request_id=request_id,
                    claim_token=claim_token,
                    lease_generation=lease_generation,
                )
                for request_id, claim_token, lease_generation in renewals
            ],
        )
        response = self._call(
            lambda: self._stub.RenewComputeRequestLeases(
                request,
                timeout=self._control_timeout(timeout_seconds),
                metadata=self._metadata(),
            )
        )
        results: dict[str, int | None] = {request_id: None for request_id, _, _ in renewals}
        for result in response.renewals:
            if result.request_id not in results:
                continue
            if not result.renewed:
                continue
            if not result.HasField("lease_ttl_seconds"):
                raise ValueError(f"Renewed compute request {result.request_id} has no lease TTL")
            results[result.request_id] = int(result.lease_ttl_seconds)
        return results

    async def _renew_compute_request_leases_batch_async(
        self,
        *,
        namespace: str,
        worker_id: str,
        renewals: Sequence[tuple[str, str, int]],
        timeout_seconds: float,
    ) -> dict[str, int | None]:
        request = worker_runtime_pb2.WorkerRenewComputeRequestLeasesRequest(
            namespace=namespace,
            worker_id=worker_id,
            renewals=[
                worker_runtime_pb2.WorkerComputeRequestLeaseRenewal(
                    request_id=request_id,
                    claim_token=claim_token,
                    lease_generation=lease_generation,
                )
                for request_id, claim_token, lease_generation in renewals
            ],
        )
        worker_stub, _coordinator_stub = self._async_stubs()
        response = await self._call_async(
            worker_stub.RenewComputeRequestLeases(
                request,
                timeout=self._control_timeout(timeout_seconds),
                metadata=self._metadata(),
            ),
            operation="RenewComputeRequestLeases",
        )
        results: dict[str, int | None] = {request_id: None for request_id, _, _ in renewals}
        for result in response.renewals:
            if result.request_id not in results or not result.renewed:
                continue
            if not result.HasField("lease_ttl_seconds"):
                raise ValueError(f"Renewed compute request {result.request_id} has no lease TTL")
            results[result.request_id] = int(result.lease_ttl_seconds)
        return results

    def complete_compute_request(
        self,
        *,
        namespace: str,
        request_id: str,
        kind: enums_pb2.ComputeRequestKind,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        response: compute_pb2.ComputeResponse,
        artifact_path: str | None = None,
        artifact_name: str | None = None,
        artifact_content_type: str | None = None,
        engine_run_finalization: ComputeWorkerRunFinalization | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        request = worker_runtime_pb2.WorkerCompleteComputeRequestRequest(
            namespace=namespace,
            request_id=request_id,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_generation=lease_generation,
            response_envelope=_compute_response_envelope(
                kind=kind,
                request_id=request_id,
                status=enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED,
                response=response,
            ),
        )
        if artifact_path is not None:
            request.artifact_path = artifact_path
        if artifact_name is not None:
            request.artifact_name = artifact_name
        if artifact_content_type is not None:
            request.artifact_content_type = artifact_content_type
        if engine_run_finalization is not None:
            request.engine_run_finalization.CopyFrom(_engine_run_finalization_proto(engine_run_finalization))
        timeout = self._control_timeout(timeout_seconds)
        self._call(lambda: self._stub.CompleteComputeRequest(request, timeout=timeout, metadata=self._metadata()))

    def fail_compute_request(
        self,
        *,
        namespace: str,
        request_id: str,
        kind: enums_pb2.ComputeRequestKind,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        error_message: str,
        error: compute_pb2.ComputeErrorResult,
        engine_run_finalization: ComputeWorkerRunFinalization | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        timeout = self._control_timeout(timeout_seconds)
        request = worker_runtime_pb2.WorkerFailComputeRequestRequest(
            namespace=namespace,
            request_id=request_id,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_generation=lease_generation,
            error_message=error_message,
            response_envelope=_compute_response_envelope(
                kind=kind,
                request_id=request_id,
                status=enums_pb2.COMPUTE_REQUEST_STATUS_FAILED,
                response=compute_pb2.ComputeResponse(error=error),
                error_message=error_message,
            ),
        )
        if engine_run_finalization is not None:
            request.engine_run_finalization.CopyFrom(_engine_run_finalization_proto(engine_run_finalization))
        self._call(
            lambda: self._stub.FailComputeRequest(
                request,
                timeout=timeout,
                metadata=self._metadata(),
            )
        )

    def register_datasource_stage(
        self,
        *,
        namespace: str,
        datasource_id: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        prefix_url: str,
        manifest_url: str,
        catalog_identifier: str,
        compute_request_id: str | None = None,
        job_id: str | None = None,
        build_id: str | None = None,
    ) -> None:
        if (compute_request_id is None) == (job_id is None) or (job_id is not None and build_id is None):
            raise ValueError("Datasource staging requires one complete compute or build claim")
        request = worker_runtime_pb2.WorkerRegisterDatasourceStageRequest(
            namespace=namespace,
            datasource_id=datasource_id,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_generation=lease_generation,
            prefix_url=prefix_url,
            artifact_url=manifest_url,
            catalog_identifier=catalog_identifier,
        )
        if compute_request_id is not None:
            request.compute_request_id = compute_request_id
        if job_id is not None:
            request.job_id = job_id
        if build_id is not None:
            request.build_id = build_id
        response = self._call(lambda: self._stub.RegisterDatasourceStage(request, timeout=self._control_timeout(), metadata=self._metadata()))
        if not response.value:
            raise RuntimeError("Datasource staging cleanup intents were not accepted")

    def claim_storage_cleanups(self, *, namespace: str, limit: int = 1) -> list[StorageCleanupClaim]:
        response = self._call(
            lambda: self._stub.ClaimStorageCleanup(
                worker_runtime_pb2.WorkerClaimStorageCleanupRequest(namespace=namespace, limit=limit),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            )
        )
        return [
            StorageCleanupClaim(
                namespace=row.claim.namespace,
                event_id=row.claim.event_id,
                claim_token=row.claim.claim_token,
                lease_generation=row.claim.lease_generation,
                resource_id=row.resource_id,
                url=row.url,
                is_prefix=row.is_prefix,
                catalog_identifier=row.catalog_identifier if row.HasField("catalog_identifier") else None,
                catalog_type=row.catalog_type if row.HasField("catalog_type") else None,
                catalog_uri=row.catalog_uri if row.HasField("catalog_uri") else None,
                warehouse=row.warehouse if row.HasField("warehouse") else None,
                catalog_namespace=row.catalog_namespace if row.HasField("catalog_namespace") else None,
                catalog_table=row.catalog_table if row.HasField("catalog_table") else None,
                catalog_family_prefix=row.catalog_family_prefix if row.HasField("catalog_family_prefix") else None,
            )
            for row in response.cleanups
        ]

    async def claim_storage_cleanups_async(self, *, namespace: str, limit: int = 1) -> list[StorageCleanupClaim]:
        request = worker_runtime_pb2.WorkerClaimStorageCleanupRequest(namespace=namespace, limit=limit)
        worker_stub, _coordinator_stub = self._async_stubs()
        response = await self._call_async(
            worker_stub.ClaimStorageCleanup(request, timeout=self._control_timeout(), metadata=self._metadata()),
            operation="ClaimStorageCleanup",
        )
        return [
            StorageCleanupClaim(
                namespace=row.claim.namespace,
                event_id=row.claim.event_id,
                claim_token=row.claim.claim_token,
                lease_generation=row.claim.lease_generation,
                resource_id=row.resource_id,
                url=row.url,
                is_prefix=row.is_prefix,
                catalog_identifier=row.catalog_identifier if row.HasField("catalog_identifier") else None,
                catalog_type=row.catalog_type if row.HasField("catalog_type") else None,
                catalog_uri=row.catalog_uri if row.HasField("catalog_uri") else None,
                warehouse=row.warehouse if row.HasField("warehouse") else None,
                catalog_namespace=row.catalog_namespace if row.HasField("catalog_namespace") else None,
                catalog_table=row.catalog_table if row.HasField("catalog_table") else None,
                catalog_family_prefix=row.catalog_family_prefix if row.HasField("catalog_family_prefix") else None,
            )
            for row in response.cleanups
        ]

    def authorize_storage_cleanup(self, claim: StorageCleanupClaim) -> bool:
        response = self._call(lambda: self._stub.AuthorizeStorageCleanup(claim.protocol_claim(), timeout=self._control_timeout(), metadata=self._metadata()))
        return bool(response.value)

    async def authorize_storage_cleanup_async(self, claim: StorageCleanupClaim) -> bool:
        worker_stub, _coordinator_stub = self._async_stubs()
        response = await self._call_async(
            worker_stub.AuthorizeStorageCleanup(claim.protocol_claim(), timeout=self._control_timeout(), metadata=self._metadata()),
            operation="AuthorizeStorageCleanup",
        )
        return bool(response.value)

    def complete_storage_cleanup(self, claim: StorageCleanupClaim, *, error: str | None = None) -> bool:
        request = worker_runtime_pb2.WorkerCompleteStorageCleanupRequest(claim=claim.protocol_claim())
        if error is not None:
            request.error = error
        response = self._call(lambda: self._stub.CompleteStorageCleanup(request, timeout=self._control_timeout(), metadata=self._metadata()))
        return bool(response.value)

    async def complete_storage_cleanup_async(self, claim: StorageCleanupClaim, *, error: str | None = None) -> bool:
        request = worker_runtime_pb2.WorkerCompleteStorageCleanupRequest(claim=claim.protocol_claim())
        if error is not None:
            request.error = error
        worker_stub, _coordinator_stub = self._async_stubs()
        response = await self._call_async(
            worker_stub.CompleteStorageCleanup(request, timeout=self._control_timeout(), metadata=self._metadata()),
            operation="CompleteStorageCleanup",
        )
        return bool(response.value)

    def publish_datasource_create(
        self,
        *,
        namespace: str,
        datasource_id: str,
        name: str,
        description: str | None,
        source_type: str,
        config: dict[str, object],
        compute_request_id: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        owner_id: str | None = None,
        schema_info: datasource_pb2.SchemaInfo | None = None,
    ):
        from datasources.schemas import DataSourceRecord

        request = worker_runtime_pb2.WorkerPublishDatasourceCreateRequest(
            namespace=namespace,
            datasource_id=datasource_id,
            name=name,
            source_type=enum_to_proto_value("DATA_SOURCE_TYPE", source_type),
            config=dict_to_struct(config),
            compute_request_id=compute_request_id,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_generation=lease_generation,
        )
        if description is not None:
            request.description = description
        if owner_id is not None:
            request.owner_id = owner_id
        if schema_info is not None:
            request.schema_info.CopyFrom(schema_info)
        response = self._call(lambda: self._stub.PublishDatasourceCreate(request, timeout=self._timeout_seconds, metadata=self._metadata()))
        return DataSourceRecord.model_validate(_datasource_record_payload(response.datasource))

    def publish_datasource_ingest(
        self,
        *,
        namespace: str,
        datasource_id: str,
        config: dict[str, object],
        expected_revision: int,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        schema_info: datasource_pb2.SchemaInfo | None = None,
        compute_request_id: str | None = None,
        job_id: str | None = None,
        build_id: str | None = None,
    ):
        from datasources.schemas import DataSourceRecord

        request = worker_runtime_pb2.WorkerPublishDatasourceIngestRequest(
            namespace=namespace,
            datasource_id=datasource_id,
            config=dict_to_struct(config),
            expected_revision=expected_revision,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_generation=lease_generation,
        )
        if schema_info is not None:
            request.schema_info.CopyFrom(schema_info)
        if compute_request_id is not None:
            request.compute_request_id = compute_request_id
        if job_id is not None:
            request.job_id = job_id
        if build_id is not None:
            request.build_id = build_id
        response = self._call(lambda: self._stub.PublishDatasourceIngest(request, timeout=self._timeout_seconds, metadata=self._metadata()))
        return DataSourceRecord.model_validate(_datasource_record_payload(response.datasource))

    def publish_datasource_schema_cache(
        self,
        *,
        namespace: str,
        datasource_id: str,
        schema_info: datasource_pb2.SchemaInfo,
        expected_revision: int,
        compute_request_id: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
    ) -> datasource_pb2.SchemaInfo:
        request = worker_runtime_pb2.WorkerPublishDatasourceSchemaCacheRequest(
            namespace=namespace,
            datasource_id=datasource_id,
            schema_info=schema_info,
            expected_revision=expected_revision,
            compute_request_id=compute_request_id,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_generation=lease_generation,
        )
        response = self._call(lambda: self._stub.PublishDatasourceSchemaCache(request, timeout=self._timeout_seconds, metadata=self._metadata()))
        return response.schema_info

    def datasource_metadata(self, *, namespace: str, datasource_id: str) -> DatasourceMetadata:
        snapshot = _datasource_metadata_snapshot.get()
        if snapshot is not None and (namespace, datasource_id) in snapshot:
            return snapshot[(namespace, datasource_id)]
        response = self._call(
            lambda: self._stub.GetDatasourceMetadata(
                worker_runtime_pb2.WorkerDatasourceMetadataRequest(namespace=namespace, datasource_id=datasource_id),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            )
        )
        return DatasourceMetadata(
            found=response.found,
            id=_optional_str(response, "id"),
            name=_optional_str(response, "name"),
            source_type=_optional_proto_enum_name(response, "source_type", enums_pb2.DataSourceType, "DATA_SOURCE_TYPE"),
            config=optional_struct_to_dict(response, "config"),
            schema_cache=_schema_info_payload(response.schema_info) if response.HasField("schema_info") else None,
            is_hidden=_optional_bool(response, "is_hidden"),
            revision=int(response.revision) if response.HasField("revision") else None,
            description=_optional_str(response, "description"),
            column_descriptions=dict(response.column_descriptions) if response.column_descriptions else {},
            created_by=_optional_str(response, "created_by"),
        )

    def udf_codes(self, *, namespace: str, udf_ids: list[str]) -> dict[str, str]:
        response = self._call(
            lambda: self._stub.GetUdfCodes(
                worker_runtime_pb2.WorkerUdfCodesRequest(namespace=namespace, udf_ids=udf_ids),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            )
        )
        return dict(response.codes)

    def engine_credentials(self, *, namespace: str, role: str) -> worker_runtime_pb2.WorkerComputeWorkerCredentialsResponse:
        return self._call(
            lambda: self._stub.GetComputeWorkerCredentials(
                worker_runtime_pb2.WorkerComputeWorkerCredentialsRequest(namespace=namespace, role=role),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            )
        )

    def analysis_name(self, *, namespace: str, analysis_id: str) -> str | None:
        response = self._call(
            lambda: self._stub.GetAnalysisMetadata(
                worker_runtime_pb2.WorkerAnalysisMetadataRequest(namespace=namespace, analysis_id=analysis_id),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            )
        )
        if not response.found:
            return None
        return _optional_str(response, "name")

    def build_cancel_status(self, *, namespace: str, build_id: str) -> tuple[bool, str | None, str | None]:
        response = self._call(
            lambda: self._stub.GetBuildCancelStatus(
                worker_runtime_pb2.WorkerBuildCancelStatusRequest(namespace=namespace, build_id=build_id),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            )
        )
        return (response.cancelled, _optional_timestamp_iso(response, "cancelled_at"), _optional_str(response, "cancelled_by"))

    def update_build_result(
        self,
        *,
        namespace: str,
        build_id: str,
        job_id: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        result_json: dict[str, object],
    ) -> None:
        try:
            self._call(
                lambda: self._stub.UpdateBuildResult(
                    worker_runtime_pb2.WorkerUpdateBuildResultRequest(
                        namespace=namespace,
                        build_id=build_id,
                        job_id=job_id,
                        worker_id=worker_id,
                        claim_token=claim_token,
                        lease_generation=lease_generation,
                        result=dict_to_struct(result_json),
                    ),
                    timeout=self._timeout_seconds,
                    metadata=self._metadata(),
                )
            )
        except BackendWorkerRpcError as exc:
            if exc.error_code == "FAILED_PRECONDITION":
                raise BuildJobLeaseLost(f"Build job {job_id} result update was rejected because its lease is no longer active") from exc
            raise

    def upsert_output_datasource(
        self,
        *,
        namespace: str,
        result_id: str,
        name: str,
        source_type: str,
        config: dict[str, object],
        schema_cache: dict[str, object],
        analysis_id: str | None,
        is_hidden: bool | None,
        keep_schema_cache: bool,
        job_id: str | None,
        build_id: str | None,
        worker_id: str | None,
        claim_token: str | None,
        lease_generation: int | None,
        build_result_json: dict[str, object] | None,
        notification_deliveries: Sequence[Mapping[str, object]],
    ) -> DatasourceMetadata:
        request = worker_runtime_pb2.WorkerUpsertOutputDatasourceRequest(
            namespace=namespace,
            result_id=result_id,
            name=name,
            source_type=enum_to_proto_value("DATA_SOURCE_TYPE", source_type),
            config=dict_to_struct(config),
            schema_info=_schema_info_proto(schema_cache),
            keep_schema_cache=keep_schema_cache,
            notification_delivery=[_notification_delivery_proto(delivery) for delivery in notification_deliveries],
        )
        claim_values = (job_id, build_id, worker_id, claim_token, lease_generation, build_result_json)
        if any(value is not None for value in claim_values):
            if any(value is None for value in claim_values):
                raise ValueError("Output publication claim fields must be provided together")
            request.job_id = cast(str, job_id)
            request.build_id = cast(str, build_id)
            request.worker_id = cast(str, worker_id)
            request.claim_token = cast(str, claim_token)
            request.lease_generation = cast(int, lease_generation)
            request.build_result.CopyFrom(dict_to_struct(cast(dict[str, object], build_result_json)))
        if analysis_id is not None:
            request.analysis_id = analysis_id
        if is_hidden is not None:
            request.is_hidden = is_hidden
        try:
            response = self._call(lambda: self._stub.UpsertOutputDatasource(request, timeout=self._timeout_seconds, metadata=self._metadata()))
        except BackendWorkerRpcError as exc:
            if exc.error_code == "FAILED_PRECONDITION" and job_id is not None:
                raise BuildJobLeaseLost(f"Build job {job_id} output publication was rejected because its lease is no longer active") from exc
            raise
        return DatasourceMetadata(
            found=True,
            id=response.datasource_id,
            name=response.datasource_name,
            source_type=source_type,
            config=config,
            schema_cache=schema_cache,
            is_hidden=response.is_hidden,
        )

    def list_healthchecks(self, *, namespace: str, datasource_id: str) -> list[HealthCheckSpec]:
        response = self._call(
            lambda: self._stub.ListHealthChecks(
                worker_runtime_pb2.WorkerListHealthChecksRequest(namespace=namespace, datasource_id=datasource_id),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return [
            HealthCheckSpec(
                id=check.id,
                name=check.name,
                check_type=proto_value_to_enum_name(enums_pb2.HealthCheckType, "HEALTH_CHECK_TYPE", check.check_type),
                config=struct_to_dict(check.config),
                critical=check.critical,
            )
            for check in response.checks
        ]

    def record_healthcheck_results(self, *, namespace: str, results: list[Mapping[str, object]]) -> int:
        request = worker_runtime_pb2.WorkerRecordHealthCheckResultsRequest(
            namespace=namespace,
            results=[
                worker_runtime_pb2.WorkerHealthCheckResultPayload(
                    healthcheck_id=_required_mapping_str(result, "healthcheck_id"),
                    passed=_required_mapping_bool(result, "passed"),
                    message=_required_mapping_str(result, "message"),
                    details=dict_to_struct(_required_mapping_dict(result, "details")),
                    checked_at=datetime_to_timestamp(datetime.fromisoformat(_required_mapping_str(result, "checked_at"))),
                )
                for result in results
            ],
        )
        return int(self._call(lambda: self._stub.RecordHealthCheckResults(request, timeout=self._timeout_seconds, metadata=self._metadata())).count)

    def create_engine_run(
        self,
        *,
        namespace: str,
        analysis_id: str | None,
        datasource_id: str,
        kind: str,
        status: str,
        request_json: dict[str, object],
        result_json: dict[str, object] | None = None,
        error_message: str | None = None,
        created_at: datetime | None = None,
        completed_at: datetime | None = None,
        duration_ms: int | None = None,
        step_timings: dict[str, float] | None = None,
        query_plan: str | None = None,
        execution_entries: list[dict[str, object]] | None = None,
        progress: float = 0.0,
        current_step: str | None = None,
        triggered_by: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        request = worker_runtime_pb2.WorkerCreateComputeWorkerRunRequest(
            namespace=namespace,
            datasource_id=datasource_id,
            kind=enum_to_proto_value("COMPUTE_WORKER_RUN_KIND", kind),
            status=enum_to_proto_value("COMPUTE_WORKER_RUN_STATUS", status),
            request=dict_to_struct(request_json),
            execution_entry=[_engine_run_execution_entry_proto(entry) for entry in execution_entries or []],
            progress=progress,
        )
        if analysis_id is not None:
            request.analysis_id = analysis_id
        if result_json is not None:
            request.result.CopyFrom(dict_to_struct(result_json))
        if error_message is not None:
            request.error_message = error_message
        if created_at is not None:
            request.created_at.CopyFrom(datetime_to_timestamp(created_at))
        if completed_at is not None:
            request.completed_at.CopyFrom(datetime_to_timestamp(completed_at))
        if duration_ms is not None:
            request.duration_ms = duration_ms
        if step_timings is not None:
            request.timing_by_key.update({str(key): float(value) for key, value in step_timings.items()})
        if query_plan is not None:
            request.query_plan = query_plan
        if current_step is not None:
            request.current_step = current_step
        if triggered_by is not None:
            request.triggered_by = triggered_by
        if idempotency_key is not None:
            request.idempotency_key = idempotency_key

        def create():
            return self._stub.CreateComputeWorkerRun(request, timeout=self._control_timeout(), metadata=self._metadata())

        if idempotency_key is not None:
            return self._call_with_reconnect(create, operation="CreateComputeWorkerRun").id
        return self._call(create).id

    def update_engine_run(
        self,
        *,
        namespace: str,
        run_id: str,
        fields: dict[str, object],
        merge_result_json: bool = True,
    ) -> str:
        response = self._call(
            lambda: self._stub.UpdateComputeWorkerRun(
                worker_runtime_pb2.WorkerUpdateComputeWorkerRunRequest(
                    namespace=namespace,
                    run_id=run_id,
                    merge_result=merge_result_json,
                    update=_engine_run_update_proto(fields),
                ),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            )
        )
        return response.id

    def engine_run_state(self, *, namespace: str, run_id: str) -> dict[str, object] | None:
        response = self._call(
            lambda: self._stub.GetComputeWorkerRunState(
                worker_runtime_pb2.WorkerComputeWorkerRunStateRequest(namespace=namespace, run_id=run_id),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            )
        )
        if not response.found:
            return None
        return {
            "status": _optional_proto_enum_name(response, "status", enums_pb2.ComputeWorkerRunStatus, "COMPUTE_WORKER_RUN_STATUS"),
            "result_json": optional_struct_to_dict(response, "result") or {},
            "cancelled_at": _optional_timestamp_iso(response, "cancelled_at"),
            "cancelled_by": _optional_str(response, "cancelled_by"),
        }

    def fail_build_job(self, *, job_id: str, build_id: str, namespace: str, worker_id: str, claim_token: str, lease_generation: int, error: str) -> bool:
        response = self._call_with_reconnect(
            lambda: self._stub.FailBuildJob(
                worker_runtime_pb2.WorkerFailBuildJobRequest(
                    job_id=job_id,
                    namespace=namespace,
                    error=error,
                    claim_token=claim_token,
                    lease_generation=lease_generation,
                    worker_id=worker_id,
                    build_id=build_id,
                ),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            ),
            operation="FailBuildJob",
        )
        return bool(response.value)

    async def fail_build_job_async(
        self,
        *,
        job_id: str,
        build_id: str,
        namespace: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        error: str,
    ) -> bool:
        request = worker_runtime_pb2.WorkerFailBuildJobRequest(
            job_id=job_id,
            namespace=namespace,
            error=error,
            claim_token=claim_token,
            lease_generation=lease_generation,
            worker_id=worker_id,
            build_id=build_id,
        )
        worker_stub, _coordinator_stub = self._async_stubs()
        response = await self._call_with_reconnect_async(
            lambda: worker_stub.FailBuildJob(request, timeout=self._control_timeout(), metadata=self._metadata()),
            operation="FailBuildJob",
        )
        return bool(response.value)

    def finalize_build_job(self, *, job_id: str, build_id: str, namespace: str, worker_id: str, claim_token: str, lease_generation: int) -> bool:
        response = self._call_with_reconnect(
            lambda: self._stub.FinalizeBuildJob(
                worker_runtime_pb2.WorkerFinalizeBuildJobRequest(
                    job_id=job_id,
                    build_id=build_id,
                    namespace=namespace,
                    claim_token=claim_token,
                    lease_generation=lease_generation,
                    worker_id=worker_id,
                ),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            ),
            operation="FinalizeBuildJob",
        )
        return bool(response.value)

    async def finalize_build_job_async(
        self,
        *,
        job_id: str,
        build_id: str,
        namespace: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
    ) -> bool:
        request = worker_runtime_pb2.WorkerFinalizeBuildJobRequest(
            job_id=job_id,
            build_id=build_id,
            namespace=namespace,
            claim_token=claim_token,
            lease_generation=lease_generation,
            worker_id=worker_id,
        )
        worker_stub, _coordinator_stub = self._async_stubs()
        response = await self._call_with_reconnect_async(
            lambda: worker_stub.FinalizeBuildJob(request, timeout=self._control_timeout(), metadata=self._metadata()),
            operation="FinalizeBuildJob",
        )
        return bool(response.value)

    def release_build_worker_jobs(self, *, worker_id: str, namespace: str) -> int:
        request = common_pb2.RuntimeWorkerRequest(worker_id=worker_id, protocol_version=2, target_namespace=namespace)
        return int(self._call(lambda: self._stub.ReleaseBuildWorkerJobs(request, timeout=self._control_timeout(), metadata=self._metadata())).count)

    def queued_build_job_count(self, *, namespace: str) -> int:
        return int(
            self._call(
                lambda: self._stub.GetQueuedBuildJobCount(
                    common_pb2.EmptyRequest(namespace=namespace),
                    timeout=self._control_timeout(),
                    metadata=self._metadata(),
                )
            ).count
        )

    def reconcile_expired_build_jobs(self, *, namespace: str) -> int:
        return int(
            self._call(
                lambda: self._stub.ReconcileExpiredBuildJobs(
                    common_pb2.EmptyRequest(namespace=namespace),
                    timeout=self._control_timeout(),
                    metadata=self._metadata(),
                )
            ).count
        )

    async def reconcile_expired_build_jobs_async(self, *, namespace: str) -> int:
        worker_stub, _coordinator_stub = self._async_stubs()
        response = await self._call_async(
            worker_stub.ReconcileExpiredBuildJobs(
                common_pb2.EmptyRequest(namespace=namespace),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            ),
            operation="ReconcileExpiredBuildJobs",
        )
        return int(response.count)

    def reconcile_expired_compute_requests(self, *, namespace: str) -> int:
        return int(
            self._call(
                lambda: self._stub.ReconcileExpiredComputeRequests(
                    common_pb2.EmptyRequest(namespace=namespace),
                    timeout=self._control_timeout(),
                    metadata=self._metadata(),
                )
            ).count
        )

    async def reconcile_expired_compute_requests_async(self, *, namespace: str) -> int:
        worker_stub, _coordinator_stub = self._async_stubs()
        response = await self._call_async(
            worker_stub.ReconcileExpiredComputeRequests(
                common_pb2.EmptyRequest(namespace=namespace),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            ),
            operation="ReconcileExpiredComputeRequests",
        )
        return int(response.count)

    def idle_build_worker_pids(self) -> set[int]:
        response = self._call(lambda: self._stub.GetIdleBuildWorkerPids(common_pb2.EmptyRequest(), timeout=self._control_timeout(), metadata=self._metadata()))
        return set(response.pids)

    def pending_runtime_work_namespaces(self, *, work_kinds: tuple[str, ...] = ()) -> list[str]:
        response = self._call(
            lambda: self._stub.ListPendingRuntimeWorkNamespaces(
                worker_runtime_pb2.WorkerPendingRuntimeWorkNamespacesRequest(kinds=work_kinds),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            )
        )
        return list(response.namespaces)

    async def pending_runtime_work_namespaces_async(self, *, work_kinds: tuple[str, ...] = ()) -> list[str]:
        worker_stub, _coordinator_stub = self._async_stubs()
        response = await self._call_async(
            worker_stub.ListPendingRuntimeWorkNamespaces(
                worker_runtime_pb2.WorkerPendingRuntimeWorkNamespacesRequest(kinds=work_kinds),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            ),
            operation="ListPendingRuntimeWorkNamespaces",
        )
        return list(response.namespaces)

    def persist_build_event(
        self,
        *,
        namespace: str,
        build_id: str,
        job_id: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        event: dict[str, object],
        resource_config_json: dict[str, object] | None = None,
    ) -> int | None:
        request = worker_runtime_pb2.WorkerPersistBuildEventRequest(
            namespace=namespace,
            build_id=build_id,
            job_id=job_id,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_generation=lease_generation,
            build_event=_build_event_proto(namespace, event),
        )
        if resource_config_json is not None:
            request.build_resource_config.CopyFrom(_build_resource_config_proto(resource_config_json))
        # Event publication is intentionally not retried here: a successful
        # transaction followed by a lost response must not append the same
        # event twice. The surrounding build path turns an unavailable event
        # publication into an explicit durable failure instead.
        response = self._call(lambda: self._stub.PersistBuildEvent(request, timeout=self._control_timeout(), metadata=self._metadata()))
        return int(response.sequence) if response.HasField("sequence") else None

    async def persist_build_event_async(
        self,
        *,
        namespace: str,
        build_id: str,
        job_id: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
        event: dict[str, object],
        resource_config_json: dict[str, object] | None = None,
    ) -> int | None:
        request = worker_runtime_pb2.WorkerPersistBuildEventRequest(
            namespace=namespace,
            build_id=build_id,
            job_id=job_id,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_generation=lease_generation,
            build_event=_build_event_proto(namespace, event),
        )
        if resource_config_json is not None:
            request.build_resource_config.CopyFrom(_build_resource_config_proto(resource_config_json))
        worker_stub, _coordinator_stub = self._async_stubs()
        response = await self._call_async(
            worker_stub.PersistBuildEvent(request, timeout=self._control_timeout(), metadata=self._metadata()),
            operation="PersistBuildEvent",
        )
        return int(response.sequence) if response.HasField("sequence") else None

    def start_build_run(self, *, namespace: str, build_id: str, job_id: str, worker_id: str, claim_token: str, lease_generation: int) -> StartedBuildRun | None:
        response = self._call_with_reconnect(
            lambda: self._stub.StartBuildRun(
                worker_runtime_pb2.WorkerStartBuildRunRequest(
                    namespace=namespace,
                    build_id=build_id,
                    job_id=job_id,
                    worker_id=worker_id,
                    claim_token=claim_token,
                    lease_generation=lease_generation,
                ),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            ),
            operation="StartBuildRun",
        )
        return _started_build_run_from_response(response)

    async def start_build_run_async(
        self,
        *,
        namespace: str,
        build_id: str,
        job_id: str,
        worker_id: str,
        claim_token: str,
        lease_generation: int,
    ) -> StartedBuildRun | None:
        request = worker_runtime_pb2.WorkerStartBuildRunRequest(
            namespace=namespace,
            build_id=build_id,
            job_id=job_id,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_generation=lease_generation,
        )
        worker_stub, _coordinator_stub = self._async_stubs()
        response = await self._call_with_reconnect_async(
            lambda: worker_stub.StartBuildRun(request, timeout=self._control_timeout(), metadata=self._metadata()),
            operation="StartBuildRun",
        )
        return _started_build_run_from_response(response)

    def persist_compute_worker_snapshot(self, *, worker_id: str, namespace: str, statuses: Sequence[ComputeWorkerStatusInfo]) -> int:
        response = self._call(
            lambda: self._stub.PersistComputeWorkerSnapshot(
                worker_runtime_pb2.WorkerPersistComputeWorkerSnapshotRequest(
                    worker_id=worker_id,
                    namespace=namespace,
                    engine_status=[_engine_status_result_proto(status) for status in statuses],
                ),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            )
        )
        return int(response.count)

    def pending_datasource_deletes(self, *, namespace: str) -> list[PendingDatasourceDelete]:
        response = self._call(
            lambda: self._stub.ListPendingDatasourceDeletes(
                common_pb2.EmptyRequest(namespace=namespace),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            )
        )
        return [PendingDatasourceDelete(namespace=delete.namespace, datasource_id=delete.datasource_id) for delete in response.deletes]

    async def pending_datasource_deletes_async(self, *, namespace: str) -> list[PendingDatasourceDelete]:
        worker_stub, _coordinator_stub = self._async_stubs()
        response = await self._call_async(
            worker_stub.ListPendingDatasourceDeletes(
                common_pb2.EmptyRequest(namespace=namespace),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            ),
            operation="ListPendingDatasourceDeletes",
        )
        return [PendingDatasourceDelete(namespace=delete.namespace, datasource_id=delete.datasource_id) for delete in response.deletes]

    def finalize_datasource_delete(self, *, namespace: str, datasource_id: str) -> bool:
        response = self._call(
            lambda: self._stub.FinalizeDatasourceDelete(
                worker_runtime_pb2.WorkerFinalizeDatasourceDeleteRequest(namespace=namespace, datasource_id=datasource_id),
                timeout=self._control_timeout(),
                metadata=self._metadata(),
            )
        )
        return response.deleted

    async def finalize_datasource_delete_async(self, *, namespace: str, datasource_id: str) -> bool:
        request = worker_runtime_pb2.WorkerFinalizeDatasourceDeleteRequest(namespace=namespace, datasource_id=datasource_id)
        worker_stub, _coordinator_stub = self._async_stubs()
        response = await self._call_async(
            worker_stub.FinalizeDatasourceDelete(request, timeout=self._control_timeout(), metadata=self._metadata()),
            operation="FinalizeDatasourceDelete",
        )
        return bool(response.deleted)

    def telegram_enabled(self) -> bool:
        response = self._call(lambda: self._stub.GetTelegramSettings(common_pb2.EmptyRequest(), timeout=self._timeout_seconds, metadata=self._metadata()))
        return response.enabled

    def send_email(
        self,
        *,
        namespace: str,
        to: str,
        subject: str,
        body: str,
        attachments: list[Mapping[str, object]] | None = None,
    ) -> bool:
        response = self._call(
            lambda: self._stub.SendEmail(
                worker_runtime_pb2.WorkerSendEmailRequest(
                    namespace=namespace,
                    to=to,
                    subject=subject,
                    body=body,
                    attachments=_serialize_attachments(attachments or []),
                ),
                timeout=self._timeout_seconds,
                metadata=self._metadata(),
            )
        )
        return response.value

    def send_telegram(
        self,
        *,
        namespace: str,
        chat_id: str,
        message: str,
        bot_token: str | None = None,
        attachments: list[Mapping[str, object]] | None = None,
    ) -> bool:
        request = worker_runtime_pb2.WorkerSendTelegramRequest(
            namespace=namespace,
            chat_id=chat_id,
            message=message,
            attachments=_serialize_attachments(attachments or []),
        )
        if bot_token is not None:
            request.bot_token = bot_token
        response = self._call(lambda: self._stub.SendTelegram(request, timeout=self._timeout_seconds, metadata=self._metadata()))
        return response.value

    def generate_ai(
        self,
        *,
        provider: str,
        prompts: list[str],
        model: str,
        endpoint_url: str | None,
        api_key: str | None,
        options: dict[str, object],
    ) -> list[str]:
        request = worker_runtime_pb2.WorkerGenerateAIRequest(
            provider=enum_to_proto_value("AI_PROVIDER", provider),
            prompts=prompts,
            model=model,
            options=dict_to_struct(options),
        )
        if endpoint_url is not None:
            request.endpoint_url = endpoint_url
        if api_key is not None:
            request.api_key = api_key
        response = self._call(lambda: self._stub.GenerateAI(request, timeout=self._timeout_seconds, metadata=self._metadata()))
        return list(response.outputs)

    def telegram_targets(self, *, namespace: str, datasource_id: str | None = None, active_subscribers: bool = False) -> list[TelegramTarget]:
        request = worker_runtime_pb2.WorkerTelegramTargetsRequest(namespace=namespace, active_subscribers=active_subscribers)
        if datasource_id is not None:
            request.datasource_id = datasource_id
        response = self._call(lambda: self._stub.GetTelegramTargets(request, timeout=self._timeout_seconds, metadata=self._metadata()))
        return [TelegramTarget(chat_id=target.chat_id, bot_token=target.bot_token) for target in response.targets]

    def close(self) -> None:
        """Release the client. The channel is process-shared and stays open."""

    def __enter__(self) -> WorkerRuntimeClient:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def _metadata(self) -> tuple[tuple[str, str], ...]:
        raw_generation = os.environ.get("RUNTIME_COORDINATOR_GENERATION", "").strip()
        try:
            generation = int(raw_generation)
        except ValueError as exc:
            raise RuntimeError("Worker runtime RPCs require an active RUNTIME_COORDINATOR_GENERATION") from exc
        if generation < 1:
            raise RuntimeError("RUNTIME_COORDINATOR_GENERATION must be a positive integer")
        return self._metadata_for_generation(generation)

    def _token_metadata(self) -> tuple[tuple[str, str], ...]:
        return ((_TOKEN_METADATA_KEY, self._token),)

    def _metadata_for_generation(self, generation: int) -> tuple[tuple[str, str], ...]:
        if generation < 1:
            raise ValueError("Runtime coordinator generation must be a positive integer")
        return (
            (_TOKEN_METADATA_KEY, self._token),
            (_COORDINATOR_GENERATION_METADATA_KEY, str(generation)),
        )

    def _control_timeout(self, timeout_seconds: float | None = None) -> float:
        requested = self._timeout_seconds if timeout_seconds is None else float(timeout_seconds)
        return min(max(requested, 0.1), _CONTROL_RPC_TIMEOUT_SECONDS)

    def _call(self, fn: Callable[[], _T]) -> _T:
        try:
            return fn()
        except grpc.RpcError as exc:
            raise _rpc_error_from_grpc_error(exc, target=self._target) from exc

    def _call_with_reconnect(self, fn: Callable[[], _T], *, operation: str) -> _T:
        """Retry idempotent runtime RPCs while the API reconnects.

        Callers must guarantee that repeated execution has the same durable
        effect, either through a lease generation or an explicit idempotency
        key. Non-idempotent operations use :meth:`_call` instead.
        """
        deadline = time.monotonic() + _BUILD_LIFECYCLE_RETRY_SECONDS
        delay = 0.25
        while True:
            try:
                return self._call(fn)
            except BackendWorkerRpcError as exc:
                if exc.error_code not in _TRANSIENT_RECONNECT_CODES or time.monotonic() >= deadline:
                    raise
                remaining = max(deadline - time.monotonic(), 0.05)
                logger.warning(
                    "%s unavailable; retrying runtime lifecycle RPC in %.2fs: %s",
                    operation,
                    min(delay, remaining),
                    exc.error,
                )
                time.sleep(min(delay, remaining))
                delay = min(delay * 2, 2.0)

    async def _call_with_reconnect_async(self, fn: Callable[[], Awaitable[_T]], *, operation: str) -> _T:
        deadline = asyncio.get_running_loop().time() + _BUILD_LIFECYCLE_RETRY_SECONDS
        delay = 0.25
        while True:
            try:
                return await self._call_async(fn(), operation=operation)
            except BackendWorkerRpcError as exc:
                remaining = deadline - asyncio.get_running_loop().time()
                if exc.error_code not in _TRANSIENT_RECONNECT_CODES or remaining <= 0:
                    raise
                logger.warning("%s unavailable; retrying runtime lifecycle RPC in %.2fs: %s", operation, min(delay, remaining), exc.error)
                await asyncio.sleep(min(delay, remaining))
                delay = min(delay * 2, 2.0)

    def _call_registration(self, fn: Callable[[], _T], *, retry_seconds: float | None = None) -> _T:
        deadline = time.monotonic() + (self._registration_retry_seconds if retry_seconds is None else max(retry_seconds, 0.0))
        while True:
            try:
                return self._call(fn)
            except BackendWorkerRpcError as exc:
                if time.monotonic() >= deadline or exc.error_code not in {"UNAVAILABLE", "DEADLINE_EXCEEDED"}:
                    raise
                time.sleep(min(1.0, max(deadline - time.monotonic(), 0.05)))


def run_worker_heartbeat_loop(
    *,
    client: WorkerRuntimeClient,
    stop_signal: threading.Event,
    worker_id: str,
    kind: str,
    hostname: str,
    pid: int,
    capacity: int,
    heartbeat_seconds: float = 5.0,
    active_jobs: Callable[[], int] | None = None,
    on_reconnected: Callable[[], None] | None = None,
    on_registration_changed: Callable[[bool], None] | None = None,
) -> None:
    """Heartbeat a runtime worker and re-register it after API reconnects.

    The registration row is durable, but a lost API process can leave it
    stale while the worker and its engines are still alive. Re-registering
    before the next heartbeat clears that stale lease. The optional callback
    lets the owning manager publish its current engine projection again; a
    projection failure never stops the heartbeat loop.
    """
    needs_registration = False
    interval = max(float(heartbeat_seconds), 0.05)
    resync_lock = threading.Lock()
    resync_in_progress = False

    def schedule_resynchronization() -> None:
        nonlocal resync_in_progress
        if on_reconnected is None:
            return
        with resync_lock:
            if resync_in_progress:
                return
            resync_in_progress = True

        def _resynchronize() -> None:
            nonlocal resync_in_progress
            try:
                on_reconnected()
            except Exception:
                logger.warning("Runtime worker state resynchronization failed worker_id=%s", worker_id, exc_info=True)
            finally:
                with resync_lock:
                    resync_in_progress = False

        threading.Thread(
            target=_resynchronize,
            name=f"runtime-resync-{worker_id[-12:]}",
            daemon=True,
        ).start()

    while not stop_signal.wait(interval):
        if needs_registration:
            try:
                client.register_worker(
                    worker_id=worker_id,
                    kind=kind,
                    hostname=hostname,
                    pid=pid,
                    capacity=capacity,
                    active_jobs=active_jobs() if active_jobs is not None else 0,
                    retry_seconds=min(interval, 2.0),
                )
            except Exception as exc:
                logger.warning("Runtime worker re-registration failed worker_id=%s: %s", worker_id, exc)
                if on_registration_changed is not None:
                    on_registration_changed(False)
            else:
                needs_registration = False
                if on_registration_changed is not None:
                    on_registration_changed(True)
                schedule_resynchronization()
        try:
            client.heartbeat_worker(
                worker_id=worker_id,
                active_jobs=active_jobs() if active_jobs is not None else None,
                timeout_seconds=_HEARTBEAT_RPC_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            needs_registration = True
            if on_registration_changed is not None:
                on_registration_changed(False)
            logger.warning("Runtime worker heartbeat failed worker_id=%s: %s", worker_id, exc)


def _rpc_error_from_grpc_error(exc: grpc.RpcError, *, target: str) -> BackendWorkerRpcError:
    code = exc.code()
    details = exc.details() or f"Backend worker gRPC call to {target} failed"
    return BackendWorkerRpcError(
        status_code=_grpc_status_number(code),
        error=details,
        error_code=code.name,
        details={},
    )


def _grpc_status_number(code: grpc.StatusCode) -> int:
    return {
        grpc.StatusCode.OK: 200,
        grpc.StatusCode.CANCELLED: 499,
        grpc.StatusCode.UNKNOWN: 500,
        grpc.StatusCode.INVALID_ARGUMENT: 400,
        grpc.StatusCode.DEADLINE_EXCEEDED: 504,
        grpc.StatusCode.NOT_FOUND: 404,
        grpc.StatusCode.ALREADY_EXISTS: 409,
        grpc.StatusCode.PERMISSION_DENIED: 403,
        grpc.StatusCode.RESOURCE_EXHAUSTED: 429,
        grpc.StatusCode.FAILED_PRECONDITION: 412,
        grpc.StatusCode.ABORTED: 409,
        grpc.StatusCode.OUT_OF_RANGE: 400,
        grpc.StatusCode.UNIMPLEMENTED: 501,
        grpc.StatusCode.INTERNAL: 500,
        grpc.StatusCode.UNAVAILABLE: 503,
        grpc.StatusCode.DATA_LOSS: 500,
        grpc.StatusCode.UNAUTHENTICATED: 401,
    }[code]


def _worker(worker_id: str) -> common_pb2.RuntimeWorkerRequest:
    return common_pb2.RuntimeWorkerRequest(worker_id=worker_id, protocol_version=2)


def _optional_str(message: Any, field: str) -> str | None:
    return getattr(message, field) if message.HasField(field) else None


def _optional_bool(message: Any, field: str) -> bool | None:
    return getattr(message, field) if message.HasField(field) else None


def _optional_timestamp_iso(message: Any, field: str) -> str | None:
    value = optional_timestamp_to_datetime(message, field)
    return value.isoformat() if value is not None else None


def _optional_proto_enum_name(message: Any, field: str, enum_type: Any, prefix: str) -> str | None:
    if not message.HasField(field):
        return None
    return proto_value_to_enum_name(enum_type, prefix, getattr(message, field))


def _notification_delivery_proto(delivery: Mapping[str, object]) -> worker_runtime_pb2.WorkerNotificationDelivery:
    method = delivery.get("method")
    if method == "email":
        return worker_runtime_pb2.WorkerNotificationDelivery(
            email=worker_runtime_pb2.WorkerEmailDelivery(
                to=_required_mapping_str(delivery, "recipient"),
                subject=_required_mapping_str(delivery, "subject"),
                body=str(delivery.get("body", "")),
            )
        )
    if method == "telegram":
        telegram = worker_runtime_pb2.WorkerTelegramDelivery(
            chat_id=_required_mapping_str(delivery, "recipient"),
            message=_required_mapping_str(delivery, "message"),
        )
        token = delivery.get("bot_token")
        if isinstance(token, str) and token:
            telegram.bot_token = token
        return worker_runtime_pb2.WorkerNotificationDelivery(telegram=telegram)
    raise ValueError(f"Unsupported notification delivery method: {method!r}")


def _serialize_attachments(attachments: list[Mapping[str, object]]) -> list[common_pb2.NotificationAttachment]:
    serialized: list[common_pb2.NotificationAttachment] = []
    for attachment in attachments:
        content = attachment.get("content")
        if not isinstance(content, bytes):
            raise RuntimeError(f"Notification attachment content must be bytes: {attachment!r}")
        serialized.append(
            common_pb2.NotificationAttachment(
                filename=_required_mapping_str(attachment, "filename"),
                content_base64=base64.b64encode(content).decode("ascii"),
                content_type=str(attachment.get("content_type") or "text/plain"),
            )
        )
    return serialized


def _required_mapping_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Payload missing string {key}: {payload!r}")
    return value


def _mapping_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise RuntimeError(f"Payload missing string {key}: {payload!r}")
    return value


def _required_mapping_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise RuntimeError(f"Payload missing boolean {key}: {payload!r}")
    return value


def _required_mapping_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError(f"Payload missing integer {key}: {payload!r}")
    return value


def _optional_mapping_float(payload: Mapping[str, object], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise RuntimeError(f"Payload field {key} must be numeric: {payload!r}")
    return float(value)


def _optional_mapping_str(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"Payload field {key} must be a string: {payload!r}")
    return value


def _engine_run_entry_step_type(payload: Mapping[str, object]) -> enums_pb2.StepType | None:
    value = payload.get("step_type")
    if value is None:
        metadata = payload.get("metadata")
        if isinstance(metadata, Mapping):
            value = metadata.get("step_type")
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"Engine run execution entry step_type must be a string: {payload!r}")
    return cast(enums_pb2.StepType, enum_to_proto_value("STEP_TYPE", value))


def _engine_run_execution_entry_proto(payload: Mapping[str, object]) -> compute_pb2.ComputeWorkerRunExecutionEntry:
    entry = compute_pb2.ComputeWorkerRunExecutionEntry(
        key=_required_mapping_str(payload, "key"),
        label=_required_mapping_str(payload, "label"),
        category=enum_to_proto_value("COMPUTE_WORKER_RUN_EXECUTION_CATEGORY", _required_mapping_str(payload, "category")),
        order=_required_mapping_int(payload, "order"),
    )
    duration_ms = _optional_mapping_float(payload, "duration_ms")
    if duration_ms is not None:
        entry.duration_ms = duration_ms
    share_pct = _optional_mapping_float(payload, "share_pct")
    if share_pct is not None:
        entry.share_pct = share_pct
    optimized_plan = _optional_mapping_str(payload, "optimized_plan")
    if optimized_plan is not None:
        entry.optimized_plan = optimized_plan
    unoptimized_plan = _optional_mapping_str(payload, "unoptimized_plan")
    if unoptimized_plan is not None:
        entry.unoptimized_plan = unoptimized_plan
    step_type = _engine_run_entry_step_type(payload)
    if step_type is not None:
        entry.step_type = step_type
    return entry


def _datetime_field(value: object, *, key: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise RuntimeError(f"Payload field {key} must be an ISO datetime string: {value!r}")


def _mapping_dict_field(payload: Mapping[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"Payload field {key} must be an object: {payload!r}")
    return value


def _engine_resource_config_proto(payload: Mapping[str, object]) -> compute_pb2.ComputeWorkerResourceConfig:
    config = compute_pb2.ComputeWorkerResourceConfig()
    for field in ("max_threads", "max_memory_mb", "streaming_chunk_size"):
        value = payload.get(field)
        if value is not None:
            if not isinstance(value, int) or isinstance(value, bool):
                raise RuntimeError(f"Engine resource field {field} must be an integer: {payload!r}")
            setattr(config, field, value)
    return config


def _engine_defaults_proto(payload: Mapping[str, object]) -> compute_pb2.ComputeWorkerDefaults:
    return compute_pb2.ComputeWorkerDefaults(
        max_threads=_required_mapping_int(payload, "max_threads"),
        max_memory_mb=_required_mapping_int(payload, "max_memory_mb"),
        streaming_chunk_size=_required_mapping_int(payload, "streaming_chunk_size"),
    )


def _engine_status_result_proto(status_info: ComputeWorkerStatusInfo) -> compute_pb2.ComputeWorkerStatusResult:
    if not isinstance(status_info.analysis_id, str):
        raise RuntimeError(f"Engine status analysis_id must be a string: {status_info!r}")
    if not isinstance(status_info.resource_id, str) or not status_info.resource_id:
        raise RuntimeError(f"Engine status resource_id must be a non-empty string: {status_info!r}")
    if not isinstance(status_info.status, str):
        raise RuntimeError(f"Engine status status must be a string: {status_info!r}")
    status = compute_pb2.ComputeWorkerStatusResult(
        analysis_id=status_info.analysis_id,
        resource_id=status_info.resource_id,
        status=enum_to_proto_value("COMPUTE_WORKER_STATUS", status_info.status),
    )
    for field in (
        "last_activity",
        "current_job_id",
        "datasource_id",
        "build_id",
        "current_build_id",
        "current_engine_run_id",
        "container_id",
        "image_digest",
        "termination_reason",
        "supervisor_id",
        "owner_id",
    ):
        value = getattr(status_info, field)
        if value is not None:
            if not isinstance(value, str):
                raise RuntimeError(f"Engine status field {field} must be a string: {status_info!r}")
            setattr(status, field, value)
    exit_code = status_info.exit_code
    if exit_code is not None:
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            raise RuntimeError(f"Engine status exit_code must be an integer: {status_info!r}")
        status.exit_code = exit_code
    oom_killed = status_info.oom_killed
    if oom_killed is not None:
        if not isinstance(oom_killed, bool):
            raise RuntimeError(f"Engine status oom_killed must be a boolean: {status_info!r}")
        status.oom_killed = oom_killed
    resource_config = status_info.resource_config
    if isinstance(resource_config, Mapping):
        status.resource_config.CopyFrom(_engine_resource_config_proto(resource_config))
    effective_resources = status_info.effective_resources
    if isinstance(effective_resources, Mapping):
        status.effective_resources.CopyFrom(_engine_resource_config_proto(effective_resources))
    defaults = status_info.defaults
    if isinstance(defaults, Mapping):
        status.defaults.CopyFrom(_engine_defaults_proto(defaults))
    scope = status_info.scope
    if scope is not None:
        if not isinstance(scope, str):
            raise RuntimeError(f"Engine status scope must be a string: {status_info!r}")
        status.scope = enum_to_proto_value("COMPUTE_WORKER_SCOPE", scope)
    reuse_policy = status_info.reuse_policy
    if reuse_policy is not None:
        if not isinstance(reuse_policy, str):
            raise RuntimeError(f"Engine status reuse_policy must be a string: {status_info!r}")
        status.reuse_policy = enum_to_proto_value("COMPUTE_WORKER_REUSE_POLICY", reuse_policy)
    lifecycle_status = status_info.lifecycle_status
    if lifecycle_status is not None:
        if not isinstance(lifecycle_status, str):
            raise RuntimeError(f"Engine lifecycle status must be a string: {status_info!r}")
        status.lifecycle_status = enum_to_proto_value("COMPUTE_WORKER_INSTANCE_STATUS", lifecycle_status)
    return status


def _engine_run_update_proto(fields: Mapping[str, object]) -> worker_runtime_pb2.WorkerComputeWorkerRunUpdateFields:
    update = worker_runtime_pb2.WorkerComputeWorkerRunUpdateFields()
    if "analysis_id" in fields:
        update.analysis_id = _required_mapping_str(fields, "analysis_id")
    if "datasource_id" in fields:
        update.datasource_id = _required_mapping_str(fields, "datasource_id")
    if "kind" in fields:
        update.kind = enum_to_proto_value("COMPUTE_WORKER_RUN_KIND", _required_mapping_str(fields, "kind"))
    if "status" in fields:
        update.status = enum_to_proto_value("COMPUTE_WORKER_RUN_STATUS", _required_mapping_str(fields, "status"))
    if "request_json" in fields:
        update.request_json.CopyFrom(dict_to_struct(_mapping_dict_field(fields, "request_json")))
    if "result_json" in fields:
        update.result_json.CopyFrom(dict_to_struct(_mapping_dict_field(fields, "result_json")))
    if "error_message" in fields:
        update.error_message = _required_mapping_str(fields, "error_message")
    if "completed_at" in fields:
        update.completed_at.CopyFrom(datetime_to_timestamp(_datetime_field(fields["completed_at"], key="completed_at")))
    if "duration_ms" in fields:
        update.duration_ms = _required_mapping_int(fields, "duration_ms")
    if "step_timings" in fields:
        step_timings = _mapping_dict_field(fields, "step_timings")
        update.step_timings.SetInParent()
        for key, value in step_timings.items():
            if not isinstance(value, int | float) or isinstance(value, bool):
                raise RuntimeError(f"Step timing value must be numeric: {fields!r}")
            update.step_timings.values[str(key)] = float(value)
    if "query_plan" in fields:
        update.query_plan = _required_mapping_str(fields, "query_plan")
    if "execution_entries" in fields:
        entries = fields.get("execution_entries")
        if not isinstance(entries, list):
            raise RuntimeError(f"Payload field execution_entries must be a list: {fields!r}")
        update.execution_entries.SetInParent()
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise RuntimeError(f"Execution entry must be an object: {entry!r}")
            update.execution_entries.entries.append(_engine_run_execution_entry_proto(entry))
    if "progress" in fields:
        progress = _optional_mapping_float(fields, "progress")
        if progress is None:
            raise RuntimeError(f"Payload field progress must be numeric: {fields!r}")
        update.progress = progress
    if "current_step" in fields:
        value = fields.get("current_step")
        if value is None:
            update.clear_current_step = True
        elif isinstance(value, str) and value:
            update.current_step = value
        else:
            raise RuntimeError(f"Payload field current_step must be a string or null: {fields!r}")
    if "triggered_by" in fields:
        update.triggered_by = _required_mapping_str(fields, "triggered_by")
    return update


def _engine_run_finalization_proto(finalization: ComputeWorkerRunFinalization) -> worker_runtime_pb2.WorkerComputeWorkerRunFinalization:
    return worker_runtime_pb2.WorkerComputeWorkerRunFinalization(
        run_id=finalization.run_id,
        merge_result=finalization.merge_result_json,
        update=_engine_run_update_proto(finalization.fields),
    )


def _required_mapping_dict(payload: Mapping[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"Payload missing object {key}: {payload!r}")
    return value


def _enum_name_from_token(enum_descriptor: Any, value: object) -> object:
    if not isinstance(value, str) or value in enum_descriptor.values_by_name:
        return value
    prefixed_value = f"{_enum_prefix(enum_descriptor)}_{value}"
    if prefixed_value in enum_descriptor.values_by_name:
        return prefixed_value
    for enum_value in enum_descriptor.values:
        options = enum_value.GetOptions()
        if not options.HasExtension(cast(Any, enums_pb2.dataforge_token)):
            continue
        token = options.Extensions[cast(Any, enums_pb2.dataforge_token)]
        if token == value:
            return enum_value.name
    return value


def _enum_prefix(enum_descriptor: Any) -> str:
    chars: list[str] = []
    for index, char in enumerate(enum_descriptor.name):
        if char.isupper() and index > 0:
            chars.append("_")
        chars.append(char.upper())
    return "".join(chars)


def _enum_number_from_token(enum_descriptor: Any, value: object, *, field_name: str) -> Any:
    enum_name = _enum_name_from_token(enum_descriptor, value)
    if not isinstance(enum_name, str):
        raise ValueError(f"{field_name} must be a string enum token")
    try:
        return cast(int, enum_descriptor.values_by_name[enum_name].number)
    except KeyError as exc:
        raise ValueError(f"{field_name} is invalid") from exc


def _optional_payload_int(payload: Mapping[str, object], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _build_resource_config_proto(payload: Mapping[str, object]) -> compute_pb2.BuildResourceConfigSummary:
    config = compute_pb2.BuildResourceConfigSummary()
    for key in ("max_threads", "max_memory_mb", "streaming_chunk_size"):
        value = _optional_payload_int(payload, key)
        if value is not None:
            setattr(config, key, value)
    return config


def _build_resource_config_payload(config: compute_pb2.BuildResourceConfigSummary) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key in ("max_threads", "max_memory_mb", "streaming_chunk_size"):
        if config.HasField(key):
            payload[key] = getattr(config, key)
    return payload


def _build_starter_payload(starter: compute_pb2.BuildStarter) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key in ("user_id", "display_name", "email", "triggered_by"):
        if starter.HasField(key):
            payload[key] = getattr(starter, key)
    return payload


def _started_build_run_from_response(response: Any) -> StartedBuildRun | None:
    if not response.HasField("run"):
        return None
    run = response.run
    return StartedBuildRun(
        id=run.id,
        namespace=run.namespace,
        analysis_id=run.analysis_id,
        analysis_name=run.analysis_name,
        analysis_pipeline=run.analysis_pipeline,
        tab_id=_optional_str(run, "tab_id"),
        starter_json=_build_starter_payload(run.build_starter),
        resource_config_json=_build_resource_config_payload(run.build_resource_config) if run.HasField("build_resource_config") else None,
        current_kind=_optional_proto_enum_name(run, "current_kind", enums_pb2.ComputeWorkerRunKind, "COMPUTE_WORKER_RUN_KIND"),
        current_datasource_id=_optional_str(run, "current_datasource_id"),
        current_tab_id=_optional_str(run, "current_tab_id"),
        current_tab_name=_optional_str(run, "current_tab_name"),
        current_output_id=_optional_str(run, "current_output_id"),
        current_output_name=_optional_str(run, "current_output_name"),
        started_at=optional_timestamp_to_datetime(run, "started_at") or datetime.min,
        total_tabs=run.total_tabs,
    )


def _required_event_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"build event {key} is required")
    return value


def _optional_event_str(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"build event {key} must be a string")
    return value


def _optional_event_int(payload: Mapping[str, object], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"build event {key} must be an integer")
    return value


def _required_event_int(payload: Mapping[str, object], key: str) -> int:
    value = _optional_event_int(payload, key)
    if value is None:
        raise ValueError(f"build event {key} is required")
    return value


def _optional_event_float(payload: Mapping[str, object], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"build event {key} must be numeric")
    return float(value)


def _required_event_float(payload: Mapping[str, object], key: str) -> float:
    value = _optional_event_float(payload, key)
    if value is None:
        raise ValueError(f"build event {key} is required")
    return value


def _event_datetime(payload: Mapping[str, object], key: str) -> datetime:
    value = payload.get(key)
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(f"build event {key} is required")


def _build_step_kind_proto(step_type: object) -> compute_pb2.BuildStepKind:
    if not isinstance(step_type, str) or not step_type.strip():
        raise ValueError("build step event step_type is required")
    message = compute_pb2.BuildStepKind()
    try:
        message.pipeline = _enum_number_from_token(enums_pb2.StepType.DESCRIPTOR, step_type, field_name="step_type")
        return message
    except ValueError:
        category = _enum_number_from_token(enums_pb2.ComputeWorkerRunExecutionCategory.DESCRIPTOR, step_type, field_name="step_type")
        if category not in {enums_pb2.COMPUTE_WORKER_RUN_EXECUTION_CATEGORY_READ, enums_pb2.COMPUTE_WORKER_RUN_EXECUTION_CATEGORY_WRITE}:
            raise ValueError(f"Unsupported build execution category for protocol step event: {step_type!r}") from None
        message.execution_category = category
        return message


def _build_tab_result_proto(payload: Mapping[str, object]) -> compute_pb2.BuildTabResult:
    message = compute_pb2.BuildTabResult(
        tab_id=_required_event_str(payload, "tab_id"),
        tab_name=_required_event_str(payload, "tab_name"),
    )
    message.status = _enum_number_from_token(enums_pb2.BuildTabStatus.DESCRIPTOR, payload.get("status"), field_name="status")
    for field in ("output_id", "output_name", "error"):
        value = _optional_event_str(payload, field)
        if value is not None:
            setattr(message, field, value)
    return message


def _build_terminal_event_proto(payload: Mapping[str, object]) -> compute_pb2.BuildTerminalEvent:
    message = compute_pb2.BuildTerminalEvent(
        progress=_required_event_float(payload, "progress"),
        elapsed_ms=_required_event_int(payload, "elapsed_ms"),
        total_steps=_required_event_int(payload, "total_steps"),
        tabs_built=_required_event_int(payload, "tabs_built"),
        duration_ms=_required_event_int(payload, "duration_ms"),
    )
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("build terminal event results must be a list")
    for result in results:
        if not isinstance(result, Mapping):
            raise ValueError("build terminal event results must be objects")
        message.results.append(_build_tab_result_proto(result))
    error = _optional_event_str(payload, "error")
    if error is not None:
        message.error = error
    if payload.get("cancelled_at") is not None:
        message.cancelled_at.CopyFrom(datetime_to_timestamp(_event_datetime(payload, "cancelled_at")))
    cancelled_by = _optional_event_str(payload, "cancelled_by")
    if cancelled_by is not None:
        message.cancelled_by = cancelled_by
    return message


def _build_event_proto(namespace: str, payload: Mapping[str, object]) -> compute_pb2.BuildEvent:
    context = compute_pb2.BuildEventContext(
        build_id=_required_event_str(payload, "build_id"),
        analysis_id=_required_event_str(payload, "analysis_id"),
        emitted_at=datetime_to_timestamp(_event_datetime(payload, "emitted_at")),
    )
    sequence = _optional_event_int(payload, "sequence")
    if sequence is not None:
        context.sequence = sequence
    current_kind = payload.get("current_kind")
    if current_kind is not None:
        context.current_kind = _enum_number_from_token(enums_pb2.ComputeWorkerRunKind.DESCRIPTOR, current_kind, field_name="current_kind")
    for field in ("current_datasource_id", "tab_id", "tab_name", "current_output_id", "current_output_name", "engine_run_id"):
        value = _optional_event_str(payload, field)
        if value is not None:
            setattr(context, field, value)

    message = compute_pb2.BuildEvent(context=context, namespace=namespace)
    match _required_event_str(payload, "type"):
        case "plan":
            message.plan.optimized_plan = _required_event_str(payload, "optimized_plan")
            message.plan.unoptimized_plan = _required_event_str(payload, "unoptimized_plan")
        case "step_start":
            message.step_started.build_step_index = _required_event_int(payload, "build_step_index")
            message.step_started.step_index = _required_event_int(payload, "step_index")
            message.step_started.step_id = _required_event_str(payload, "step_id")
            message.step_started.step_name = _required_event_str(payload, "step_name")
            message.step_started.total_steps = _required_event_int(payload, "total_steps")
            message.step_started.step_kind.CopyFrom(_build_step_kind_proto(payload.get("step_type")))
        case "step_complete":
            message.step_completed.build_step_index = _required_event_int(payload, "build_step_index")
            message.step_completed.step_index = _required_event_int(payload, "step_index")
            message.step_completed.step_id = _required_event_str(payload, "step_id")
            message.step_completed.step_name = _required_event_str(payload, "step_name")
            message.step_completed.duration_ms = _required_event_int(payload, "duration_ms")
            row_count = _optional_event_int(payload, "row_count")
            if row_count is not None:
                message.step_completed.row_count = row_count
            message.step_completed.total_steps = _required_event_int(payload, "total_steps")
            message.step_completed.step_kind.CopyFrom(_build_step_kind_proto(payload.get("step_type")))
        case "step_failed":
            message.step_failed.build_step_index = _required_event_int(payload, "build_step_index")
            message.step_failed.step_index = _required_event_int(payload, "step_index")
            message.step_failed.step_id = _required_event_str(payload, "step_id")
            message.step_failed.step_name = _required_event_str(payload, "step_name")
            message.step_failed.error = _required_event_str(payload, "error")
            message.step_failed.total_steps = _required_event_int(payload, "total_steps")
            message.step_failed.step_kind.CopyFrom(_build_step_kind_proto(payload.get("step_type")))
        case "progress":
            message.progress.progress = _required_event_float(payload, "progress")
            message.progress.elapsed_ms = _required_event_int(payload, "elapsed_ms")
            estimated_remaining_ms = _optional_event_int(payload, "estimated_remaining_ms")
            if estimated_remaining_ms is not None:
                message.progress.estimated_remaining_ms = estimated_remaining_ms
            current_step = _optional_event_str(payload, "current_step")
            if current_step is not None:
                message.progress.current_step = current_step
            current_step_index = _optional_event_int(payload, "current_step_index")
            if current_step_index is not None:
                message.progress.current_step_index = current_step_index
            message.progress.total_steps = _required_event_int(payload, "total_steps")
        case "resources":
            message.resources.cpu_percent = _required_event_float(payload, "cpu_percent")
            message.resources.memory_mb = _required_event_float(payload, "memory_mb")
            memory_limit_mb = _optional_event_float(payload, "memory_limit_mb")
            if memory_limit_mb is not None:
                message.resources.memory_limit_mb = memory_limit_mb
            message.resources.active_threads = _required_event_int(payload, "active_threads")
            max_threads = _optional_event_int(payload, "max_threads")
            if max_threads is not None:
                message.resources.max_threads = max_threads
        case "log":
            message.log.level = _enum_number_from_token(enums_pb2.BuildLogLevel.DESCRIPTOR, payload.get("level"), field_name="level")
            message.log.message = _required_event_str(payload, "message")
            for field in ("step_name", "step_id"):
                value = _optional_event_str(payload, field)
                if value is not None:
                    setattr(message.log, field, value)
        case "complete":
            message.completed.CopyFrom(_build_terminal_event_proto(payload))
        case "failed":
            message.failed.CopyFrom(_build_terminal_event_proto(payload))
        case "cancelled":
            message.cancelled.CopyFrom(_build_terminal_event_proto(payload))
        case event_type:
            raise ValueError(f"Unsupported build event type: {event_type!r}")
    return message


def _compute_response_envelope(
    *,
    kind: enums_pb2.ComputeRequestKind,
    request_id: str,
    status: enums_pb2.ComputeRequestStatus,
    response: compute_pb2.ComputeResponse,
    error_message: str | None = None,
) -> compute_pb2.ComputeResponseEnvelope:
    envelope = compute_pb2.ComputeResponseEnvelope(
        kind=kind,
        version=1,
        correlation_id=request_id,
        status=status,
    )
    envelope.response.CopyFrom(response)
    if error_message is not None:
        envelope.error_message = error_message
    return envelope


def client_from_env() -> WorkerRuntimeClient:
    return WorkerRuntimeClient(
        target=_required_env("INTERNAL_GRPC_TARGET"),
        token=_required_env("INTERNAL_API_TOKEN"),
    )


async def async_client_from_env() -> WorkerRuntimeClient:
    loop = asyncio.get_running_loop()
    target = _required_env("INTERNAL_GRPC_TARGET")
    token = _required_env("INTERNAL_API_TOKEN")
    clients = _async_runtime_clients.setdefault(loop, {})
    key = (target, token)
    client = clients.get(key)
    if client is None:
        client = WorkerRuntimeClient(target=target, token=token)
        clients[key] = client
    return client


async def close_async_runtime_clients() -> None:
    loop = asyncio.get_running_loop()
    clients = _async_runtime_clients.pop(loop, {})
    for client in clients.values():
        await client.aclose()


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} must be configured for the worker runtime")
    return value.strip()
