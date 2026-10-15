from __future__ import annotations

import asyncio
import contextlib
import contextvars
import hmac
import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Iterator, Mapping
from concurrent.futures import Executor, Future as ConcurrentFuture, ThreadPoolExecutor
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Protocol, cast

import grpc
from google.protobuf import json_format, struct_pb2, timestamp_pb2
from google.protobuf.message import Message
from protovalidate import ValidationError, Validator
from sqlalchemy import select, text
from sqlmodel import Session

from backend_core import (
    build_commands,
    build_jobs_service as build_job_service,
    build_runs_service as build_run_service,
    compute_requests_service,
    compute_worker_instances_service as compute_worker_instance_service,
    compute_worker_runs_service as compute_worker_run_service,
    datasource_delete_service,
    runtime_outbox_service,
    runtime_work_service,
    runtime_workers_service as runtime_worker_service,
    storage_cleanup_service,
)
from backend_core.ai_clients import get_ai_client
from backend_core.claiming import CLAIM_DELIVERY_LEASE_SECONDS
from backend_core.config import settings
from backend_core.database import (
    RuntimeCoordinatorFenced,
    active_runtime_coordinator_generation,
    database_pool_snapshot,
    database_statement_timing,
    get_db,
    run_critical_db,
    run_critical_settings_db,
    run_db,
    run_settings_db,
)
from backend_core.domain.build_runs.models import BuildRunStatus
from backend_core.domain.compute import schemas as compute_schemas
from backend_core.domain.compute.base import ComputeWorkerStatusInfo
from backend_core.domain.compute_requests.models import (
    analysis_pipeline_from_payload,
    datasource_result_from_payload,
    kind_from_proto,
)
from backend_core.domain.runtime_workers.models import RuntimeWorkerKind
from backend_core.exceptions import AppError
from backend_core.namespace import namespace_scope, reset_namespace, set_namespace_context
from backend_core.notification_delivery import EMAIL_DELIVERY_KIND, TELEGRAM_DELIVERY_KIND
from backend_core.persistence.analysis.models import Analysis
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.healthchecks.models import HealthCheck, HealthCheckResult
from backend_core.persistence.telegram.models import TelegramListener, TelegramSubscriber
from backend_core.persistence.udfs.models import Udf
from backend_core.settings_projection import get_resolved_telegram_settings
from backend_core.sqlmodel_typing import col, sa
from dataforge_protocol import (
    common_pb2,
    compute_pb2,
    enums_pb2,
    runtime_coordinator_pb2,
    runtime_coordinator_pb2_grpc,
    scheduler_runtime_pb2,
    scheduler_runtime_pb2_grpc,
    worker_runtime_pb2,
    worker_runtime_pb2_grpc,
)
from modules.datasource import commands as datasource_commands, publication_service as datasource_publication_service
from modules.datasource.schema_protocol import schema_info_payload, schema_info_proto
from modules.healthcheck import commands as healthcheck_commands
from modules.scheduler import commands as scheduler_commands, service as scheduler_service

logger = logging.getLogger(__name__)
_TOKEN_METADATA_KEY = 'x-internal-token'
_RUNTIME_GENERATION_METADATA_KEY = 'x-runtime-coordinator-generation'
_WORKER_RUNTIME_SERVICE_PREFIX = f'/{worker_runtime_pb2.DESCRIPTOR.services_by_name["WorkerRuntimeService"].full_name}/'
_BUILD_JOB_PROTOCOL_VERSION = 2
_SLOW_COMPUTE_WORKER_SNAPSHOT_PHASE_SECONDS = 1.0
_RPC_PHASE_MONOTONIC = time.monotonic
_PHASE_TIMED_RPC_METHODS = frozenset({'CreateComputeWorkerRun', 'GetDatasourceMetadata'})
_RPC_PHASE_LOG_ORDER = (
    'payload_conversion_ms',
    'db_unit_ms',
    'compute_worker_run_payload_service_ms',
    'compute_worker_run_persistence_service_ms',
    'datasource_row_lookup_ms',
    'datasource_payload_conversion_ms',
    'column_descriptions_service_ms',
    'response_transformation_ms',
    'grpc_response_serialization_ms',
)


def dict_to_struct(payload: dict[str, object] | None) -> struct_pb2.Struct:
    return json_format.ParseDict(payload or {}, struct_pb2.Struct())


def struct_to_dict(payload: struct_pb2.Struct) -> dict[str, object]:
    decoded = json_format.MessageToDict(payload, preserving_proto_field_name=True)
    if not isinstance(decoded, dict):
        raise ValueError('gRPC JSON payload must decode to an object')
    return cast(dict[str, object], decoded)


def datetime_to_timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(value if value.tzinfo is not None else value.replace(tzinfo=UTC))
    return timestamp


def _optional(message: Any, field: str) -> Any:
    return getattr(message, field) if message.HasField(field) else None


def _present_fields(message: Any, fields: tuple[str, ...]) -> dict[str, object]:
    return {field: getattr(message, field) for field in fields if message.HasField(field)}


def _proto_enum_value(prefix: str, value: object) -> Any:
    return getattr(enums_pb2, f'{prefix}_{str(value).upper()}')


def proto_value_to_enum_name(enum_type: Any, prefix: str, value: int) -> str:
    enum_name = enum_type.Name(value)
    suffix = enum_name.removeprefix(f'{prefix}_')
    if suffix == 'UNSPECIFIED' or suffix == enum_name:
        raise ValueError(f'Unsupported {prefix} enum value: {enum_name}')
    return suffix.lower()


async def _await_thread_future[T](future: ConcurrentFuture[T], loop: asyncio.AbstractEventLoop) -> T:
    wrapped = asyncio.wrap_future(future, loop=loop)
    try:
        return await asyncio.shield(wrapped)
    except asyncio.CancelledError:
        while not wrapped.done():
            try:
                await asyncio.shield(wrapped)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        raise


class _BackendRequestValidationInterceptor(grpc.aio.ServerInterceptor):
    def __init__(self) -> None:
        self._validator = Validator()

    async def intercept_service(
        self,
        continuation: Callable[[grpc.HandlerCallDetails], Awaitable[grpc.RpcMethodHandler | None]],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler | None:
        handler = await continuation(handler_call_details)
        if handler is None or handler.unary_unary is None:
            return handler
        unary_unary = cast(Callable[[Message, grpc.aio.ServicerContext], Awaitable[Any]], handler.unary_unary)
        admission_lane = _rpc_admission_lane(handler_call_details.method)
        response_timing: list[dict[str, Any] | None] = [None]
        response_serializer = handler.response_serializer
        method_name = handler_call_details.method.rsplit('/', 1)[-1]
        if method_name in _PHASE_TIMED_RPC_METHODS and response_serializer is not None:
            serialize = response_serializer

            def serialize_response(response: Any) -> bytes:
                serialization_started = _RPC_PHASE_MONOTONIC()
                try:
                    return serialize(response)
                finally:
                    timing = response_timing[0]
                    if timing is not None:
                        phase_timings = timing.get('phase_timings')
                        if isinstance(phase_timings, dict):
                            phase_timings['grpc_response_serialization_ms'] = max(
                                0.0,
                                (_RPC_PHASE_MONOTONIC() - serialization_started) * 1000,
                            )
                        log_slow_rpc = timing.pop('_slow_rpc_diagnostic_callback', None)
                        if callable(log_slow_rpc):
                            log_slow_rpc()

            response_serializer = serialize_response

        async def validate_request(request: Message, context: grpc.aio.ServicerContext) -> Any:
            request_started = _RPC_PHASE_MONOTONIC()
            try:
                acquired = await admission_lane.acquire(context)
                outcome, status, details = 'rejected', grpc.StatusCode.RESOURCE_EXHAUSTED, 'is full'
            except TimeoutError:
                acquired = False
                outcome, status, details = 'timed out', grpc.StatusCode.DEADLINE_EXCEEDED, 'deadline expired'
            admission_queue_ms = (_RPC_PHASE_MONOTONIC() - request_started) * 1000
            if not acquired:
                logger.warning(
                    'Internal runtime RPC admission %s method=%s lane=%s admission_queue_ms=%.1f',
                    outcome,
                    handler_call_details.method,
                    admission_lane.name,
                    admission_queue_ms,
                )
                await context.abort(status, f'Internal runtime RPC admission {details} for {admission_lane.name}')
                raise RuntimeError(f'gRPC context.abort returned after RPC admission {outcome}')
            timing = {'request_started': request_started, 'admission_queue_ms': admission_queue_ms}
            if method_name in _PHASE_TIMED_RPC_METHODS and response_serializer is not None:
                timing['defer_slow_rpc_diagnostic'] = True
                response_timing[0] = timing
            timing_token = _RPC_TIMING.set(timing)
            try:
                if handler_call_details.method.startswith(_WORKER_RUNTIME_SERVICE_PREFIX):
                    active_generation = active_runtime_coordinator_generation()
                    request_metadata = dict(cast(Any, context.invocation_metadata() or ()))
                    supplied_generation = request_metadata.get(_RUNTIME_GENERATION_METADATA_KEY)
                    rejection = _runtime_generation_rejection(active_generation, supplied_generation)
                    if rejection is not None:
                        status, details = rejection
                        await context.abort(status, details)
                try:
                    loop = asyncio.get_running_loop()
                    validation_submitted = _RPC_PHASE_MONOTONIC()

                    def validate() -> None:
                        timing['validation_started'] = _RPC_PHASE_MONOTONIC()
                        try:
                            self._validator.validate(request)
                        finally:
                            timing['validation_finished'] = _RPC_PHASE_MONOTONIC()

                    await _await_thread_future(_validation_executor(handler_call_details.method).submit(validate), loop)
                    timing['validation_queue_ms'] = (timing['validation_started'] - validation_submitted) * 1000
                    timing['validation_ms'] = (timing['validation_finished'] - timing['validation_started']) * 1000
                except ValidationError as exc:
                    logger.warning(
                        'Rejected invalid internal RPC request %s (%s): %s',
                        handler_call_details.method,
                        request.DESCRIPTOR.full_name,
                        ', '.join(repr(violation) for violation in exc.violations),
                    )
                    await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
                return await unary_unary(request, context)
            finally:
                _RPC_TIMING.reset(timing_token)
                admission_lane.release()

        return grpc.unary_unary_rpc_method_handler(
            validate_request,
            request_deserializer=handler.request_deserializer,
            response_serializer=response_serializer,
        )


def _runtime_generation_rejection(
    active_generation: int | None,
    supplied_generation: object,
) -> tuple[grpc.StatusCode, str] | None:
    if active_generation is None:
        return grpc.StatusCode.UNAVAILABLE, 'Runtime coordinator generation is not active'
    if supplied_generation is None:
        return grpc.StatusCode.UNAUTHENTICATED, 'Runtime coordinator generation metadata is required'
    try:
        generation = int(str(supplied_generation))
    except TypeError, ValueError:
        return grpc.StatusCode.INVALID_ARGUMENT, 'Invalid runtime coordinator generation metadata'
    if generation < 1:
        return grpc.StatusCode.INVALID_ARGUMENT, 'Invalid runtime coordinator generation metadata'
    if generation != active_generation:
        return (
            grpc.StatusCode.FAILED_PRECONDITION,
            f'Runtime coordinator generation {generation} is fenced by {active_generation}',
        )
    return None


type RpcMetadata = Mapping[str, str]


async def _require_internal_token(context: grpc.aio.ServicerContext) -> RpcMetadata:
    if not settings.internal_api_token:
        await context.abort(grpc.StatusCode.UNAVAILABLE, 'INTERNAL_API_TOKEN must be configured before internal runtime services can be used')
    metadata = MappingProxyType(dict(cast(Any, context.invocation_metadata() or ())))
    if not hmac.compare_digest(metadata.get(_TOKEN_METADATA_KEY) or '', settings.internal_api_token):
        await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Invalid internal runtime token')
    return metadata


_RPC_TIMING: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar('runtime_rpc_timing', default=None)
_RPC_PHASE_TIMINGS: contextvars.ContextVar[dict[str, float] | None] = contextvars.ContextVar('runtime_rpc_phase_timings', default=None)
_SCHEDULER_HEARTBEAT_METHODS = frozenset({'HeartbeatScheduler'})
_LEASE_VALIDATION_METHODS = frozenset(
    {
        'HeartbeatWorker',
        'RenewBuildJobLease',
        'RenewComputeRequestLeases',
        'GetCoordinatorGeneration',
    }
)


def _validation_executor(method: str) -> Executor:
    method_name = method.rsplit('/', 1)[-1]
    if method_name in _SCHEDULER_HEARTBEAT_METHODS and _INTERNAL_SCHEDULER_VALIDATION_EXECUTOR is not None:
        return _INTERNAL_SCHEDULER_VALIDATION_EXECUTOR
    if method_name in _SCHEDULER_HEARTBEAT_METHODS | _LEASE_VALIDATION_METHODS:
        return _INTERNAL_LEASE_VALIDATION_EXECUTOR
    return _INTERNAL_VALIDATION_EXECUTOR


def _record_rpc_phase[T](name: str, operation: Callable[[], T]) -> T:
    phase_timings = _RPC_PHASE_TIMINGS.get()
    if phase_timings is None:
        return operation()
    started = _RPC_PHASE_MONOTONIC()
    try:
        return operation()
    finally:
        phase_timings[name] = max(0.0, (_RPC_PHASE_MONOTONIC() - started) * 1000)


# Keep completion/claim RPC capacity aligned with the compute budget, while
# reserving a smaller independent lane for batched lease renewals and one
# scheduler heartbeat. One pooled connection stays available to outbox recovery.
def _runtime_rpc_executor_sizes(
    database_pool_size: int,
    database_max_overflow: int,
) -> tuple[int, int, int]:
    """Return (lease, general, scheduler-heartbeat) RPC counts for one coordinator."""
    database_capacity = max(database_pool_size + database_max_overflow, 1)
    if database_capacity < 4:
        raise ValueError(
            'Runtime coordinator requires at least four pooled database connections for lease RPCs, scheduler heartbeat, general RPCs, and outbox recovery'
        )
    rpc_capacity = database_capacity - 1
    scheduler_heartbeat_workers = 1
    remaining_capacity = rpc_capacity - scheduler_heartbeat_workers
    # The runtime coordinator's pool size is configured from COMPUTE_WORKERS.
    # Match that concurrency for claims/completions, instead of capping the
    # control-plane lane at 12 while 32 admitted jobs finish together.
    general_target = min(32, max(database_pool_size, 4))
    lease_target = min(max(database_pool_size // 4, 4), max(database_pool_size, 1))
    general_workers = min(general_target, max(remaining_capacity - lease_target, 1))
    lease_workers = min(lease_target, max(remaining_capacity - general_workers, 1))
    return lease_workers, general_workers, scheduler_heartbeat_workers


(
    _INTERNAL_LEASE_RPC_WORKERS,
    _INTERNAL_GENERAL_RPC_WORKERS,
    _INTERNAL_SCHEDULER_RPC_WORKERS,
) = _runtime_rpc_executor_sizes(settings.database_pool_size, settings.database_max_overflow)
_INTERNAL_VALIDATION_EXECUTOR = ThreadPoolExecutor(
    max_workers=_INTERNAL_GENERAL_RPC_WORKERS,
    thread_name_prefix='internal-rpc-validation',
)
# Large compute payload validation must not delay liveness or lease messages.
_INTERNAL_LEASE_VALIDATION_WORKERS = min(2, _INTERNAL_LEASE_RPC_WORKERS)
_INTERNAL_LEASE_VALIDATION_EXECUTOR = ThreadPoolExecutor(
    max_workers=_INTERNAL_LEASE_VALIDATION_WORKERS,
    thread_name_prefix='internal-lease-validation',
)
_INTERNAL_SCHEDULER_VALIDATION_WORKERS = min(1, _INTERNAL_SCHEDULER_RPC_WORKERS)
_INTERNAL_SCHEDULER_VALIDATION_EXECUTOR = (
    ThreadPoolExecutor(
        max_workers=_INTERNAL_SCHEDULER_VALIDATION_WORKERS,
        thread_name_prefix='internal-scheduler-validation',
    )
    if _INTERNAL_SCHEDULER_VALIDATION_WORKERS
    else None
)
_INTERNAL_EXTERNAL_IO_WORKERS = 2
_INTERNAL_EXTERNAL_IO_EXECUTOR = ThreadPoolExecutor(max_workers=_INTERNAL_EXTERNAL_IO_WORKERS, thread_name_prefix='internal-runtime-external-io')
_INTERNAL_RPC_EXECUTOR = ThreadPoolExecutor(
    max_workers=_INTERNAL_GENERAL_RPC_WORKERS,
    thread_name_prefix='internal-runtime-rpc',
)
_INTERNAL_LEASE_RPC_EXECUTOR = ThreadPoolExecutor(
    max_workers=_INTERNAL_LEASE_RPC_WORKERS,
    thread_name_prefix='internal-runtime-lease',
)
_INTERNAL_SCHEDULER_RPC_EXECUTOR = (
    ThreadPoolExecutor(
        max_workers=_INTERNAL_SCHEDULER_RPC_WORKERS,
        thread_name_prefix='internal-scheduler-heartbeat',
    )
    if _INTERNAL_SCHEDULER_RPC_WORKERS
    else None
)


def _runtime_rpc_admission_queue_limit(compute_workers: int = settings.compute_workers) -> int:
    # Bound queued control-plane work by runtime capacity, independently of DB thread-pool width.
    return max(8, 2 * compute_workers)


_INTERNAL_RPC_ADMISSION_QUEUE_LIMIT = _runtime_rpc_admission_queue_limit()


class _RpcAdmissionContext(Protocol):
    def time_remaining(self) -> float | None: ...


class _RpcAdmissionLane:
    def __init__(self, name: str, capacity: int, queue_limit: int = _INTERNAL_RPC_ADMISSION_QUEUE_LIMIT) -> None:
        self.name = name
        self.capacity = capacity
        self.queue_limit = queue_limit
        self._active = 0
        self._waiters: deque[ConcurrentFuture[None]] = deque()
        self._lock = threading.Lock()

    async def acquire(self, context: _RpcAdmissionContext) -> bool:
        with self._lock:
            if self._active < self.capacity and not self._waiters:
                self._active += 1
                return True
            if len(self._waiters) >= self.queue_limit:
                return False
            waiter: ConcurrentFuture[None] = ConcurrentFuture()
            self._waiters.append(waiter)

        try:
            remaining = context.time_remaining()
            wrapped_waiter = asyncio.wrap_future(waiter)
            if remaining is None:
                await asyncio.shield(wrapped_waiter)
            else:
                await asyncio.wait_for(asyncio.shield(wrapped_waiter), timeout=max(remaining, 0))
            return True
        except TimeoutError, asyncio.CancelledError:
            self._withdraw(waiter)
            raise

    def release(self) -> None:
        with self._lock:
            self._release_locked()

    def _withdraw(self, waiter: ConcurrentFuture[None]) -> None:
        with self._lock:
            try:
                self._waiters.remove(waiter)
            except ValueError:
                if waiter.done() and not waiter.cancelled():
                    self._release_locked()
            else:
                waiter.cancel()

    def _release_locked(self) -> None:
        while self._waiters:
            waiter = self._waiters.popleft()
            if waiter.set_running_or_notify_cancel():
                waiter.set_result(None)
                return
        if self._active <= 0:
            raise RuntimeError(f'RPC admission lane {self.name} released without an active call')
        self._active -= 1

    @property
    def active_count(self) -> int:
        with self._lock:
            return self._active

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._waiters)


_RPC_ADMISSION_LANES = {
    'critical': _RpcAdmissionLane('critical', _INTERNAL_LEASE_RPC_WORKERS),
    'general': _RpcAdmissionLane('general', _INTERNAL_GENERAL_RPC_WORKERS),
    'scheduler': _RpcAdmissionLane(
        'scheduler',
        _INTERNAL_SCHEDULER_RPC_WORKERS or _INTERNAL_LEASE_RPC_WORKERS,
    ),
    'external-io': _RpcAdmissionLane('external-io', _INTERNAL_EXTERNAL_IO_WORKERS),
}


def _rpc_admission_lane(method: str) -> _RpcAdmissionLane:
    method_name = method.rsplit('/', 1)[-1]
    if method_name in _SCHEDULER_HEARTBEAT_METHODS:
        return _RPC_ADMISSION_LANES['scheduler']
    if method_name in _LEASE_VALIDATION_METHODS:
        return _RPC_ADMISSION_LANES['critical']
    if method_name == 'GenerateAI':
        return _RPC_ADMISSION_LANES['external-io']
    return _RPC_ADMISSION_LANES['general']


_RUNTIME_WORK_CACHE_TTL_SECONDS = 5.0
_RUNTIME_WORK_CACHE_LOCK = threading.Lock()
_RUNTIME_PENDING_NAMESPACE_CACHE: dict[tuple[str, ...], tuple[float, tuple[str, ...]]] = {}
_RUNTIME_WORK_CACHE_MISS_LOCKS: dict[tuple[str, ...], threading.Lock] = {}


def _cached_pending_runtime_work_namespaces(kinds: tuple[runtime_work_service.RuntimeWorkKind, ...]) -> list[str]:
    """Share indexed pending-work queries without blocking unrelated queue types."""
    cache_key = tuple(sorted({kind.value for kind in kinds}))
    now = time.monotonic()
    with _RUNTIME_WORK_CACHE_LOCK:
        cached = _RUNTIME_PENDING_NAMESPACE_CACHE.get(cache_key)
        if cached is not None and cached[0] > now:
            return list(cached[1])
        miss_lock = _RUNTIME_WORK_CACHE_MISS_LOCKS.setdefault(cache_key, threading.Lock())

    # Keep one refresh per kind, but never hold the global cache lock while
    # querying Postgres. A slow compute recovery query must not queue build or
    # datasource-delete recovery behind it.
    with miss_lock:
        now = time.monotonic()
        with _RUNTIME_WORK_CACHE_LOCK:
            cached = _RUNTIME_PENDING_NAMESPACE_CACHE.get(cache_key)
            if cached is not None and cached[0] > now:
                return list(cached[1])
        namespaces = tuple(
            dict.fromkeys(
                run_settings_db(
                    lambda session: runtime_work_service.list_pending_namespaces(
                        session,
                        kinds=kinds,
                    )
                )
            )
        )
        with _RUNTIME_WORK_CACHE_LOCK:
            _RUNTIME_PENDING_NAMESPACE_CACHE[cache_key] = (time.monotonic() + _RUNTIME_WORK_CACHE_TTL_SECONDS, namespaces)
        return list(namespaces)


def close_rpc_session(session_gen) -> None:
    """Exhaust and close a get_db() generator so post-yield cleanup runs."""
    with contextlib.suppress(StopIteration):
        next(session_gen, None)
    session_gen.close()


@contextlib.contextmanager
def _tenant_session(namespace: str) -> Iterator[Session]:
    """Hold one tenant session for an RPC whose service call manages its own transaction."""
    with namespace_scope(namespace):
        session_gen = get_db()
        session = next(session_gen)
        try:
            yield session
        finally:
            close_rpc_session(session_gen)


def _threaded_rpc(executor: Executor):
    def decorator(func):
        async def wrapper(self, request, context):
            metadata = await _require_internal_token(context)
            started = _RPC_PHASE_MONOTONIC()
            rpc_timing = _RPC_TIMING.get()
            phase_timings: dict[str, float] = {}
            phase_token = _RPC_PHASE_TIMINGS.set(phase_timings)
            if rpc_timing is not None:
                rpc_timing['phase_timings'] = phase_timings
            timing: dict[str, float] = {}
            database_timing: dict[str, Any] = {'sql_count': 0, 'sql_ms': 0.0, 'commit_ms': 0.0}
            response_ready = False

            def _run():
                timing['worker_started'] = _RPC_PHASE_MONOTONIC()
                try:
                    timing['handler_started'] = _RPC_PHASE_MONOTONIC()
                    with database_statement_timing(database_timing):
                        return func(self, request, metadata)
                finally:
                    timing['worker_finished'] = _RPC_PHASE_MONOTONIC()

            try:
                loop = asyncio.get_running_loop()
                contextvars_context = contextvars.copy_context()
                future = executor.submit(contextvars_context.run, _run)
                response = await _await_thread_future(future, loop)
                response_ready = True
                return response
            except _ThreadedRpcAbort as exc:
                await context.abort(exc.status, exc.details)
            except RuntimeCoordinatorFenced as exc:
                await context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
            finally:
                _RPC_PHASE_TIMINGS.reset(phase_token)
                validation_queue_ms = rpc_timing.get('validation_queue_ms', 0.0) if rpc_timing is not None else 0.0
                validation_ms = rpc_timing.get('validation_ms', 0.0) if rpc_timing is not None else 0.0

                def log_slow_rpc() -> None:
                    finished = _RPC_PHASE_MONOTONIC()
                    duration_ms = (finished - started) * 1000
                    request_ms = (finished - rpc_timing['request_started']) * 1000 if rpc_timing is not None else duration_ms
                    if request_ms < 1000:
                        return
                    worker_started = timing.get('worker_started', finished)
                    handler_started = timing.get('handler_started', worker_started)
                    worker_finished = timing.get('worker_finished', finished)
                    request_id = getattr(request, 'request_id', None) or getattr(request, 'idempotency_key', None) or getattr(request, 'job_id', None) or '-'
                    namespace = getattr(request, 'target_namespace', None) or getattr(request, 'namespace', None) or '-'
                    identity = getattr(request, 'compute_worker_identity', None) or getattr(request, 'engine_identity', None)
                    resource_id = getattr(identity, 'resource_id', None) or getattr(request, 'datasource_id', None) or '-'
                    pool_snapshot: dict[str, object] = {}
                    with contextlib.suppress(Exception):
                        pool_snapshot = database_pool_snapshot()
                    logger.warning(
                        'Slow internal runtime RPC method=%s request_id=%s request_ms=%.1f admission_queue_ms=%.1f validation_queue_ms=%.1f '
                        'validation_ms=%.1f executor_queue_ms=%.1f handler_ms=%.1f sql_count=%s sql_ms=%.1f '
                        'db_checkout_count=%s db_checkout_ms=%.1f db_checkout_max_ms=%.1f '
                        'slowest_sql_ms=%.1f slowest_sql=%s commit_ms=%.1f '
                        'namespace=%s resource_id=%s coordinator_generation=%s db_pool=%s phase_timings_ms=%s',
                        func.__name__,
                        request_id,
                        request_ms,
                        rpc_timing.get('admission_queue_ms', 0.0) if rpc_timing is not None else 0.0,
                        validation_queue_ms,
                        validation_ms,
                        max(0.0, worker_started - started) * 1000,
                        max(0.0, worker_finished - handler_started) * 1000,
                        database_timing['sql_count'],
                        float(database_timing['sql_ms']),
                        database_timing.get('db_pool_checkout_count', 0),
                        float(database_timing.get('db_pool_checkout_ms', 0.0)),
                        float(database_timing.get('db_pool_checkout_max_ms', 0.0)),
                        float(database_timing.get('slowest_sql_ms', 0.0)),
                        database_timing.get('slowest_sql_statement', '-'),
                        float(database_timing['commit_ms']),
                        namespace,
                        resource_id,
                        active_runtime_coordinator_generation() or '-',
                        pool_snapshot,
                        {name: round(phase_timings[name], 1) for name in _RPC_PHASE_LOG_ORDER if name in phase_timings},
                    )

                defer_until_serialized = bool(rpc_timing and rpc_timing.get('defer_slow_rpc_diagnostic'))
                if defer_until_serialized and response_ready:
                    rpc_timing['_slow_rpc_diagnostic_callback'] = log_slow_rpc
                else:
                    log_slow_rpc()

        return wrapper

    return decorator


# Claims, completions, publication and maintenance share the bounded general lane.
_general_rpc = _threaded_rpc(_INTERNAL_RPC_EXECUTOR)
# Keep liveness and lease progress RPCs on their protected lane.
_lease_rpc = _threaded_rpc(_INTERNAL_LEASE_RPC_EXECUTOR)
# Protect the singleton scheduler heartbeat from worker lease bursts.
_scheduler_heartbeat_rpc = _threaded_rpc(_INTERNAL_SCHEDULER_RPC_EXECUTOR or _INTERNAL_LEASE_RPC_EXECUTOR)
# Isolate potentially slow provider calls from durable coordinator RPCs.
_external_io_rpc = _threaded_rpc(_INTERNAL_EXTERNAL_IO_EXECUTOR)


class _ThreadedRpcAbort(Exception):
    def __init__(self, status: grpc.StatusCode, details: str) -> None:
        super().__init__(details)
        self.status = status
        self.details = details


def _proto_runtime_worker_kind(value: int) -> RuntimeWorkerKind:
    kind = proto_value_to_enum_name(enums_pb2.RuntimeWorkerKind, 'RUNTIME_WORKER_KIND', value)
    try:
        return RuntimeWorkerKind.require(kind)
    except ValueError as exc:
        raise ValueError(f'Unsupported runtime worker kind: {kind}') from exc


def _build_step_kind_token(message: compute_pb2.BuildStepKind) -> str:
    match message.WhichOneof('kind'):
        case 'pipeline':
            return proto_value_to_enum_name(enums_pb2.StepType, 'STEP_TYPE', message.pipeline)
        case 'execution_category':
            return proto_value_to_enum_name(enums_pb2.ComputeWorkerRunExecutionCategory, 'COMPUTE_WORKER_RUN_EXECUTION_CATEGORY', message.execution_category)
        case _:
            raise ValueError('build step event is missing step_kind')


_RESOURCE_CONFIG_FIELDS = ('max_threads', 'max_memory_mb', 'streaming_chunk_size')


def _build_tab_result_payload(message: compute_pb2.BuildTabResult) -> dict[str, object]:
    return {
        'tab_id': message.tab_id,
        'tab_name': message.tab_name,
        'status': proto_value_to_enum_name(enums_pb2.BuildTabStatus, 'BUILD_TAB_STATUS', message.status),
        **_present_fields(message, ('output_id', 'output_name', 'error')),
    }


def _build_event_payload(message: compute_pb2.BuildEvent) -> dict[str, object]:
    context = message.context
    payload: dict[str, object] = {
        'build_id': context.build_id,
        'analysis_id': context.analysis_id,
        'emitted_at': context.emitted_at.ToDatetime(tzinfo=UTC),
        **_present_fields(context, ('sequence', 'current_datasource_id', 'tab_id', 'tab_name', 'current_output_id', 'current_output_name')),
    }
    if context.HasField('current_kind'):
        payload['current_kind'] = proto_value_to_enum_name(enums_pb2.ComputeWorkerRunKind, 'COMPUTE_WORKER_RUN_KIND', context.current_kind)
    if context.HasField('engine_run_id'):
        payload['compute_worker_run_id'] = context.engine_run_id

    match message.WhichOneof('event'):
        case 'plan':
            payload.update({'type': 'plan', 'optimized_plan': message.plan.optimized_plan, 'unoptimized_plan': message.plan.unoptimized_plan})
        case ('step_started' | 'step_completed' | 'step_failed') as event_name:
            step = getattr(message, event_name)
            payload.update(
                {
                    'type': {'step_started': 'step_start', 'step_completed': 'step_complete'}.get(event_name, event_name),
                    'build_step_index': step.build_step_index,
                    'step_index': step.step_index,
                    'step_id': step.step_id,
                    'step_name': step.step_name,
                    'step_type': _build_step_kind_token(step.step_kind),
                    'total_steps': step.total_steps,
                }
            )
            if event_name == 'step_completed':
                payload['duration_ms'] = step.duration_ms
                payload.update(_present_fields(step, ('row_count',)))
            if event_name == 'step_failed':
                payload['error'] = step.error
        case 'progress':
            payload.update(
                {
                    'type': 'progress',
                    'progress': message.progress.progress,
                    'elapsed_ms': message.progress.elapsed_ms,
                    'total_steps': message.progress.total_steps,
                    **_present_fields(message.progress, ('estimated_remaining_ms', 'current_step', 'current_step_index')),
                }
            )
        case 'resources':
            payload.update(
                {
                    'type': 'resources',
                    'cpu_percent': message.resources.cpu_percent,
                    'memory_mb': message.resources.memory_mb,
                    'active_threads': message.resources.active_threads,
                    **_present_fields(message.resources, ('memory_limit_mb', 'max_threads')),
                }
            )
        case 'log':
            payload.update(
                {
                    'type': 'log',
                    'level': proto_value_to_enum_name(enums_pb2.BuildLogLevel, 'BUILD_LOG_LEVEL', message.log.level),
                    'message': message.log.message,
                    **_present_fields(message.log, ('step_name', 'step_id')),
                }
            )
        case ('completed' | 'failed' | 'cancelled') as event_name:
            terminal = getattr(message, event_name)
            payload.update(
                {
                    'type': 'complete' if event_name == 'completed' else event_name,
                    'progress': terminal.progress,
                    'elapsed_ms': terminal.elapsed_ms,
                    'total_steps': terminal.total_steps,
                    'tabs_built': terminal.tabs_built,
                    'results': [_build_tab_result_payload(result) for result in terminal.results],
                    'duration_ms': terminal.duration_ms,
                    **_present_fields(terminal, ('error', 'cancelled_by')),
                }
            )
            if terminal.HasField('cancelled_at'):
                payload['cancelled_at'] = terminal.cancelled_at.ToDatetime(tzinfo=UTC)
        case _:
            raise ValueError('build event is missing typed event payload')
    return payload


def _compute_worker_run_execution_entry_payload(entry: compute_pb2.ComputeWorkerRunExecutionEntry) -> dict[str, object]:
    payload: dict[str, object] = {
        'key': entry.key,
        'label': entry.label,
        'category': proto_value_to_enum_name(enums_pb2.ComputeWorkerRunExecutionCategory, 'COMPUTE_WORKER_RUN_EXECUTION_CATEGORY', entry.category),
        'order': entry.order,
        **_present_fields(entry, ('duration_ms', 'share_pct', 'optimized_plan', 'unoptimized_plan')),
    }
    if entry.HasField('step_type'):
        payload['metadata'] = {'step_type': proto_value_to_enum_name(enums_pb2.StepType, 'STEP_TYPE', entry.step_type)}
    return payload


def _compute_worker_status_info_payload(message: compute_pb2.ComputeWorkerStatusResult) -> ComputeWorkerStatusInfo:
    return ComputeWorkerStatusInfo(
        analysis_id=message.analysis_id,
        resource_id=message.resource_id,
        status=proto_value_to_enum_name(enums_pb2.ComputeWorkerStatus, 'COMPUTE_WORKER_STATUS', message.status),
        lifecycle_status=proto_value_to_enum_name(enums_pb2.ComputeWorkerInstanceStatus, 'COMPUTE_WORKER_INSTANCE_STATUS', message.lifecycle_status)
        if message.HasField('lifecycle_status')
        else None,
        resource_config=_present_fields(message.resource_config, _RESOURCE_CONFIG_FIELDS) if message.HasField('resource_config') else None,
        effective_resources=_present_fields(message.effective_resources, _RESOURCE_CONFIG_FIELDS) if message.HasField('effective_resources') else None,
        defaults={field: getattr(message.defaults, field) for field in _RESOURCE_CONFIG_FIELDS} if message.HasField('defaults') else {},
        scope=proto_value_to_enum_name(enums_pb2.ComputeWorkerScope, 'COMPUTE_WORKER_SCOPE', message.scope) if message.HasField('scope') else None,
        reuse_policy=proto_value_to_enum_name(enums_pb2.ComputeWorkerReusePolicy, 'COMPUTE_WORKER_REUSE_POLICY', message.reuse_policy)
        if message.HasField('reuse_policy')
        else None,
        current_compute_worker_run_id=_optional(message, 'current_engine_run_id'),
        **{
            field: _optional(message, field)
            for field in (
                'container_id',
                'image_digest',
                'termination_reason',
                'exit_code',
                'oom_killed',
                'supervisor_id',
                'owner_id',
                'docker_host',
                'last_activity',
                'current_job_id',
                'datasource_id',
                'build_id',
                'current_build_id',
            )
        },
    )


def _compute_worker_run_update_fields(update: worker_runtime_pb2.WorkerComputeWorkerRunUpdateFields) -> dict[str, Any]:
    fields: dict[str, Any] = _present_fields(
        update,
        ('analysis_id', 'datasource_id', 'error_message', 'duration_ms', 'query_plan', 'progress', 'triggered_by'),
    )
    if update.HasField('kind'):
        fields['kind'] = proto_value_to_enum_name(enums_pb2.ComputeWorkerRunKind, 'COMPUTE_WORKER_RUN_KIND', update.kind)
    if update.HasField('status'):
        fields['status'] = proto_value_to_enum_name(enums_pb2.ComputeWorkerRunStatus, 'COMPUTE_WORKER_RUN_STATUS', update.status)
    if update.HasField('request_json'):
        fields['request_json'] = struct_to_dict(update.request_json)
    if update.HasField('result_json'):
        fields['result_json'] = struct_to_dict(update.result_json)
    if update.HasField('completed_at'):
        fields['completed_at'] = update.completed_at.ToDatetime(tzinfo=UTC)
    if update.HasField('step_timings'):
        fields['step_timings'] = dict(update.step_timings.values)
    if update.HasField('execution_entries'):
        fields['execution_entries'] = [_compute_worker_run_execution_entry_payload(entry) for entry in update.execution_entries.entries]
    if update.clear_current_step:
        fields['current_step'] = None
    if update.HasField('current_step'):
        fields['current_step'] = update.current_step
    return fields


def _compute_worker_run_finalization(
    request: worker_runtime_pb2.WorkerCompleteComputeRequestRequest | worker_runtime_pb2.WorkerFailComputeRequestRequest,
) -> compute_requests_service.ComputeWorkerRunFinalization | None:
    if not request.HasField('engine_run_finalization'):
        return None
    finalization = request.engine_run_finalization
    if not finalization.HasField('update'):
        raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Compute worker run finalization update is required')
    return compute_requests_service.ComputeWorkerRunFinalization(
        run_id=finalization.run_id,
        fields=_compute_worker_run_update_fields(finalization.update),
        merge_result_json=finalization.merge_result,
    )


def _build_starter_proto(payload: dict[str, object]) -> compute_pb2.BuildStarter:
    message = compute_pb2.BuildStarter()
    for field in ('user_id', 'display_name', 'email', 'triggered_by'):
        value = payload.get(field)
        if isinstance(value, str):
            setattr(message, field, value)
    return message


def _build_resource_config_proto(payload: dict[str, object]) -> compute_pb2.BuildResourceConfigSummary:
    message = compute_pb2.BuildResourceConfigSummary()
    for field in _RESOURCE_CONFIG_FIELDS:
        value = payload.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            setattr(message, field, value)
    return message


def _assert_runtime_coordinator_generation(session: Session) -> None:
    """Start a short DB transaction so its begin hook fences the owner epoch."""
    session.execute(text('SELECT 1'))


def _settle_build_job(
    request: worker_runtime_pb2.WorkerFailBuildJobRequest | worker_runtime_pb2.WorkerFinalizeBuildJobRequest,
    settle: Callable[..., object | None],
    outcome: str,
    **kwargs: Any,
) -> worker_runtime_pb2.BoolResponse:
    with namespace_scope(request.namespace):
        command = build_commands.BuildClaimCommand(
            job_id=request.job_id,
            build_id=request.build_id,
            worker_id=request.worker_id,
            claim_token=request.claim_token,
            lease_generation=request.lease_generation,
        )
        result = run_db(settle, command, **kwargs)
        if result is not None:
            # The build outcome is already durable; the scheduler reconciles the run later if this fails.
            try:
                run_db(scheduler_service.reconcile_schedule_run, build_id=request.build_id)
            except Exception:
                logger.warning('Schedule reconciliation deferred after durable build %s build_id=%s', outcome, request.build_id, exc_info=True)
    return worker_runtime_pb2.BoolResponse(value=result is not None)


def _notification_attachments(request: worker_runtime_pb2.WorkerSendEmailRequest | worker_runtime_pb2.WorkerSendTelegramRequest) -> list[dict[str, object]]:
    return [{'filename': item.filename, 'content_base64': item.content_base64, 'content_type': item.content_type} for item in request.attachments]


class WorkerRuntimeServicer(worker_runtime_pb2_grpc.WorkerRuntimeServiceServicer):
    @_general_rpc
    def RegisterWorker(self, request: worker_runtime_pb2.RuntimeWorkerRegisterRequest, metadata: RpcMetadata) -> common_pb2.RuntimeWorkerResponse:
        run_settings_db(
            runtime_worker_service.register_worker,
            worker_id=request.worker_id,
            kind=_proto_runtime_worker_kind(request.kind),
            hostname=request.hostname,
            pid=request.pid,
            capacity=request.capacity,
            active_jobs=request.active_jobs,
        )
        return common_pb2.RuntimeWorkerResponse(worker_id=request.worker_id)

    @_lease_rpc
    def HeartbeatWorker(self, request: worker_runtime_pb2.RuntimeWorkerHeartbeatRequest, metadata: RpcMetadata) -> common_pb2.RuntimeWorkerResponse:
        run_critical_settings_db(runtime_worker_service.heartbeat_worker, worker_id=request.worker_id, active_jobs=_optional(request, 'active_jobs'))
        return common_pb2.RuntimeWorkerResponse(worker_id=request.worker_id)

    @_general_rpc
    def StopWorker(self, request: common_pb2.RuntimeWorkerRequest, metadata: RpcMetadata) -> common_pb2.RuntimeWorkerResponse:
        run_settings_db(runtime_worker_service.mark_worker_stopped, worker_id=request.worker_id)
        return common_pb2.RuntimeWorkerResponse(worker_id=request.worker_id)

    @_general_rpc
    def ClaimBuildJob(self, request: common_pb2.RuntimeWorkerRequest, metadata: RpcMetadata) -> worker_runtime_pb2.WorkerClaimBuildJobResponse:
        if request.protocol_version != _BUILD_JOB_PROTOCOL_VERSION:
            raise _ThreadedRpcAbort(grpc.StatusCode.FAILED_PRECONDITION, 'Build worker protocol version is incompatible')
        if not request.target_namespace:
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Build worker claim must target a namespace')
        with namespace_scope(request.target_namespace):
            # Reconciliation is performed by the bounded recovery/count path.
            # A claim must only inspect the directed namespace's next job; the
            # old full exhausted-job scan here ran once per worker poll and
            # multiplied database work during a browser burst. A stopped or
            # disconnected owner is recovered by its durable lease expiry; a
            # cooperative child releases its own claim before stopping.
            job = run_db(build_job_service.claim_next_job, worker_id=request.worker_id)
        if job is None:
            return worker_runtime_pb2.WorkerClaimBuildJobResponse()
        if job.claim_token is None or job.lease_expires_at is None:
            raise RuntimeError(f'Claimed build job {job.id} is missing lease identity')
        return worker_runtime_pb2.WorkerClaimBuildJobResponse(
            job=worker_runtime_pb2.WorkerClaimedBuildJob(
                job_id=job.id,
                build_id=job.build_id,
                namespace=job.namespace,
                claim_token=job.claim_token,
                lease_generation=job.lease_generation,
                lease_expires_at=datetime_to_timestamp(job.lease_expires_at),
                attempt=job.attempts,
                lease_ttl_seconds=CLAIM_DELIVERY_LEASE_SECONDS,
            )
        )

    @_lease_rpc
    def RenewBuildJobLease(
        self, request: worker_runtime_pb2.WorkerBuildJobClaimRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.WorkerRenewBuildJobLeaseResponse:
        with namespace_scope(request.namespace):
            renewal = run_critical_db(
                build_job_service.renew_job_lease,
                request.job_id,
                worker_id=request.worker_id,
                claim_token=request.claim_token,
                lease_generation=request.lease_generation,
            )
        response = worker_runtime_pb2.WorkerRenewBuildJobLeaseResponse(
            renewed=renewal is not None,
            lease_ttl_seconds=settings.runtime_work_lease_ttl_seconds if renewal is not None else None,
        )
        if renewal is not None and renewal.lease_expires_at is not None:
            response.lease_expires_at.CopyFrom(datetime_to_timestamp(renewal.lease_expires_at))
        return response

    @_general_rpc
    def ClaimComputeRequest(self, request: common_pb2.RuntimeWorkerRequest, metadata: RpcMetadata) -> worker_runtime_pb2.WorkerClaimComputeRequestResponse:
        if request.protocol_version != _BUILD_JOB_PROTOCOL_VERSION:
            raise _ThreadedRpcAbort(grpc.StatusCode.FAILED_PRECONDITION, 'Compute worker protocol version is incompatible')
        if not request.target_namespace:
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Compute request claim must target a namespace')
        with namespace_scope(request.target_namespace):
            # The claim is directed and lease expiry is the durable recovery
            # boundary. Do not query the settings database for a registry of
            # stale workers on every request claim: a heartbeat race must not
            # invalidate the lease of a manager that is still executing work.
            compute_request = run_db(
                compute_requests_service.claim_next_request,
                worker_id=request.worker_id,
                allowed_kinds=request.allowed_compute_request_kinds,
            )
            if compute_request is None:
                return worker_runtime_pb2.WorkerClaimComputeRequestResponse()
            if compute_request.claim_token is None or compute_request.lease_expires_at is None:
                raise RuntimeError(f'Claimed compute request {compute_request.id} is missing lease identity')
            return worker_runtime_pb2.WorkerClaimComputeRequestResponse(
                request=worker_runtime_pb2.WorkerClaimedComputeRequest(
                    id=compute_request.id,
                    namespace=compute_request.namespace,
                    kind=kind_from_proto(compute_request.kind),
                    command=compute_requests_service.command_envelope_for_request(compute_request),
                    claim_token=compute_request.claim_token,
                    lease_generation=compute_request.lease_generation,
                    lease_expires_at=datetime_to_timestamp(compute_request.lease_expires_at),
                    attempt=compute_request.attempts,
                    lease_ttl_seconds=CLAIM_DELIVERY_LEASE_SECONDS,
                )
            )

    @_lease_rpc
    def RenewComputeRequestLeases(
        self, request: worker_runtime_pb2.WorkerRenewComputeRequestLeasesRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.WorkerRenewComputeRequestLeasesResponse:
        claims = [
            compute_requests_service.ComputeRequestLeaseClaim(
                request_id=claim.request_id,
                claim_token=claim.claim_token,
                lease_generation=claim.lease_generation,
            )
            for claim in request.renewals
        ]
        request_ids = [claim.request_id for claim in claims]
        if len(request_ids) != len(set(request_ids)):
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Compute lease renewal batch contains duplicate request IDs')
        with namespace_scope(request.namespace):
            renewed_ids = run_critical_db(compute_requests_service.renew_request_leases, claims, worker_id=request.worker_id)
        response = worker_runtime_pb2.WorkerRenewComputeRequestLeasesResponse()
        for claim in claims:
            renewed = claim.request_id in renewed_ids
            result = response.renewals.add(request_id=claim.request_id, renewed=renewed)
            if renewed:
                result.lease_ttl_seconds = settings.runtime_work_lease_ttl_seconds
        return response

    @_general_rpc
    def CompleteComputeRequest(
        self, request: worker_runtime_pb2.WorkerCompleteComputeRequestRequest, metadata: RpcMetadata
    ) -> common_pb2.RuntimeWorkerResponse:
        with namespace_scope(request.namespace):
            completed = run_db(
                compute_requests_service.mark_request_completed,
                request.request_id,
                response_envelope=request.response_envelope,
                worker_id=request.worker_id,
                claim_token=request.claim_token,
                lease_generation=request.lease_generation,
                artifact_path=_optional(request, 'artifact_path'),
                artifact_name=_optional(request, 'artifact_name'),
                artifact_content_type=_optional(request, 'artifact_content_type'),
                compute_worker_run_finalization=_compute_worker_run_finalization(request),
            )
        if completed is None:
            raise _ThreadedRpcAbort(grpc.StatusCode.FAILED_PRECONDITION, 'Compute request lease is no longer active')
        return common_pb2.RuntimeWorkerResponse(worker_id=request.request_id)

    @_general_rpc
    def FailComputeRequest(self, request: worker_runtime_pb2.WorkerFailComputeRequestRequest, metadata: RpcMetadata) -> common_pb2.RuntimeWorkerResponse:
        with namespace_scope(request.namespace):
            failed = run_db(
                compute_requests_service.mark_request_failed,
                request.request_id,
                error_message=request.error_message,
                response_envelope=request.response_envelope,
                worker_id=request.worker_id,
                claim_token=request.claim_token,
                lease_generation=request.lease_generation,
                compute_worker_run_finalization=_compute_worker_run_finalization(request),
            )
        if failed is None:
            raise _ThreadedRpcAbort(grpc.StatusCode.FAILED_PRECONDITION, 'Compute request lease is no longer active')
        return common_pb2.RuntimeWorkerResponse(worker_id=request.request_id)

    @_general_rpc
    def RegisterDatasourceStage(
        self, request: worker_runtime_pb2.WorkerRegisterDatasourceStageRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.BoolResponse:
        is_compute_owner = request.WhichOneof('owner') == 'compute_request_id'
        with namespace_scope(request.namespace):
            try:
                run_db(
                    storage_cleanup_service.register_stage,
                    datasource_id=request.datasource_id,
                    owner_kind='compute' if is_compute_owner else 'build',
                    owner_id=request.compute_request_id if is_compute_owner else request.job_id,
                    worker_id=request.worker_id,
                    claim_token=request.claim_token,
                    lease_generation=request.lease_generation,
                    prefix_url=request.prefix_url,
                    manifest_url=request.artifact_url,
                    catalog_identifier=request.catalog_identifier,
                    build_id=_optional(request, 'build_id'),
                )
            except storage_cleanup_service.StorageCleanupConflict as exc:
                raise _ThreadedRpcAbort(grpc.StatusCode.FAILED_PRECONDITION, str(exc)) from exc
        return worker_runtime_pb2.BoolResponse(value=True)

    @_general_rpc
    def ClaimStorageCleanup(
        self, request: worker_runtime_pb2.WorkerClaimStorageCleanupRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.WorkerStorageCleanupClaimsResponse:
        with namespace_scope(request.namespace):
            claims = run_db(storage_cleanup_service.claim_cleanups, limit=request.limit)
        cleanups = []
        for claim in claims:
            cleanup = worker_runtime_pb2.WorkerStorageCleanupClaim(
                claim=worker_runtime_pb2.WorkerStorageCleanupClaimRequest(
                    namespace=request.namespace,
                    event_id=claim.event_id,
                    claim_token=claim.claim_token,
                    lease_generation=claim.lease_generation,
                ),
                resource_id=str(claim.payload['resource_id']),
                url=str(claim.payload['url']),
                is_prefix=claim.payload['is_prefix'] is True,
            )
            for field in (
                'catalog_identifier',
                'catalog_type',
                'catalog_uri',
                'warehouse',
                'catalog_namespace',
                'catalog_table',
                'catalog_family_prefix',
            ):
                value = claim.payload.get(field)
                if isinstance(value, str):
                    setattr(cleanup, field, value)
            cleanups.append(cleanup)
        return worker_runtime_pb2.WorkerStorageCleanupClaimsResponse(cleanups=cleanups)

    @_general_rpc
    def AuthorizeStorageCleanup(self, request: worker_runtime_pb2.WorkerStorageCleanupClaimRequest, metadata: RpcMetadata) -> worker_runtime_pb2.BoolResponse:
        with namespace_scope(request.namespace):
            authorized = run_db(
                storage_cleanup_service.authorize_cleanup,
                event_id=request.event_id,
                claim_token=request.claim_token,
                lease_generation=request.lease_generation,
            )
        return worker_runtime_pb2.BoolResponse(value=authorized)

    @_general_rpc
    def CompleteStorageCleanup(self, request: worker_runtime_pb2.WorkerCompleteStorageCleanupRequest, metadata: RpcMetadata) -> worker_runtime_pb2.BoolResponse:
        with namespace_scope(request.claim.namespace):
            completed = run_db(
                storage_cleanup_service.complete_cleanup,
                event_id=request.claim.event_id,
                claim_token=request.claim.claim_token,
                lease_generation=request.claim.lease_generation,
                error=_optional(request, 'error'),
            )
        return worker_runtime_pb2.BoolResponse(value=completed)

    @_general_rpc
    def PublishDatasourceCreate(
        self, request: worker_runtime_pb2.WorkerPublishDatasourceCreateRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.WorkerPublishDatasourceCreateResponse:

        def guard_publication(active_session: Session) -> None:
            claim = compute_requests_service.lock_active_request_claim(
                active_session,
                request.compute_request_id,
                worker_id=request.worker_id,
                claim_token=request.claim_token,
                lease_generation=request.lease_generation,
            )
            if claim is None or request.datasource_id != request.compute_request_id:
                raise _ThreadedRpcAbort(grpc.StatusCode.FAILED_PRECONDITION, 'Datasource create publication claim is no longer active')

        with _tenant_session(request.namespace) as session:
            try:
                response = datasource_publication_service.create_datasource(
                    session,
                    datasource_id=request.datasource_id,
                    name=request.name,
                    description=_optional(request, 'description'),
                    source_type=proto_value_to_enum_name(enums_pb2.DataSourceType, 'DATA_SOURCE_TYPE', request.source_type),
                    config=struct_to_dict(request.config),
                    owner_id=_optional(request, 'owner_id'),
                    schema_info=request.schema_info if request.HasField('schema_info') and request.schema_info.columns else None,
                    publication_guard=guard_publication,
                )
            except storage_cleanup_service.StorageCleanupConflict as exc:
                raise _ThreadedRpcAbort(grpc.StatusCode.FAILED_PRECONDITION, str(exc)) from exc
            record = datasource_result_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE, response.model_dump(mode='json'))
            if record.WhichOneof('result') != 'datasource':
                raise ValueError('create publication must return a datasource result')
            return worker_runtime_pb2.WorkerPublishDatasourceCreateResponse(datasource=record.datasource)

    @_general_rpc
    def PublishDatasourceIngest(
        self, request: worker_runtime_pb2.WorkerPublishDatasourceIngestRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.WorkerPublishDatasourceIngestResponse:
        has_compute = request.HasField('compute_request_id')
        has_build = request.HasField('job_id') or request.HasField('build_id')
        if has_compute == has_build:
            raise _ThreadedRpcAbort(
                grpc.StatusCode.INVALID_ARGUMENT,
                'Ingest publication requires exactly one of compute_request_id or build job claim fields',
            )
        if has_build and not (request.HasField('job_id') and request.HasField('build_id')):
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Build job claim fields must be provided together')

        def guard_publication(active_session: Session) -> None:
            if has_compute:
                claim: object = compute_requests_service.lock_active_request_claim(
                    active_session,
                    request.compute_request_id,
                    worker_id=request.worker_id,
                    claim_token=request.claim_token,
                    lease_generation=request.lease_generation,
                )
            else:
                claim = build_job_service.lock_active_job_claim(
                    active_session,
                    request.job_id,
                    build_id=request.build_id,
                    worker_id=request.worker_id,
                    claim_token=request.claim_token,
                    lease_generation=request.lease_generation,
                )
            if claim is None:
                raise datasource_publication_service.DatasourcePublicationClaimLost

        with _tenant_session(request.namespace) as session:
            try:
                response = datasource_publication_service.publish_ingest(
                    session,
                    datasource_id=request.datasource_id,
                    config=struct_to_dict(request.config),
                    expected_revision=int(request.expected_revision),
                    schema_info=request.schema_info if request.HasField('schema_info') and request.schema_info.columns else None,
                    publication_guard=guard_publication,
                )
            except datasource_publication_service.DatasourcePublicationClaimLost as exc:
                raise _ThreadedRpcAbort(grpc.StatusCode.FAILED_PRECONDITION, str(exc) or 'Datasource publication claim is no longer active') from exc
            except storage_cleanup_service.StorageCleanupConflict as exc:
                raise _ThreadedRpcAbort(grpc.StatusCode.FAILED_PRECONDITION, str(exc)) from exc
            record = datasource_result_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE, response.model_dump(mode='json'))
            if record.WhichOneof('result') != 'datasource':
                raise ValueError('ingest publication must return a datasource result')
            return worker_runtime_pb2.WorkerPublishDatasourceIngestResponse(datasource=record.datasource)

    @_general_rpc
    def PublishDatasourceSchemaCache(
        self, request: worker_runtime_pb2.WorkerPublishDatasourceSchemaCacheRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.WorkerPublishDatasourceSchemaCacheResponse:
        def guard_publication(active_session: Session) -> None:
            request_claim = compute_requests_service.lock_active_request_claim(
                active_session,
                request.compute_request_id,
                worker_id=request.worker_id,
                claim_token=request.claim_token,
                lease_generation=request.lease_generation,
                include_command_envelope=True,
            )
            if request_claim is None:
                raise datasource_publication_service.DatasourcePublicationClaimLost('Datasource schema publication claim is no longer active')
            if request_claim.kind != enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA:
                raise datasource_publication_service.DatasourcePublicationClaimLost('Datasource schema publication claim has a different compute request kind')
            try:
                command = compute_requests_service.command_envelope_for_request(request_claim).command
            except ValueError as exc:
                raise datasource_publication_service.DatasourcePublicationClaimLost(
                    'Datasource schema publication claim has an invalid command snapshot'
                ) from exc
            if command.WhichOneof('command') != 'datasource' or command.datasource.WhichOneof('command') != 'schema':
                raise datasource_publication_service.DatasourcePublicationClaimLost('Datasource schema publication claim does not contain a schema command')
            if command.datasource.schema.datasource_id != request.datasource_id:
                raise datasource_publication_service.DatasourcePublicationClaimLost('Datasource schema publication claim targets a different datasource')
            source_revisions = [revision.revision for revision in command.input_revisions if revision.datasource_id == request.datasource_id]
            if len(source_revisions) != 1:
                raise datasource_publication_service.DatasourcePublicationClaimLost(
                    'Datasource schema publication claim has no unique source revision snapshot'
                )
            if source_revisions[0] != request.expected_revision:
                raise datasource_publication_service.DatasourcePublicationRevisionChanged(
                    'Datasource schema publication revision does not match its claimed command snapshot'
                )

        with _tenant_session(request.namespace) as session:
            try:
                published = datasource_publication_service.publish_schema_cache(
                    session,
                    datasource_id=request.datasource_id,
                    expected_revision=int(request.expected_revision),
                    schema_info=request.schema_info,
                    publication_guard=guard_publication,
                )
            except datasource_publication_service.DatasourcePublicationRevisionChanged as exc:
                raise _ThreadedRpcAbort(grpc.StatusCode.ABORTED, str(exc)) from exc
            except datasource_publication_service.DatasourcePublicationClaimLost as exc:
                raise _ThreadedRpcAbort(grpc.StatusCode.FAILED_PRECONDITION, str(exc)) from exc
            except AppError as exc:
                if exc.error_code != 'DATASOURCE_NOT_FOUND':
                    raise
                raise _ThreadedRpcAbort(grpc.StatusCode.NOT_FOUND, str(exc)) from exc
            return worker_runtime_pb2.WorkerPublishDatasourceSchemaCacheResponse(schema_info=published)

    @_general_rpc
    def GetDatasourceMetadata(
        self, request: worker_runtime_pb2.WorkerDatasourceMetadataRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.WorkerDatasourceMetadataResponse:
        def _load_metadata() -> tuple[str, str, str, dict[str, object], bool, int, str, str | None, dict | None, dict[str, str]] | None:
            with _tenant_session(request.namespace) as session:
                datasource = _record_rpc_phase('datasource_row_lookup_ms', lambda: session.get(DataSource, request.datasource_id))
                if datasource is None:
                    return None
                metadata_values = _record_rpc_phase(
                    'datasource_payload_conversion_ms',
                    lambda: (
                        datasource.id,
                        datasource.name,
                        datasource.source_type,
                        dict(datasource.config),
                        datasource.is_hidden,
                        int(datasource.revision),
                        str(datasource.created_by),
                        datasource.description,
                        dict(datasource.schema_cache) if isinstance(datasource.schema_cache, dict) else None,
                    ),
                )
                descriptions = _record_rpc_phase(
                    'column_descriptions_service_ms',
                    lambda: datasource_publication_service.column_description_map(session, datasource.id),
                )
                return (*metadata_values, descriptions)

        datasource_metadata = _record_rpc_phase('db_unit_ms', _load_metadata)
        if datasource_metadata is None:
            return _record_rpc_phase(
                'response_transformation_ms',
                lambda: worker_runtime_pb2.WorkerDatasourceMetadataResponse(found=False),
            )

        def _build_response() -> worker_runtime_pb2.WorkerDatasourceMetadataResponse:
            datasource_id, name, source_type, config, is_hidden, revision, created_by, description, schema_cache, descriptions = datasource_metadata
            response = worker_runtime_pb2.WorkerDatasourceMetadataResponse(
                found=True,
                id=datasource_id,
                name=name,
                source_type=_proto_enum_value('DATA_SOURCE_TYPE', source_type),
                config=dict_to_struct(config),
                is_hidden=is_hidden,
                revision=revision,
                created_by=created_by,
                description=description,
                column_descriptions=descriptions,
            )
            if schema_cache is not None:
                response.schema_info.CopyFrom(schema_info_proto(schema_cache))
            return response

        return _record_rpc_phase('response_transformation_ms', _build_response)

    @_general_rpc
    def GetUdfCodes(self, request: worker_runtime_pb2.WorkerUdfCodesRequest, metadata: RpcMetadata) -> worker_runtime_pb2.WorkerUdfCodesResponse:
        ids = [udf_id for udf_id in request.udf_ids if udf_id]
        if not ids:
            return worker_runtime_pb2.WorkerUdfCodesResponse()
        with _tenant_session(request.namespace) as session:
            codes = {udf.id: udf.code for udf in session.execute(select(Udf).where(col(Udf.id).in_(ids))).scalars().all()}
        return worker_runtime_pb2.WorkerUdfCodesResponse(codes=codes)

    @_general_rpc
    def GetComputeWorkerCredentials(
        self, request: worker_runtime_pb2.WorkerComputeWorkerCredentialsRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.WorkerComputeWorkerCredentialsResponse:
        from backend_core.namespace_credentials_service import NamespaceCredentialError, resolve_namespace_engine_credentials

        try:
            access_key, secret_key = run_settings_db(resolve_namespace_engine_credentials, request.namespace, request.role)
        except NamespaceCredentialError as exc:
            raise _ThreadedRpcAbort(grpc.StatusCode.NOT_FOUND, str(exc)) from exc
        return worker_runtime_pb2.WorkerComputeWorkerCredentialsResponse(access_key=access_key, secret_key=secret_key)

    @_general_rpc
    def GetAnalysisMetadata(
        self, request: worker_runtime_pb2.WorkerAnalysisMetadataRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.WorkerAnalysisMetadataResponse:
        with _tenant_session(request.namespace) as session:
            analysis = session.get(Analysis, request.analysis_id)
            if analysis is None:
                return worker_runtime_pb2.WorkerAnalysisMetadataResponse(found=False)
            return worker_runtime_pb2.WorkerAnalysisMetadataResponse(found=True, name=analysis.name)

    @_general_rpc
    def GetBuildCancelStatus(
        self, request: worker_runtime_pb2.WorkerBuildCancelStatusRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.WorkerBuildCancelStatusResponse:
        with namespace_scope(request.namespace):
            run = run_db(build_run_service.get_build_run, request.build_id)
        if run is None or run.status != BuildRunStatus.CANCELLED:
            return worker_runtime_pb2.WorkerBuildCancelStatusResponse(cancelled=False)
        cancelled_by = run.cancelled_by if isinstance(run.cancelled_by, str) else None
        response = worker_runtime_pb2.WorkerBuildCancelStatusResponse(cancelled=True, cancelled_by=cancelled_by)
        if isinstance(run.cancelled_at, datetime):
            response.cancelled_at.CopyFrom(datetime_to_timestamp(run.cancelled_at))
        return response

    @_general_rpc
    def UpdateBuildResult(self, request: worker_runtime_pb2.WorkerUpdateBuildResultRequest, metadata: RpcMetadata) -> common_pb2.RuntimeWorkerResponse:
        with _tenant_session(request.namespace) as session:
            claim = build_job_service.lock_active_job_claim(
                session,
                request.job_id,
                build_id=request.build_id,
                worker_id=request.worker_id,
                claim_token=request.claim_token,
                lease_generation=request.lease_generation,
            )
            if claim is None:
                raise _ThreadedRpcAbort(grpc.StatusCode.FAILED_PRECONDITION, 'Build job lease is no longer active')
            build_run_service.update_build_result_json(session, request.build_id, struct_to_dict(request.result))
        return common_pb2.RuntimeWorkerResponse(worker_id=request.build_id)

    @_general_rpc
    def UpsertOutputDatasource(
        self, request: worker_runtime_pb2.WorkerUpsertOutputDatasourceRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.WorkerUpsertOutputDatasourceResponse:
        claim_fields = ('job_id', 'build_id', 'worker_id', 'claim_token', 'lease_generation')
        if any(request.HasField(field) for field in claim_fields) != all(request.HasField(field) for field in claim_fields):
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Output publication claim fields must be provided together')
        publication_claim = None
        if request.HasField('build_id'):
            if not request.HasField('build_result'):
                raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Claimed output publication requires a build result')
            publication_claim = datasource_commands.OutputPublicationClaim(
                job_id=request.job_id,
                build_id=request.build_id,
                worker_id=request.worker_id,
                claim_token=request.claim_token,
                lease_generation=request.lease_generation,
                build_result=struct_to_dict(request.build_result),
            )
        notification_deliveries: list[dict[str, object]] = []
        for delivery in request.notification_delivery:
            match delivery.WhichOneof('delivery'):
                case 'email':
                    notification_deliveries.append(
                        {
                            'kind': EMAIL_DELIVERY_KIND,
                            'to': delivery.email.to,
                            'subject': delivery.email.subject,
                            'body': delivery.email.body,
                            'attachments': [],
                        }
                    )
                case 'telegram':
                    notification_deliveries.append(
                        {
                            'kind': TELEGRAM_DELIVERY_KIND,
                            'chat_id': delivery.telegram.chat_id,
                            'message': delivery.telegram.message,
                            'attachments': [],
                            **_present_fields(delivery.telegram, ('bot_token',)),
                        }
                    )
                case _:
                    raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Notification delivery command is missing its delivery payload')
        with _tenant_session(request.namespace) as session:
            try:
                datasource = datasource_commands.upsert_output_datasource(
                    session,
                    result_id=request.result_id,
                    name=request.name,
                    source_type=proto_value_to_enum_name(enums_pb2.DataSourceType, 'DATA_SOURCE_TYPE', request.source_type),
                    config=struct_to_dict(request.config),
                    schema_cache=schema_info_payload(request.schema_info),
                    keep_schema_cache=request.keep_schema_cache,
                    analysis_id=_optional(request, 'analysis_id'),
                    is_hidden=_optional(request, 'is_hidden'),
                    claim=publication_claim,
                    notification_deliveries=notification_deliveries,
                )
            except datasource_commands.OutputPublicationClaimLost as exc:
                raise _ThreadedRpcAbort(grpc.StatusCode.FAILED_PRECONDITION, str(exc)) from exc
            return worker_runtime_pb2.WorkerUpsertOutputDatasourceResponse(
                datasource_id=datasource.id,
                datasource_name=datasource.name,
                is_hidden=datasource.is_hidden,
            )

    @_general_rpc
    def ListHealthChecks(
        self, request: worker_runtime_pb2.WorkerListHealthChecksRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.WorkerListHealthChecksResponse:
        with _tenant_session(request.namespace) as session:
            checks = session.execute(select(HealthCheck).where(sa(HealthCheck.datasource_id == request.datasource_id))).scalars().all()
            return worker_runtime_pb2.WorkerListHealthChecksResponse(
                checks=[
                    worker_runtime_pb2.WorkerHealthCheckSpec(
                        id=check.id,
                        name=check.name,
                        check_type=_proto_enum_value('HEALTH_CHECK_TYPE', check.check_type),
                        config=dict_to_struct(dict(check.config)),
                        critical=check.critical,
                    )
                    for check in checks
                    if check.enabled
                ]
            )

    @_general_rpc
    def RecordHealthCheckResults(
        self, request: worker_runtime_pb2.WorkerRecordHealthCheckResultsRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.CountResponse:
        with _tenant_session(request.namespace) as session:
            count = healthcheck_commands.record_results(
                session,
                (
                    HealthCheckResult(
                        id=str(uuid.uuid4()),
                        healthcheck_id=result.healthcheck_id,
                        passed=result.passed,
                        message=result.message,
                        details=struct_to_dict(result.details),
                        checked_at=result.checked_at.ToDatetime(tzinfo=UTC),
                    )
                    for result in request.results
                ),
            )
        return worker_runtime_pb2.CountResponse(count=count)

    @_general_rpc
    def CreateComputeWorkerRun(self, request: worker_runtime_pb2.WorkerCreateComputeWorkerRunRequest, metadata: RpcMetadata) -> worker_runtime_pb2.IdResponse:
        with namespace_scope(request.namespace):
            payload_fields: dict[str, Any] = _record_rpc_phase(
                'payload_conversion_ms',
                lambda: dict(
                    analysis_id=_optional(request, 'analysis_id'),
                    datasource_id=request.datasource_id,
                    kind=proto_value_to_enum_name(enums_pb2.ComputeWorkerRunKind, 'COMPUTE_WORKER_RUN_KIND', request.kind),
                    status=proto_value_to_enum_name(enums_pb2.ComputeWorkerRunStatus, 'COMPUTE_WORKER_RUN_STATUS', request.status),
                    request_json=struct_to_dict(request.request),
                    result_json=struct_to_dict(request.result) if request.HasField('result') else None,
                    error_message=_optional(request, 'error_message'),
                    created_at=request.created_at.ToDatetime(tzinfo=UTC) if request.HasField('created_at') else None,
                    completed_at=request.completed_at.ToDatetime(tzinfo=UTC) if request.HasField('completed_at') else None,
                    duration_ms=_optional(request, 'duration_ms'),
                    step_timings=dict(request.timing_by_key) if request.timing_by_key else None,
                    query_plan=_optional(request, 'query_plan'),
                    execution_entries=[_compute_worker_run_execution_entry_payload(entry) for entry in request.execution_entry] or None,
                    progress=request.progress,
                    current_step=_optional(request, 'current_step'),
                    triggered_by=_optional(request, 'triggered_by'),
                    idempotency_key=_optional(request, 'idempotency_key'),
                ),
            )
            payload = _record_rpc_phase(
                'compute_worker_run_payload_service_ms',
                lambda: compute_worker_run_service.create_compute_worker_run_payload(**payload_fields),
            )

            def _persist(session: Session) -> Any:
                return _record_rpc_phase(
                    'compute_worker_run_persistence_service_ms',
                    lambda: compute_worker_run_service.create_compute_worker_run(session, payload),
                )

            run = _record_rpc_phase('db_unit_ms', lambda: run_db(_persist))
            return _record_rpc_phase('response_transformation_ms', lambda: worker_runtime_pb2.IdResponse(id=run.id))

    @_general_rpc
    def UpdateComputeWorkerRun(self, request: worker_runtime_pb2.WorkerUpdateComputeWorkerRunRequest, metadata: RpcMetadata) -> worker_runtime_pb2.IdResponse:
        fields = _compute_worker_run_update_fields(request.update)
        with namespace_scope(request.namespace):
            run = run_db(compute_worker_run_service.update_compute_worker_run, request.run_id, merge_result_json=request.merge_result, **fields)
        return worker_runtime_pb2.IdResponse(id=run.id)

    @_general_rpc
    def GetComputeWorkerRunState(
        self, request: worker_runtime_pb2.WorkerComputeWorkerRunStateRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.WorkerComputeWorkerRunStateResponse:
        with namespace_scope(request.namespace):
            run = run_db(compute_worker_run_service.get_compute_worker_run, request.run_id)
        if run is None:
            return worker_runtime_pb2.WorkerComputeWorkerRunStateResponse(found=False)
        result_json = dict(run.result_json) if isinstance(run.result_json, dict) else {}
        cancelled_at = result_json.get('cancelled_at')
        cancelled_by = result_json.get('cancelled_by')
        response = worker_runtime_pb2.WorkerComputeWorkerRunStateResponse(
            found=True,
            status=_proto_enum_value('COMPUTE_WORKER_RUN_STATUS', run.status),
            result=dict_to_struct(result_json),
            cancelled_by=cancelled_by if isinstance(cancelled_by, str) else None,
        )
        if isinstance(cancelled_at, str):
            response.cancelled_at.CopyFrom(datetime_to_timestamp(datetime.fromisoformat(cancelled_at)))
        return response

    @_general_rpc
    def FailBuildJob(self, request: worker_runtime_pb2.WorkerFailBuildJobRequest, metadata: RpcMetadata) -> worker_runtime_pb2.BoolResponse:
        return _settle_build_job(request, build_commands.fail_build_job, 'failure', error=request.error)

    @_general_rpc
    def FinalizeBuildJob(self, request: worker_runtime_pb2.WorkerFinalizeBuildJobRequest, metadata: RpcMetadata) -> worker_runtime_pb2.BoolResponse:
        return _settle_build_job(request, build_commands.finalize_build_job, 'completion')

    @_general_rpc
    def ReleaseBuildWorkerJobs(self, request: common_pb2.RuntimeWorkerRequest, metadata: RpcMetadata) -> worker_runtime_pb2.CountResponse:
        if not request.target_namespace:
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Build worker release must target a namespace')
        with namespace_scope(request.target_namespace):
            released = run_db(build_job_service.release_worker_jobs, worker_id=request.worker_id)
        return worker_runtime_pb2.CountResponse(count=len(released))

    @_general_rpc
    def GetQueuedBuildJobCount(self, request: common_pb2.EmptyRequest, metadata: RpcMetadata) -> worker_runtime_pb2.CountResponse:
        if not request.namespace:
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Queued build count must target a namespace')
        with namespace_scope(request.namespace):
            return worker_runtime_pb2.CountResponse(count=run_db(build_job_service.queued_job_count))

    @_general_rpc
    def ReconcileExpiredBuildJobs(self, request: common_pb2.EmptyRequest, metadata: RpcMetadata) -> worker_runtime_pb2.CountResponse:
        if not request.namespace:
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Build job reconciliation must target a namespace')
        with namespace_scope(request.namespace):
            return worker_runtime_pb2.CountResponse(count=run_db(scheduler_commands.reconcile_expired_build_jobs))

    @_general_rpc
    def ReconcileExpiredComputeRequests(self, request: common_pb2.EmptyRequest, metadata: RpcMetadata) -> worker_runtime_pb2.CountResponse:
        if not request.namespace:
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Compute request reconciliation must target a namespace')
        with namespace_scope(request.namespace):
            return worker_runtime_pb2.CountResponse(count=run_db(compute_requests_service.reconcile_expired_requests, namespace=request.namespace))

    @_general_rpc
    def GetIdleBuildWorkerPids(self, request: common_pb2.EmptyRequest, metadata: RpcMetadata) -> worker_runtime_pb2.WorkerIdlePidsResponse:
        workers = run_settings_db(runtime_worker_service.list_workers, kind=RuntimeWorkerKind.BUILD_WORKER)
        return worker_runtime_pb2.WorkerIdlePidsResponse(pids=[worker.pid for worker in workers if worker.stopped_at is None and worker.active_jobs == 0])

    @_general_rpc
    def ListPendingRuntimeWorkNamespaces(
        self, request: worker_runtime_pb2.WorkerPendingRuntimeWorkNamespacesRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.WorkerNamespacesResponse:
        try:
            kinds = tuple(sorted({runtime_work_service.RuntimeWorkKind(kind) for kind in request.kinds})) or runtime_work_service.WORKER_RECOVERY_KINDS
        except ValueError as exc:
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, f'Unknown runtime work kind: {exc}') from exc
        return worker_runtime_pb2.WorkerNamespacesResponse(namespaces=_cached_pending_runtime_work_namespaces(kinds))

    @_general_rpc
    def PersistBuildEvent(
        self, request: worker_runtime_pb2.WorkerPersistBuildEventRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.WorkerPersistBuildEventResponse:
        started = time.perf_counter()
        timings: dict[str, float] = {}
        token = set_namespace_context(request.namespace)
        session_gen: Iterator[Session] | None = None
        event_type = 'invalid'
        result: tuple[object, int] | None = None
        try:
            phase_started = time.perf_counter()
            event = compute_schemas.BuildEventAdapter.validate_python(_build_event_payload(request.build_event))
            event_type = str(event.type)
            timings['validation_ms'] = (time.perf_counter() - phase_started) * 1000

            phase_started = time.perf_counter()
            session_gen = get_db()
            session = next(session_gen)
            timings['session_open_ms'] = (time.perf_counter() - phase_started) * 1000

            phase_started = time.perf_counter()
            claim = build_job_service.get_active_job_claim(
                session,
                request.job_id,
                build_id=request.build_id,
                worker_id=request.worker_id,
                claim_token=request.claim_token,
                lease_generation=request.lease_generation,
            )
            timings['claim_lock_ms'] = (time.perf_counter() - phase_started) * 1000
            if claim is None:
                return worker_runtime_pb2.WorkerPersistBuildEventResponse()

            phase_started = time.perf_counter()
            result = build_run_service.persist_build_event(
                session,
                build_id=request.build_id,
                execution_generation=request.lease_generation,
                event=event,
                resource_config_json=_present_fields(request.build_resource_config, _RESOURCE_CONFIG_FIELDS)
                if request.HasField('build_resource_config')
                else None,
            )
            timings['persist_ms'] = (time.perf_counter() - phase_started) * 1000
        finally:
            phase_started = time.perf_counter()
            try:
                if session_gen is not None:
                    close_rpc_session(session_gen)
            finally:
                reset_namespace(token)
                timings['session_close_ms'] = (time.perf_counter() - phase_started) * 1000
                total_ms = (time.perf_counter() - started) * 1000
                if total_ms >= 1000:
                    logger.warning(
                        'Slow build event RPC build_id=%s job_id=%s worker_id=%s event_type=%s total_ms=%.1f '
                        'validation_ms=%.1f session_open_ms=%.1f claim_lock_ms=%.1f persist_ms=%.1f session_close_ms=%.1f',
                        request.build_id,
                        request.job_id,
                        request.worker_id,
                        event_type,
                        total_ms,
                        timings.get('validation_ms', 0.0),
                        timings.get('session_open_ms', 0.0),
                        timings.get('claim_lock_ms', 0.0),
                        timings.get('persist_ms', 0.0),
                        timings.get('session_close_ms', 0.0),
                    )
        if result is None:
            return worker_runtime_pb2.WorkerPersistBuildEventResponse()
        return worker_runtime_pb2.WorkerPersistBuildEventResponse(sequence=int(result[1]))

    @_general_rpc
    def StartBuildRun(self, request: worker_runtime_pb2.WorkerStartBuildRunRequest, metadata: RpcMetadata) -> worker_runtime_pb2.WorkerStartBuildRunResponse:
        with namespace_scope(request.namespace):
            snapshot = run_db(build_run_service.get_build_run, request.build_id)
            if snapshot is None:
                return worker_runtime_pb2.WorkerStartBuildRunResponse()

            # Build payload conversion can be CPU-heavy for large analyses.
            # Prepare protobufs before opening the claim transaction so JSON
            # parsing never holds a database connection or job-row lock.
            analysis_pipeline = analysis_pipeline_from_payload(dict(snapshot.request_json))
            build_starter = _build_starter_proto(dict(snapshot.starter_json))
            build_resource_config = (
                _build_resource_config_proto(dict(snapshot.resource_config_json)) if isinstance(snapshot.resource_config_json, dict) else None
            )

            def mark_running(session: Session):
                claim = build_job_service.lock_active_job_claim(
                    session,
                    request.job_id,
                    build_id=request.build_id,
                    worker_id=request.worker_id,
                    claim_token=request.claim_token,
                    lease_generation=request.lease_generation,
                )
                if claim is None:
                    return None
                run = build_run_service.mark_build_running(session, request.build_id, execution_generation=request.lease_generation)
                return run if run is not None and run.status == BuildRunStatus.RUNNING else None

            run = run_db(mark_running)
            if run is None:
                return worker_runtime_pb2.WorkerStartBuildRunResponse()
            payload = worker_runtime_pb2.WorkerBuildRunPayload(
                id=run.id,
                namespace=run.namespace,
                analysis_id=run.analysis_id,
                analysis_name=run.analysis_name,
                analysis_pipeline=analysis_pipeline,
                build_starter=build_starter,
                current_datasource_id=run.current_datasource_id,
                current_tab_id=run.current_tab_id,
                current_tab_name=run.current_tab_name,
                current_output_id=run.current_output_id,
                current_output_name=run.current_output_name,
                total_tabs=run.total_tabs,
            )
            tab_id = run.request_json.get('tab_id')
            if isinstance(tab_id, str) and tab_id:
                payload.tab_id = tab_id
            if isinstance(run.current_kind, str):
                payload.current_kind = _proto_enum_value('COMPUTE_WORKER_RUN_KIND', run.current_kind)
            payload.started_at.CopyFrom(datetime_to_timestamp(run.started_at))
            if build_resource_config is not None:
                payload.build_resource_config.CopyFrom(build_resource_config)
            return worker_runtime_pb2.WorkerStartBuildRunResponse(run=payload)

    @_general_rpc
    def PersistComputeWorkerSnapshot(
        self, request: worker_runtime_pb2.WorkerPersistComputeWorkerSnapshotRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.CountResponse:
        conversion_started = time.perf_counter()
        statuses = [_compute_worker_status_info_payload(status) for status in request.engine_status]
        phase_timings: dict[str, float] = {
            'protobuf_to_status_conversion_ms': (time.perf_counter() - conversion_started) * 1000,
        }

        def _write(session: Any) -> None:
            persistence_started = time.perf_counter()
            compute_worker_instance_service.persist_compute_worker_snapshot(
                session,
                worker_id=request.worker_id,
                namespace=request.namespace,
                statuses=statuses,
                phase_timings=phase_timings,
            )
            phase_timings['settings_db_persistence_ms'] = (time.perf_counter() - persistence_started) * 1000

        run_settings_db(_write)
        if any(value > _SLOW_COMPUTE_WORKER_SNAPSHOT_PHASE_SECONDS * 1000 for value in phase_timings.values()):
            logger.warning(
                'Slow PersistComputeWorkerSnapshot phases worker_id=%s namespace=%s status_count=%d '
                'protobuf_to_status_conversion_ms=%.1f settings_db_persistence_ms=%.1f '
                'advisory_lock_wait_ms=%.1f snapshot_write_ms=%.1f active_id_mapping_ms=%.1f '
                'existing_row_query_fetch_ms=%.1f applying_statuses_ms=%.1f stale_row_sweep_ms=%.1f '
                'notification_enqueue_ms=%.1f snapshot_commit_ms=%.1f',
                request.worker_id,
                request.namespace,
                len(statuses),
                phase_timings['protobuf_to_status_conversion_ms'],
                phase_timings['settings_db_persistence_ms'],
                phase_timings.get('advisory_lock_wait_ms', 0.0),
                phase_timings.get('snapshot_write_ms', 0.0),
                phase_timings.get('active_id_mapping_ms', 0.0),
                phase_timings.get('existing_row_query_fetch_ms', 0.0),
                phase_timings.get('applying_statuses_ms', 0.0),
                phase_timings.get('stale_row_sweep_ms', 0.0),
                phase_timings.get('notification_enqueue_ms', 0.0),
                phase_timings.get('snapshot_commit_ms', 0.0),
            )
        return worker_runtime_pb2.CountResponse(count=len(statuses))

    @_general_rpc
    def ListPendingDatasourceDeletes(
        self, request: common_pb2.EmptyRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.WorkerPendingDatasourceDeletesResponse:
        if not request.namespace:
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Datasource delete listing must target a namespace')
        with namespace_scope(request.namespace):
            datasource_ids = run_db(lambda session: [datasource.id for datasource in datasource_delete_service.list_pending_deletes(session)])
        deletes = [
            worker_runtime_pb2.WorkerPendingDatasourceDelete(namespace=request.namespace, datasource_id=datasource_id) for datasource_id in datasource_ids
        ]
        return worker_runtime_pb2.WorkerPendingDatasourceDeletesResponse(deletes=deletes)

    @_general_rpc
    def FinalizeDatasourceDelete(
        self, request: worker_runtime_pb2.WorkerFinalizeDatasourceDeleteRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.WorkerFinalizeDatasourceDeleteResponse:
        with _tenant_session(request.namespace) as session:
            deleted = datasource_delete_service.finalize_delete(session, request.datasource_id)
        return worker_runtime_pb2.WorkerFinalizeDatasourceDeleteResponse(deleted=deleted)

    @_general_rpc
    def GetTelegramSettings(self, request: common_pb2.EmptyRequest, metadata: RpcMetadata) -> worker_runtime_pb2.WorkerTelegramSettingsResponse:
        resolved = get_resolved_telegram_settings()
        return worker_runtime_pb2.WorkerTelegramSettingsResponse(enabled=bool(resolved.get('enabled')))

    @_general_rpc
    def SendEmail(self, request: worker_runtime_pb2.WorkerSendEmailRequest, metadata: RpcMetadata) -> worker_runtime_pb2.BoolResponse:
        if not request.to:
            return worker_runtime_pb2.BoolResponse(value=False)
        payload: dict[str, object] = {
            'kind': EMAIL_DELIVERY_KIND,
            'to': request.to,
            'subject': request.subject,
            'body': request.body,
            'attachments': _notification_attachments(request),
        }
        with namespace_scope(request.namespace):
            run_db(runtime_outbox_service.enqueue_notification_delivery_command, payload)
        return worker_runtime_pb2.BoolResponse(value=True)

    @_general_rpc
    def SendTelegram(self, request: worker_runtime_pb2.WorkerSendTelegramRequest, metadata: RpcMetadata) -> worker_runtime_pb2.BoolResponse:
        payload: dict[str, object] = {
            'kind': TELEGRAM_DELIVERY_KIND,
            'chat_id': request.chat_id,
            'message': request.message,
            'attachments': _notification_attachments(request),
            **_present_fields(request, ('bot_token',)),
        }
        with namespace_scope(request.namespace):
            run_db(runtime_outbox_service.enqueue_notification_delivery_command, payload)
        return worker_runtime_pb2.BoolResponse(value=True)

    @_external_io_rpc
    def GenerateAI(self, request: worker_runtime_pb2.WorkerGenerateAIRequest, metadata: RpcMetadata) -> worker_runtime_pb2.WorkerGenerateAIResponse:
        client = get_ai_client(
            request.provider,
            endpoint_url=_optional(request, 'endpoint_url'),
            api_key=_optional(request, 'api_key'),
        )
        run_settings_db(_assert_runtime_coordinator_generation)
        outputs = client.generate_batch(list(request.prompts), model=request.model, options=struct_to_dict(request.options))
        run_settings_db(_assert_runtime_coordinator_generation)
        return worker_runtime_pb2.WorkerGenerateAIResponse(outputs=outputs)

    @_general_rpc
    def GetTelegramTargets(
        self, request: worker_runtime_pb2.WorkerTelegramTargetsRequest, metadata: RpcMetadata
    ) -> worker_runtime_pb2.WorkerTelegramTargetsResponse:
        datasource_id = _optional(request, 'datasource_id')

        def _list_targets(session: Any) -> list[tuple[str, str]]:
            active_subscribers = select(TelegramSubscriber).where(col(TelegramSubscriber.is_active).is_(True))
            if not request.active_subscribers:
                if not datasource_id:
                    return []
                listeners = session.execute(select(TelegramListener).where(sa(TelegramListener.datasource_id == datasource_id))).scalars().all()
                subscriber_ids = {listener.subscriber_id for listener in listeners}
                if not subscriber_ids:
                    return []
                active_subscribers = active_subscribers.where(col(TelegramSubscriber.id).in_(subscriber_ids))
            rows = session.execute(active_subscribers).scalars().all()
            return [(row.chat_id, row.bot_token) for row in rows if row.bot_token]

        with namespace_scope(request.namespace):
            targets = run_db(_list_targets)
        return worker_runtime_pb2.WorkerTelegramTargetsResponse(
            targets=[worker_runtime_pb2.WorkerTelegramTarget(chat_id=chat_id, bot_token=bot_token) for chat_id, bot_token in targets]
        )


class RuntimeCoordinatorServicer(runtime_coordinator_pb2_grpc.RuntimeCoordinatorServiceServicer):
    def __init__(self, coordinator_guard: Callable[[], None]) -> None:
        self._coordinator_guard = coordinator_guard

    @_lease_rpc
    def GetCoordinatorGeneration(self, request: common_pb2.EmptyRequest, metadata: RpcMetadata) -> runtime_coordinator_pb2.RuntimeCoordinatorGenerationResponse:
        self._check_owner_lease()
        generation = active_runtime_coordinator_generation()
        if generation is None:
            raise _ThreadedRpcAbort(grpc.StatusCode.UNAVAILABLE, 'Runtime coordinator generation is not active')
        return runtime_coordinator_pb2.RuntimeCoordinatorGenerationResponse(generation=generation)

    @_general_rpc
    def AssertCoordinatorGeneration(
        self, request: runtime_coordinator_pb2.RuntimeCoordinatorGenerationRequest, metadata: RpcMetadata
    ) -> runtime_coordinator_pb2.RuntimeCoordinatorGenerationResponse:
        generation = active_runtime_coordinator_generation()
        rejection = _runtime_generation_rejection(generation, metadata.get(_RUNTIME_GENERATION_METADATA_KEY))
        if rejection is not None:
            raise _ThreadedRpcAbort(*rejection)
        if request.generation != generation:
            raise _ThreadedRpcAbort(
                grpc.StatusCode.FAILED_PRECONDITION,
                f'Runtime coordinator generation {request.generation} is fenced by {generation}',
            )
        self._check_owner_lease()
        return runtime_coordinator_pb2.RuntimeCoordinatorGenerationResponse(generation=generation)

    def _check_owner_lease(self) -> None:
        try:
            self._coordinator_guard()
        except Exception as exc:
            raise _ThreadedRpcAbort(grpc.StatusCode.UNAVAILABLE, 'Runtime coordinator lease is not active') from exc


class SchedulerRuntimeServicer(scheduler_runtime_pb2_grpc.SchedulerRuntimeServiceServicer):
    @_general_rpc
    def RegisterScheduler(self, request: scheduler_runtime_pb2.SchedulerRegisterRequest, metadata: RpcMetadata) -> common_pb2.RuntimeWorkerResponse:
        run_settings_db(
            runtime_worker_service.register_worker,
            worker_id=request.worker_id,
            kind=RuntimeWorkerKind.SCHEDULER,
            hostname=request.hostname,
            pid=request.pid,
            capacity=request.capacity,
        )
        return common_pb2.RuntimeWorkerResponse(worker_id=request.worker_id)

    @_scheduler_heartbeat_rpc
    def HeartbeatScheduler(self, request: common_pb2.RuntimeWorkerRequest, metadata: RpcMetadata) -> common_pb2.RuntimeWorkerResponse:
        run_critical_settings_db(runtime_worker_service.heartbeat_worker, worker_id=request.worker_id)
        return common_pb2.RuntimeWorkerResponse(worker_id=request.worker_id)

    @_general_rpc
    def StopScheduler(self, request: common_pb2.RuntimeWorkerRequest, metadata: RpcMetadata) -> common_pb2.RuntimeWorkerResponse:
        run_settings_db(runtime_worker_service.mark_worker_stopped, worker_id=request.worker_id)
        return common_pb2.RuntimeWorkerResponse(worker_id=request.worker_id)

    @_general_rpc
    def ListDueScheduleNamespaces(self, request: common_pb2.EmptyRequest, metadata: RpcMetadata) -> scheduler_runtime_pb2.SchedulerDueNamespacesResponse:
        due = run_settings_db(runtime_work_service.list_due_schedule_namespaces)
        return scheduler_runtime_pb2.SchedulerDueNamespacesResponse(
            namespaces=[
                scheduler_runtime_pb2.SchedulerDueNamespace(namespace=namespace, generation=generation, wake_ids=wake_ids)
                for namespace, generation, wake_ids in due
            ]
        )

    @_general_rpc
    def RunDueSchedules(self, request: scheduler_runtime_pb2.SchedulerRunDueRequest, metadata: RpcMetadata) -> scheduler_runtime_pb2.SchedulerRunDueResponse:
        namespace = request.target_namespace
        if not namespace:
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Scheduler run must target a namespace')
        enqueued: list[scheduler_runtime_pb2.SchedulerEnqueuedRun] = []
        failures: list[scheduler_runtime_pb2.SchedulerRunFailure] = []
        with namespace_scope(namespace):
            run_db(scheduler_service.reconcile_pending_schedule_runs, namespace=namespace)
            claimed = run_db(
                lambda session: [
                    (schedule.id, schedule.datasource_id, schedule.claim_token, schedule.lease_generation)
                    for schedule in scheduler_service.claim_due_schedules(session, worker_id=request.worker_id)
                ]
            )
            for schedule_id, datasource_id, claim_token, lease_generation in claimed:
                if claim_token is None:
                    raise RuntimeError(f'Schedule {schedule_id} claim token missing')
                # One failed enqueue is recorded on its schedule and must not abort the rest of the batch.
                try:
                    build_id = run_db(
                        scheduler_service.enqueue_schedule_run,
                        schedule_id,
                        worker_id=request.worker_id,
                        claim_token=claim_token,
                        lease_generation=lease_generation,
                    )
                except Exception as exc:
                    run_db(scheduler_service.mark_schedule_enqueue_failed, schedule_id, claim_token=claim_token, lease_generation=lease_generation)
                    failures.append(
                        scheduler_runtime_pb2.SchedulerRunFailure(namespace=namespace, schedule_id=schedule_id, datasource_id=datasource_id, error=str(exc))
                    )
                    continue
                enqueued.append(
                    scheduler_runtime_pb2.SchedulerEnqueuedRun(namespace=namespace, schedule_id=schedule_id, datasource_id=datasource_id, build_id=build_id)
                )
            run_db(
                scheduler_service.finish_schedule_work_scan,
                namespace=namespace,
                generation=request.generation,
                wake_ids=request.wake_ids,
            )
        return scheduler_runtime_pb2.SchedulerRunDueResponse(handled=bool(enqueued or failures), enqueued=enqueued, failures=failures)


async def _prewarm_executor(executor: Executor, size: int) -> None:
    if size <= 0:
        return

    # Hold each newly created thread at the barrier until all configured lanes
    # have started. Releasing immediately after submit only primes whichever
    # thread wins the race and leaves the rest to start on live RPC traffic.
    barrier = threading.Barrier(size + 1, timeout=30)
    futures = []
    try:
        for _ in range(size):
            futures.append(executor.submit(barrier.wait))
        await asyncio.to_thread(barrier.wait)
        await asyncio.gather(*(asyncio.wrap_future(future) for future in futures))
    except BaseException:
        barrier.abort()
        await asyncio.gather(*(asyncio.wrap_future(future) for future in futures), return_exceptions=True)
        raise


async def _prewarm_internal_rpc_executors() -> None:
    logger.info(
        'Preparing internal runtime RPC executors total=%s lease=%s general=%s scheduler_heartbeat=%s '
        'lease_validation=%s scheduler_validation=%s general_validation=%s database_budget=%s',
        _INTERNAL_LEASE_RPC_WORKERS + _INTERNAL_GENERAL_RPC_WORKERS + _INTERNAL_SCHEDULER_RPC_WORKERS,
        _INTERNAL_LEASE_RPC_WORKERS,
        _INTERNAL_GENERAL_RPC_WORKERS,
        _INTERNAL_SCHEDULER_RPC_WORKERS,
        _INTERNAL_LEASE_VALIDATION_WORKERS,
        _INTERNAL_SCHEDULER_VALIDATION_WORKERS,
        _INTERNAL_GENERAL_RPC_WORKERS,
        settings.database_pool_size + settings.database_max_overflow,
    )
    executors: list[tuple[Executor | None, int]] = [
        (_INTERNAL_VALIDATION_EXECUTOR, _INTERNAL_GENERAL_RPC_WORKERS),
        (_INTERNAL_LEASE_VALIDATION_EXECUTOR, _INTERNAL_LEASE_VALIDATION_WORKERS),
        (_INTERNAL_SCHEDULER_VALIDATION_EXECUTOR, _INTERNAL_SCHEDULER_VALIDATION_WORKERS),
        (_INTERNAL_EXTERNAL_IO_EXECUTOR, _INTERNAL_EXTERNAL_IO_WORKERS),
        (_INTERNAL_LEASE_RPC_EXECUTOR, _INTERNAL_LEASE_RPC_WORKERS),
        (_INTERNAL_RPC_EXECUTOR, _INTERNAL_GENERAL_RPC_WORKERS),
        (_INTERNAL_SCHEDULER_RPC_EXECUTOR, _INTERNAL_SCHEDULER_RPC_WORKERS),
    ]
    await asyncio.gather(*(_prewarm_executor(executor, size) for executor, size in executors if executor is not None))


async def _start_runtime_grpc_server_on_loop(coordinator_guard: Callable[[], None]) -> grpc.aio.Server:
    await _prewarm_internal_rpc_executors()
    # Keep admission per class in the interceptor. A core-level global RPC
    # ceiling runs before that classification and can let general bursts
    # consume capacity needed by lease and heartbeat calls.
    server = grpc.aio.server(interceptors=(_BackendRequestValidationInterceptor(),))
    worker_runtime_pb2_grpc.add_WorkerRuntimeServiceServicer_to_server(WorkerRuntimeServicer(), server)
    runtime_coordinator_pb2_grpc.add_RuntimeCoordinatorServiceServicer_to_server(RuntimeCoordinatorServicer(coordinator_guard), server)
    scheduler_runtime_pb2_grpc.add_SchedulerRuntimeServiceServicer_to_server(SchedulerRuntimeServicer(), server)
    address = f'{settings.internal_grpc_host}:{settings.internal_grpc_port}'
    bound_port = server.add_insecure_port(address)
    if bound_port != settings.internal_grpc_port:
        await server.stop(grace=0)
        raise RuntimeError(f'Runtime coordinator could not bind internal gRPC address {address!r}')
    await server.start()
    logger.info('Internal runtime gRPC server listening on %s', address)
    return server


class ThreadedRuntimeGrpcServer:
    """Own the runtime coordinator's internal gRPC loop separately from HTTP.

    Runtime RPC handlers already move their blocking database work to fixed
    executors, but grpc.aio still schedules authentication, validation,
    request dispatch, and response callbacks on its event loop. Keeping that
    callback stream off the HTTP loop prevents a burst of lease/claim traffic
    from delaying HTTP routing, WebSocket heartbeats, or health probes.
    """

    def __init__(self, *, loop: asyncio.AbstractEventLoop, server: grpc.aio.Server, thread: threading.Thread) -> None:
        self._loop = loop
        self._server = server
        self._thread = thread

    async def stop(self, *, grace: float = 5.0) -> None:
        if not self._thread.is_alive():
            return
        future = asyncio.run_coroutine_threadsafe(self._server.stop(grace=grace), self._loop)
        await asyncio.to_thread(future.result)
        self._loop.call_soon_threadsafe(self._loop.stop)
        await asyncio.to_thread(self._thread.join)


def start_runtime_grpc_server_in_thread(*, coordinator_guard: Callable[[], None]) -> ThreadedRuntimeGrpcServer:
    ready: threading.Event = threading.Event()
    holder: dict[str, object] = {}

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            server = loop.run_until_complete(_start_runtime_grpc_server_on_loop(coordinator_guard))
        except Exception as exc:
            holder['error'] = exc
            ready.set()
            loop.close()
            return
        holder['loop'] = loop
        holder['server'] = server
        ready.set()
        try:
            loop.run_forever()
        finally:
            loop.close()

    thread = threading.Thread(target=_run, name='runtime-coordinator-grpc', daemon=True)
    thread.start()
    if not ready.wait(timeout=30):
        raise RuntimeError('Timed out starting runtime coordinator gRPC server')
    error = holder.get('error')
    if isinstance(error, Exception):
        raise error
    return ThreadedRuntimeGrpcServer(
        loop=cast(asyncio.AbstractEventLoop, holder['loop']),
        server=cast(grpc.aio.Server, holder['server']),
        thread=thread,
    )


async def start_runtime_grpc_server(*, coordinator_guard: Callable[[], None]) -> ThreadedRuntimeGrpcServer:
    """Start runtime gRPC without sharing Uvicorn's event loop."""
    return await asyncio.to_thread(start_runtime_grpc_server_in_thread, coordinator_guard=coordinator_guard)
