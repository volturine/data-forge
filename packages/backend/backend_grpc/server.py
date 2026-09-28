from __future__ import annotations

import asyncio
import contextlib
import contextvars
import hmac
import logging
import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from concurrent.futures import Executor, ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, cast

import grpc
from google.protobuf import json_format, struct_pb2, timestamp_pb2
from google.protobuf.message import Message
from protovalidate import ValidationError, Validator
from sqlalchemy import select
from sqlmodel import Session

from backend_core import (
    build_commands,
    build_event_service,
    build_jobs_service as build_job_service,
    build_runs_service as build_run_service,
    compute_requests_service,
    datasource_delete_service,
    engine_instances_service as engine_instance_service,
    engine_run_commands,
    engine_runs_service as engine_run_service,
    runtime_ipc,
    runtime_outbox_service,
    runtime_work_service,
    runtime_workers_service as runtime_worker_service,
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
    run_db,
    run_settings_db,
)
from backend_core.domain.build_runs.models import BuildRunStatus
from backend_core.domain.compute import schemas as compute_schemas
from backend_core.domain.compute.base import EngineStatusInfo
from backend_core.domain.compute_requests.models import (
    analysis_pipeline_from_payload,
    datasource_result_from_payload,
    kind_from_proto,
)
from backend_core.domain.runtime_workers.models import RuntimeWorkerKind
from backend_core.exceptions import AppError
from backend_core.json_utils import copy_json_object
from backend_core.namespace import reset_namespace, set_namespace_context
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
_WORKER_RUNTIME_SERVICE_PREFIX = '/dataforge_protocol.WorkerRuntimeService/'
_BUILD_JOB_PROTOCOL_VERSION = 2


def dict_to_struct(payload: dict[str, object] | None) -> struct_pb2.Struct:
    return json_format.ParseDict(payload or {}, struct_pb2.Struct())


def struct_to_dict(payload: struct_pb2.Struct) -> dict[str, object]:
    decoded = json_format.MessageToDict(payload, preserving_proto_field_name=True)
    if not isinstance(decoded, dict):
        raise ValueError('gRPC JSON payload must decode to an object')
    return cast(dict[str, object], decoded)


def struct_field_to_dict(message: Any, field: str) -> dict[str, object] | None:
    if not message.HasField(field):
        return None
    return struct_to_dict(getattr(message, field))


def datetime_to_timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(value if value.tzinfo is not None else value.replace(tzinfo=UTC))
    return timestamp


def timestamp_to_datetime(value: timestamp_pb2.Timestamp) -> datetime:
    return value.ToDatetime(tzinfo=UTC)


def optional_timestamp_to_datetime(message: Any, field: str) -> datetime | None:
    if not message.HasField(field):
        return None
    return timestamp_to_datetime(getattr(message, field))


def enum_to_proto_value(prefix: str, value: str) -> Any:
    return getattr(enums_pb2, f'{prefix}_{value.upper()}')


def proto_value_to_enum_name(enum_type: Any, prefix: str, value: int) -> str:
    enum_name = enum_type.Name(value)
    suffix = enum_name.removeprefix(f'{prefix}_')
    if suffix == 'UNSPECIFIED' or suffix == enum_name:
        raise ValueError(f'Unsupported {prefix} enum value: {enum_name}')
    return suffix.lower()


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

        async def validate_request(request: Message, context: grpc.aio.ServicerContext) -> Any:
            timing = {'request_started': time.monotonic()}
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
                    validation_submitted = time.monotonic()

                    def validate() -> None:
                        timing['validation_started'] = time.monotonic()
                        try:
                            self._validator.validate(request)
                        finally:
                            timing['validation_finished'] = time.monotonic()

                    await loop.run_in_executor(_validation_executor(handler_call_details.method), validate)
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

        return grpc.unary_unary_rpc_method_handler(
            validate_request,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
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


async def _require_internal_token(context: grpc.aio.ServicerContext) -> None:
    if not settings.internal_api_token:
        await context.abort(grpc.StatusCode.UNAVAILABLE, 'INTERNAL_API_TOKEN must be configured before internal runtime services can be used')
    metadata = dict(cast(Any, context.invocation_metadata() or ()))
    if not hmac.compare_digest(metadata.get(_TOKEN_METADATA_KEY) or '', settings.internal_api_token):
        await context.abort(grpc.StatusCode.UNAUTHENTICATED, 'Invalid internal runtime token')


_THREAD_LOCAL = threading.local()
_RPC_TIMING: contextvars.ContextVar[dict[str, float] | None] = contextvars.ContextVar('runtime_rpc_timing', default=None)
_SCHEDULER_HEARTBEAT_METHODS = frozenset({'HeartbeatScheduler'})
_LEASE_VALIDATION_METHODS = frozenset(
    {
        'HeartbeatWorker',
        'RenewBuildJobLease',
        'RenewComputeRequestLeases',
    }
)


def _validation_executor(method: str) -> Executor:
    method_name = method.rsplit('/', 1)[-1]
    if method_name in _SCHEDULER_HEARTBEAT_METHODS and _INTERNAL_SCHEDULER_VALIDATION_EXECUTOR is not None:
        return _INTERNAL_SCHEDULER_VALIDATION_EXECUTOR
    if method_name in _SCHEDULER_HEARTBEAT_METHODS | _LEASE_VALIDATION_METHODS:
        return _INTERNAL_LEASE_VALIDATION_EXECUTOR
    return _INTERNAL_VALIDATION_EXECUTOR


# Keep completion/claim RPC capacity aligned with the compute budget, while
# reserving a smaller independent lane for batched lease renewals and one
# scheduler heartbeat. One pooled connection stays available to outbox recovery.
def _runtime_rpc_executor_sizes(
    database_pool_size: int,
    database_max_overflow: int,
) -> tuple[int, int, int]:
    """Return (lease, general, scheduler-heartbeat) RPC counts for one coordinator."""
    database_capacity = max(database_pool_size + database_max_overflow, 1)
    if database_capacity < 3:
        raise ValueError('Runtime coordinator requires at least three pooled database connections for lease RPCs, general RPCs, and outbox recovery')
    rpc_capacity = database_capacity - 1
    scheduler_heartbeat_workers = min(1, max(rpc_capacity - 2, 0))
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
_INTERNAL_RPC_WORKERS = _INTERNAL_LEASE_RPC_WORKERS + _INTERNAL_GENERAL_RPC_WORKERS + _INTERNAL_SCHEDULER_RPC_WORKERS
_INTERNAL_VALIDATION_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix='internal-rpc-validation')
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
_INTERNAL_EXTERNAL_IO_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix='internal-runtime-external-io')
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
_RUNTIME_WORK_CACHE_TTL_SECONDS = 5.0
_RUNTIME_WORK_CACHE_LOCK = threading.Lock()
_RUNTIME_PENDING_NAMESPACE_CACHE: dict[tuple[str, ...], tuple[float, tuple[str, ...]]] = {}
_RUNTIME_WORK_CACHE_MISS_LOCKS: dict[tuple[str, ...], threading.Lock] = {}


def _cached_pending_runtime_work_namespaces(
    kinds: tuple[runtime_work_service.RuntimeWorkKind, ...] = runtime_work_service.WORKER_RECOVERY_KINDS,
) -> list[str]:
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


def _thread_event_loop() -> asyncio.AbstractEventLoop:
    """One reusable event loop per worker thread instead of a fresh loop per RPC."""
    loop = getattr(_THREAD_LOCAL, 'loop', None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _THREAD_LOCAL.loop = loop
        asyncio.set_event_loop(loop)
    return loop


def close_rpc_session(session_gen) -> None:
    """Exhaust and close a get_db() generator so post-yield cleanup runs."""
    with contextlib.suppress(StopIteration):
        next(session_gen, None)
    session_gen.close()


def _threaded_rpc(executor: Executor):
    def decorator(func):
        async def wrapper(self, request, context):
            await _require_internal_token(context)
            started = time.monotonic()
            rpc_timing = _RPC_TIMING.get()
            timing: dict[str, float] = {}
            database_timing: dict[str, object] = {'sql_count': 0, 'sql_ms': 0.0, 'commit_ms': 0.0}

            def _run():
                timing['worker_started'] = time.monotonic()
                try:
                    loop = _thread_event_loop()
                    timing['handler_started'] = time.monotonic()
                    with database_statement_timing(database_timing):
                        return loop.run_until_complete(func(self, request, context))
                finally:
                    timing['worker_finished'] = time.monotonic()

            try:
                loop = asyncio.get_running_loop()
                contextvars_context = contextvars.copy_context()
                return await loop.run_in_executor(executor, contextvars_context.run, _run)
            except _ThreadedRpcAbort as exc:
                await context.abort(exc.status, exc.details)
            except RuntimeCoordinatorFenced as exc:
                await context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
            finally:
                finished = time.monotonic()
                duration_ms = (finished - started) * 1000
                request_ms = (finished - rpc_timing['request_started']) * 1000 if rpc_timing is not None else duration_ms
                validation_queue_ms = rpc_timing.get('validation_queue_ms', 0.0) if rpc_timing is not None else 0.0
                validation_ms = rpc_timing.get('validation_ms', 0.0) if rpc_timing is not None else 0.0
                if request_ms >= 1000:
                    worker_started = timing.get('worker_started', finished)
                    handler_started = timing.get('handler_started', worker_started)
                    worker_finished = timing.get('worker_finished', finished)
                    request_id = getattr(request, 'request_id', None) or getattr(request, 'idempotency_key', None) or getattr(request, 'job_id', None) or '-'
                    namespace = getattr(request, 'target_namespace', None) or getattr(request, 'namespace', None) or '-'
                    identity = getattr(request, 'engine_identity', None)
                    resource_id = getattr(identity, 'resource_id', None) or getattr(request, 'datasource_id', None) or '-'
                    pool_snapshot: dict[str, object] = {}
                    with contextlib.suppress(Exception):
                        pool_snapshot = database_pool_snapshot()
                    logger.warning(
                        'Slow internal runtime RPC method=%s request_id=%s request_ms=%.1f validation_queue_ms=%.1f '
                        'validation_ms=%.1f executor_queue_ms=%.1f handler_ms=%.1f sql_count=%s sql_ms=%.1f commit_ms=%.1f '
                        'namespace=%s resource_id=%s coordinator_generation=%s db_pool=%s',
                        func.__name__,
                        request_id,
                        request_ms,
                        validation_queue_ms,
                        validation_ms,
                        max(0.0, worker_started - started) * 1000,
                        max(0.0, worker_finished - handler_started) * 1000,
                        database_timing['sql_count'],
                        float(database_timing['sql_ms']),
                        float(database_timing['commit_ms']),
                        namespace,
                        resource_id,
                        active_runtime_coordinator_generation() or '-',
                        pool_snapshot,
                    )

        return wrapper

    return decorator


def _run_async_handler_in_thread(func):
    return _threaded_rpc(_INTERNAL_RPC_EXECUTOR)(func)


def _run_claim_handler_in_thread(func):
    return _threaded_rpc(_INTERNAL_RPC_EXECUTOR)(func)


def _run_critical_runtime_handler_in_thread(func):
    """Keep worker heartbeat and lease-renewal RPCs on their bounded lane."""
    return _threaded_rpc(_INTERNAL_LEASE_RPC_EXECUTOR)(func)


def _run_scheduler_heartbeat_handler_in_thread(func):
    """Protect the singleton scheduler heartbeat from worker lease bursts."""
    executor = _INTERNAL_SCHEDULER_RPC_EXECUTOR or _INTERNAL_LEASE_RPC_EXECUTOR
    return _threaded_rpc(executor)(func)


def _run_control_handler_in_thread(func):
    return _threaded_rpc(_INTERNAL_RPC_EXECUTOR)(func)


def _run_maintenance_handler_in_thread(func):
    """Run maintenance on the bounded general control-plane lane."""
    return _threaded_rpc(_INTERNAL_RPC_EXECUTOR)(func)


def _run_external_io_handler_in_thread(func):
    """Isolate potentially slow provider calls from durable coordinator RPCs."""
    return _threaded_rpc(_INTERNAL_EXTERNAL_IO_EXECUTOR)(func)


class _ThreadedRpcAbort(Exception):
    def __init__(self, status: grpc.StatusCode, details: str) -> None:
        super().__init__(details)
        self.status = status
        self.details = details


def _parse_worker_kind(value: str) -> RuntimeWorkerKind:
    try:
        return RuntimeWorkerKind.require(value)
    except ValueError as exc:
        raise ValueError(f'Unsupported runtime worker kind: {value}') from exc


def _proto_runtime_worker_kind(value: int) -> RuntimeWorkerKind:
    return _parse_worker_kind(proto_value_to_enum_name(enums_pb2.RuntimeWorkerKind, 'RUNTIME_WORKER_KIND', value))


def _proto_compute_request_kind(value: int) -> enums_pb2.ComputeRequestKind:
    return kind_from_proto(value)


def _proto_value(prefix: str, value: object) -> Any:
    return enum_to_proto_value(prefix, str(value))


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return str(value) if value is not None else None


def _read_optional_int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    return int(value) if value is not None and isinstance(value, (str, int)) else None


def _read_optional_dict(payload: dict[str, object], key: str) -> dict[str, object] | None:
    return copy_json_object(payload.get(key))


def _optional_str(message: Any, field: str) -> str | None:
    return getattr(message, field) if message.HasField(field) else None


def _optional_bool(message: Any, field: str) -> bool | None:
    return getattr(message, field) if message.HasField(field) else None


def _optional_int(message: Any, field: str) -> int | None:
    return getattr(message, field) if message.HasField(field) else None


def _build_step_kind_token(message: compute_pb2.BuildStepKind) -> str:
    match message.WhichOneof('kind'):
        case 'pipeline':
            return proto_value_to_enum_name(enums_pb2.StepType, 'STEP_TYPE', message.pipeline)
        case 'execution_category':
            return proto_value_to_enum_name(enums_pb2.EngineRunExecutionCategory, 'ENGINE_RUN_EXECUTION_CATEGORY', message.execution_category)
        case _:
            raise ValueError('build step event is missing step_kind')


def _build_tab_result_payload(message: compute_pb2.BuildTabResult) -> dict[str, object]:
    payload: dict[str, object] = {
        'tab_id': message.tab_id,
        'tab_name': message.tab_name,
        'status': proto_value_to_enum_name(enums_pb2.BuildTabStatus, 'BUILD_TAB_STATUS', message.status),
    }
    for field in ('output_id', 'output_name', 'error'):
        if message.HasField(field):
            payload[field] = getattr(message, field)
    return payload


def _build_terminal_event_payload(message: compute_pb2.BuildTerminalEvent) -> dict[str, object]:
    payload: dict[str, object] = {
        'progress': message.progress,
        'elapsed_ms': message.elapsed_ms,
        'total_steps': message.total_steps,
        'tabs_built': message.tabs_built,
        'results': [_build_tab_result_payload(result) for result in message.results],
        'duration_ms': message.duration_ms,
    }
    if message.HasField('error'):
        payload['error'] = message.error
    if message.HasField('cancelled_at'):
        payload['cancelled_at'] = timestamp_to_datetime(message.cancelled_at)
    if message.HasField('cancelled_by'):
        payload['cancelled_by'] = message.cancelled_by
    return payload


def _build_event_payload(message: compute_pb2.BuildEvent) -> dict[str, object]:
    context = message.context
    payload: dict[str, object] = {
        'build_id': context.build_id,
        'analysis_id': context.analysis_id,
        'emitted_at': timestamp_to_datetime(context.emitted_at),
    }
    if context.HasField('sequence'):
        payload['sequence'] = context.sequence
    if context.HasField('current_kind'):
        payload['current_kind'] = proto_value_to_enum_name(enums_pb2.EngineRunKind, 'ENGINE_RUN_KIND', context.current_kind)
    for field in ('current_datasource_id', 'tab_id', 'tab_name', 'current_output_id', 'current_output_name', 'engine_run_id'):
        if context.HasField(field):
            payload[field] = getattr(context, field)

    match message.WhichOneof('event'):
        case 'plan':
            payload.update({'type': 'plan', 'optimized_plan': message.plan.optimized_plan, 'unoptimized_plan': message.plan.unoptimized_plan})
        case 'step_started':
            payload.update(
                {
                    'type': 'step_start',
                    'build_step_index': message.step_started.build_step_index,
                    'step_index': message.step_started.step_index,
                    'step_id': message.step_started.step_id,
                    'step_name': message.step_started.step_name,
                    'step_type': _build_step_kind_token(message.step_started.step_kind),
                    'total_steps': message.step_started.total_steps,
                }
            )
        case 'step_completed':
            payload.update(
                {
                    'type': 'step_complete',
                    'build_step_index': message.step_completed.build_step_index,
                    'step_index': message.step_completed.step_index,
                    'step_id': message.step_completed.step_id,
                    'step_name': message.step_completed.step_name,
                    'step_type': _build_step_kind_token(message.step_completed.step_kind),
                    'duration_ms': message.step_completed.duration_ms,
                    'total_steps': message.step_completed.total_steps,
                }
            )
            if message.step_completed.HasField('row_count'):
                payload['row_count'] = message.step_completed.row_count
        case 'step_failed':
            payload.update(
                {
                    'type': 'step_failed',
                    'build_step_index': message.step_failed.build_step_index,
                    'step_index': message.step_failed.step_index,
                    'step_id': message.step_failed.step_id,
                    'step_name': message.step_failed.step_name,
                    'step_type': _build_step_kind_token(message.step_failed.step_kind),
                    'error': message.step_failed.error,
                    'total_steps': message.step_failed.total_steps,
                }
            )
        case 'progress':
            payload.update(
                {
                    'type': 'progress',
                    'progress': message.progress.progress,
                    'elapsed_ms': message.progress.elapsed_ms,
                    'total_steps': message.progress.total_steps,
                }
            )
            if message.progress.HasField('estimated_remaining_ms'):
                payload['estimated_remaining_ms'] = message.progress.estimated_remaining_ms
            if message.progress.HasField('current_step'):
                payload['current_step'] = message.progress.current_step
            if message.progress.HasField('current_step_index'):
                payload['current_step_index'] = message.progress.current_step_index
        case 'resources':
            payload.update(
                {
                    'type': 'resources',
                    'cpu_percent': message.resources.cpu_percent,
                    'memory_mb': message.resources.memory_mb,
                    'active_threads': message.resources.active_threads,
                }
            )
            if message.resources.HasField('memory_limit_mb'):
                payload['memory_limit_mb'] = message.resources.memory_limit_mb
            if message.resources.HasField('max_threads'):
                payload['max_threads'] = message.resources.max_threads
        case 'log':
            payload.update(
                {
                    'type': 'log',
                    'level': proto_value_to_enum_name(enums_pb2.BuildLogLevel, 'BUILD_LOG_LEVEL', message.log.level),
                    'message': message.log.message,
                }
            )
            for field in ('step_name', 'step_id'):
                if message.log.HasField(field):
                    payload[field] = getattr(message.log, field)
        case 'completed':
            payload.update({'type': 'complete', **_build_terminal_event_payload(message.completed)})
        case 'failed':
            payload.update({'type': 'failed', **_build_terminal_event_payload(message.failed)})
        case 'cancelled':
            payload.update({'type': 'cancelled', **_build_terminal_event_payload(message.cancelled)})
        case _:
            raise ValueError('build event is missing typed event payload')
    return payload


def _build_resource_config_payload(message: compute_pb2.BuildResourceConfigSummary) -> dict[str, object]:
    payload: dict[str, object] = {}
    for field in ('max_threads', 'max_memory_mb', 'streaming_chunk_size'):
        if message.HasField(field):
            payload[field] = getattr(message, field)
    return payload


def _engine_run_execution_entry_payload(entry: compute_pb2.EngineRunExecutionEntry) -> dict[str, object]:
    payload: dict[str, object] = {
        'key': entry.key,
        'label': entry.label,
        'category': proto_value_to_enum_name(enums_pb2.EngineRunExecutionCategory, 'ENGINE_RUN_EXECUTION_CATEGORY', entry.category),
        'order': entry.order,
    }
    if entry.HasField('duration_ms'):
        payload['duration_ms'] = entry.duration_ms
    if entry.HasField('share_pct'):
        payload['share_pct'] = entry.share_pct
    if entry.HasField('optimized_plan'):
        payload['optimized_plan'] = entry.optimized_plan
    if entry.HasField('unoptimized_plan'):
        payload['unoptimized_plan'] = entry.unoptimized_plan
    if entry.HasField('step_type'):
        payload['metadata'] = {'step_type': proto_value_to_enum_name(enums_pb2.StepType, 'STEP_TYPE', entry.step_type)}
    return payload


def _engine_resource_config_payload(message: compute_pb2.EngineResourceConfig) -> dict[str, object]:
    payload: dict[str, object] = {}
    if message.HasField('max_threads'):
        payload['max_threads'] = message.max_threads
    if message.HasField('max_memory_mb'):
        payload['max_memory_mb'] = message.max_memory_mb
    if message.HasField('streaming_chunk_size'):
        payload['streaming_chunk_size'] = message.streaming_chunk_size
    return payload


def _engine_defaults_payload(message: compute_pb2.EngineDefaults) -> dict[str, object]:
    return {
        'max_threads': message.max_threads,
        'max_memory_mb': message.max_memory_mb,
        'streaming_chunk_size': message.streaming_chunk_size,
    }


def _engine_status_info_payload(message: compute_pb2.EngineStatusResult) -> EngineStatusInfo:
    return EngineStatusInfo(
        analysis_id=message.analysis_id,
        resource_id=message.resource_id,
        status=proto_value_to_enum_name(enums_pb2.EngineStatus, 'ENGINE_STATUS', message.status),
        container_id=message.container_id if message.HasField('container_id') else None,
        image_digest=message.image_digest if message.HasField('image_digest') else None,
        lifecycle_status=proto_value_to_enum_name(enums_pb2.EngineInstanceStatus, 'ENGINE_INSTANCE_STATUS', message.lifecycle_status)
        if message.HasField('lifecycle_status')
        else None,
        termination_reason=message.termination_reason if message.HasField('termination_reason') else None,
        exit_code=message.exit_code if message.HasField('exit_code') else None,
        oom_killed=message.oom_killed if message.HasField('oom_killed') else None,
        supervisor_id=message.supervisor_id if message.HasField('supervisor_id') else None,
        owner_id=message.owner_id if message.HasField('owner_id') else None,
        last_activity=message.last_activity if message.HasField('last_activity') else None,
        current_job_id=message.current_job_id if message.HasField('current_job_id') else None,
        resource_config=_engine_resource_config_payload(message.resource_config) if message.HasField('resource_config') else None,
        effective_resources=_engine_resource_config_payload(message.effective_resources) if message.HasField('effective_resources') else None,
        defaults=_engine_defaults_payload(message.defaults) if message.HasField('defaults') else {},
        scope=proto_value_to_enum_name(enums_pb2.EngineScope, 'ENGINE_SCOPE', message.scope) if message.HasField('scope') else None,
        reuse_policy=proto_value_to_enum_name(enums_pb2.EngineReusePolicy, 'ENGINE_REUSE_POLICY', message.reuse_policy)
        if message.HasField('reuse_policy')
        else None,
        datasource_id=message.datasource_id if message.HasField('datasource_id') else None,
        build_id=message.build_id if message.HasField('build_id') else None,
        current_build_id=message.current_build_id if message.HasField('current_build_id') else None,
        current_engine_run_id=message.current_engine_run_id if message.HasField('current_engine_run_id') else None,
    )


def _engine_run_update_kwargs(update: worker_runtime_pb2.WorkerEngineRunUpdateFields, *, merge_result: bool) -> dict[str, Any]:
    kwargs: dict[str, Any] = {'merge_result_json': merge_result}
    if update.HasField('analysis_id'):
        kwargs['analysis_id'] = update.analysis_id
    if update.HasField('datasource_id'):
        kwargs['datasource_id'] = update.datasource_id
    if update.HasField('kind'):
        kwargs['kind'] = proto_value_to_enum_name(enums_pb2.EngineRunKind, 'ENGINE_RUN_KIND', update.kind)
    if update.HasField('status'):
        kwargs['status'] = proto_value_to_enum_name(enums_pb2.EngineRunStatus, 'ENGINE_RUN_STATUS', update.status)
    if update.HasField('request_json'):
        kwargs['request_json'] = struct_to_dict(update.request_json)
    if update.HasField('result_json'):
        kwargs['result_json'] = struct_to_dict(update.result_json)
    if update.HasField('error_message'):
        kwargs['error_message'] = update.error_message
    if update.HasField('completed_at'):
        kwargs['completed_at'] = timestamp_to_datetime(update.completed_at)
    if update.HasField('duration_ms'):
        kwargs['duration_ms'] = update.duration_ms
    if update.HasField('step_timings'):
        kwargs['step_timings'] = dict(update.step_timings.values)
    if update.HasField('query_plan'):
        kwargs['query_plan'] = update.query_plan
    if update.HasField('execution_entries'):
        kwargs['execution_entries'] = [_engine_run_execution_entry_payload(entry) for entry in update.execution_entries.entries]
    if update.HasField('progress'):
        kwargs['progress'] = update.progress
    if update.clear_current_step:
        kwargs['current_step'] = None
    if update.HasField('current_step'):
        kwargs['current_step'] = update.current_step
    if update.HasField('triggered_by'):
        kwargs['triggered_by'] = update.triggered_by
    return kwargs


def _compute_request_engine_run_finalization(
    finalization: worker_runtime_pb2.WorkerEngineRunFinalization | None,
) -> compute_requests_service.EngineRunFinalization | None:
    if finalization is None:
        return None
    if not finalization.HasField('update'):
        raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Engine-run finalization update is required')
    fields = _engine_run_update_kwargs(finalization.update, merge_result=finalization.merge_result)
    merge_result_json = bool(fields.pop('merge_result_json'))
    return compute_requests_service.EngineRunFinalization(
        run_id=finalization.run_id,
        fields=fields,
        merge_result_json=merge_result_json,
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
    for field in ('max_threads', 'max_memory_mb', 'streaming_chunk_size'):
        value = payload.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            setattr(message, field, value)
    return message


def _response(worker_id: str) -> common_pb2.RuntimeWorkerResponse:
    return common_pb2.RuntimeWorkerResponse(worker_id=worker_id)


def _count(value: int) -> worker_runtime_pb2.CountResponse:
    return worker_runtime_pb2.CountResponse(count=value)


def _bool(value: bool) -> worker_runtime_pb2.BoolResponse:
    return worker_runtime_pb2.BoolResponse(value=value)


def _id(value: str) -> worker_runtime_pb2.IdResponse:
    return worker_runtime_pb2.IdResponse(id=value)


class WorkerRuntimeServicer(worker_runtime_pb2_grpc.WorkerRuntimeServiceServicer):
    @_run_control_handler_in_thread
    async def RegisterWorker(
        self, request: worker_runtime_pb2.RuntimeWorkerRegisterRequest, context: grpc.aio.ServicerContext
    ) -> common_pb2.RuntimeWorkerResponse:

        def _register(session: Any) -> None:
            runtime_worker_service.register_worker(
                session,
                worker_id=request.worker_id,
                kind=_proto_runtime_worker_kind(request.kind),
                hostname=request.hostname,
                pid=request.pid,
                capacity=request.capacity,
                active_jobs=request.active_jobs,
            )

        run_settings_db(_register)
        return _response(request.worker_id)

    @_run_critical_runtime_handler_in_thread
    async def HeartbeatWorker(
        self, request: worker_runtime_pb2.RuntimeWorkerHeartbeatRequest, context: grpc.aio.ServicerContext
    ) -> common_pb2.RuntimeWorkerResponse:
        active_jobs = _optional_int(request, 'active_jobs')

        def _heartbeat(session: Any) -> None:
            runtime_worker_service.heartbeat_worker(session, worker_id=request.worker_id, active_jobs=active_jobs)

        run_settings_db(_heartbeat)
        return _response(request.worker_id)

    @_run_control_handler_in_thread
    async def StopWorker(self, request: common_pb2.RuntimeWorkerRequest, context: grpc.aio.ServicerContext) -> common_pb2.RuntimeWorkerResponse:
        await _require_internal_token(context)

        def _stop(session: Any) -> None:
            runtime_worker_service.mark_worker_stopped(session, worker_id=request.worker_id)

        run_settings_db(_stop)
        return _response(request.worker_id)

    @_run_claim_handler_in_thread
    async def ClaimBuildJob(
        self, request: common_pb2.RuntimeWorkerRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerClaimBuildJobResponse:
        if request.protocol_version != _BUILD_JOB_PROTOCOL_VERSION:
            raise _ThreadedRpcAbort(grpc.StatusCode.FAILED_PRECONDITION, 'Build worker protocol version is incompatible')
        if not request.target_namespace:
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Build worker claim must target a namespace')
        token = set_namespace_context(request.target_namespace)
        try:
            # Reconciliation is performed by the bounded recovery/count path.
            # A claim must only inspect the directed namespace's next job; the
            # old full exhausted-job scan here ran once per worker poll and
            # multiplied database work during a browser burst. A stopped or
            # disconnected owner is recovered by its durable lease expiry; a
            # cooperative child releases its own claim before stopping.
            job = run_db(build_job_service.claim_next_job, worker_id=request.worker_id)
        finally:
            reset_namespace(token)
        if job is not None:
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
        return worker_runtime_pb2.WorkerClaimBuildJobResponse()

    @_run_critical_runtime_handler_in_thread
    async def RenewBuildJobLease(
        self, request: worker_runtime_pb2.WorkerBuildJobClaimRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerRenewBuildJobLeaseResponse:
        token = set_namespace_context(request.namespace)
        try:
            renewal = run_db(
                build_job_service.renew_job_lease,
                request.job_id,
                worker_id=request.worker_id,
                claim_token=request.claim_token,
                lease_generation=request.lease_generation,
            )
        finally:
            reset_namespace(token)
        response = worker_runtime_pb2.WorkerRenewBuildJobLeaseResponse(
            renewed=renewal.applied,
            lease_ttl_seconds=settings.runtime_work_lease_ttl_seconds if renewal.applied else None,
        )
        if renewal.value is not None and renewal.value.lease_expires_at is not None:
            response.lease_expires_at.CopyFrom(datetime_to_timestamp(renewal.value.lease_expires_at))
        return response

    @_run_claim_handler_in_thread
    async def ClaimComputeRequest(
        self, request: common_pb2.RuntimeWorkerRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerClaimComputeRequestResponse:
        if request.protocol_version != _BUILD_JOB_PROTOCOL_VERSION:
            raise _ThreadedRpcAbort(grpc.StatusCode.FAILED_PRECONDITION, 'Compute worker protocol version is incompatible')
        if not request.target_namespace:
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Compute request claim must target a namespace')
        token = set_namespace_context(request.target_namespace)
        try:
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
        finally:
            reset_namespace(token)

    @_run_critical_runtime_handler_in_thread
    async def RenewComputeRequestLeases(
        self, request: worker_runtime_pb2.WorkerRenewComputeRequestLeasesRequest, context: grpc.aio.ServicerContext
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
        token = set_namespace_context(request.namespace)
        try:
            renewed_ids = run_db(
                compute_requests_service.renew_request_leases,
                claims,
                worker_id=request.worker_id,
            )
        finally:
            reset_namespace(token)
        response = worker_runtime_pb2.WorkerRenewComputeRequestLeasesResponse()
        for claim in claims:
            renewed = claim.request_id in renewed_ids
            result = response.renewals.add(request_id=claim.request_id, renewed=renewed)
            if renewed:
                result.lease_ttl_seconds = settings.runtime_work_lease_ttl_seconds
        return response

    @_run_control_handler_in_thread
    async def CompleteComputeRequest(
        self, request: worker_runtime_pb2.WorkerCompleteComputeRequestRequest, context: grpc.aio.ServicerContext
    ) -> common_pb2.RuntimeWorkerResponse:
        token = set_namespace_context(request.namespace)
        try:
            completed = run_db(
                compute_requests_service.mark_request_completed,
                request.request_id,
                response_envelope=request.response_envelope,
                worker_id=request.worker_id,
                claim_token=request.claim_token,
                lease_generation=request.lease_generation,
                artifact_path=_optional_str(request, 'artifact_path'),
                artifact_name=_optional_str(request, 'artifact_name'),
                artifact_content_type=_optional_str(request, 'artifact_content_type'),
                engine_run_finalization=_compute_request_engine_run_finalization(
                    request.engine_run_finalization if request.HasField('engine_run_finalization') else None
                ),
            )
            if completed is None:
                raise _ThreadedRpcAbort(grpc.StatusCode.FAILED_PRECONDITION, 'Compute request lease is no longer active')
            return _response(request.request_id)
        finally:
            reset_namespace(token)

    @_run_control_handler_in_thread
    async def FailComputeRequest(
        self, request: worker_runtime_pb2.WorkerFailComputeRequestRequest, context: grpc.aio.ServicerContext
    ) -> common_pb2.RuntimeWorkerResponse:
        token = set_namespace_context(request.namespace)
        try:
            failed = run_db(
                compute_requests_service.mark_request_failed,
                request.request_id,
                error_message=request.error_message,
                response_envelope=request.response_envelope,
                worker_id=request.worker_id,
                claim_token=request.claim_token,
                lease_generation=request.lease_generation,
                engine_run_finalization=_compute_request_engine_run_finalization(
                    request.engine_run_finalization if request.HasField('engine_run_finalization') else None
                ),
            )
            if failed is None:
                raise _ThreadedRpcAbort(grpc.StatusCode.FAILED_PRECONDITION, 'Compute request lease is no longer active')
            return _response(request.request_id)
        finally:
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def PublishDatasourceCreate(
        self, request: worker_runtime_pb2.WorkerPublishDatasourceCreateRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerPublishDatasourceCreateResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            schema_info = None
            if request.HasField('schema_info') and len(request.schema_info.columns) > 0:
                schema_info = request.schema_info
            response = datasource_publication_service.create_datasource(
                session,
                datasource_id=request.datasource_id,
                name=request.name,
                description=request.description if request.HasField('description') else None,
                source_type=proto_value_to_enum_name(enums_pb2.DataSourceType, 'DATA_SOURCE_TYPE', request.source_type),
                config=struct_to_dict(request.config),
                owner_id=request.owner_id if request.HasField('owner_id') else None,
                schema_info=schema_info,
            )
            record = datasource_result_from_payload(
                enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
                response.model_dump(mode='json'),
            )
            if record.WhichOneof('result') != 'datasource':
                raise ValueError('create publication must return a datasource result')
            return worker_runtime_pb2.WorkerPublishDatasourceCreateResponse(datasource=record.datasource)
        finally:
            close_rpc_session(session_gen)
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def PublishDatasourceIngest(
        self, request: worker_runtime_pb2.WorkerPublishDatasourceIngestRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerPublishDatasourceIngestResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            has_compute = request.HasField('compute_request_id')
            has_build = request.HasField('job_id') or request.HasField('build_id')
            if has_compute == has_build:
                raise _ThreadedRpcAbort(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    'Ingest publication requires exactly one of compute_request_id or build job claim fields',
                )
            if has_build and not (request.HasField('job_id') and request.HasField('build_id')):
                raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Build job claim fields must be provided together')

            def _guard_publication(active_session: Any) -> None:
                if has_compute:
                    request_claim = compute_requests_service.lock_active_request_claim(
                        active_session,
                        request.compute_request_id,
                        worker_id=request.worker_id,
                        claim_token=request.claim_token,
                        lease_generation=request.lease_generation,
                    )
                    if request_claim is None:
                        raise datasource_publication_service.DatasourcePublicationClaimLost
                    return
                job_claim = build_job_service.lock_active_job_claim(
                    active_session,
                    request.job_id,
                    build_id=request.build_id,
                    worker_id=request.worker_id,
                    claim_token=request.claim_token,
                    lease_generation=request.lease_generation,
                )
                if job_claim is None:
                    raise datasource_publication_service.DatasourcePublicationClaimLost

            schema_info = None
            if request.HasField('schema_info') and len(request.schema_info.columns) > 0:
                schema_info = request.schema_info
            try:
                response = datasource_publication_service.publish_ingest(
                    session,
                    datasource_id=request.datasource_id,
                    config=struct_to_dict(request.config),
                    expected_revision=int(request.expected_revision),
                    schema_info=schema_info,
                    publication_guard=_guard_publication,
                )
            except datasource_publication_service.DatasourcePublicationClaimLost as exc:
                raise _ThreadedRpcAbort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    str(exc) or 'Datasource publication claim is no longer active',
                ) from exc
            record = datasource_result_from_payload(
                enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE,
                response.model_dump(mode='json'),
            )
            if record.WhichOneof('result') != 'datasource':
                raise ValueError('ingest publication must return a datasource result')
            return worker_runtime_pb2.WorkerPublishDatasourceIngestResponse(datasource=record.datasource)
        finally:
            close_rpc_session(session_gen)
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def PublishDatasourceSchemaCache(
        self, request: worker_runtime_pb2.WorkerPublishDatasourceSchemaCacheRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerPublishDatasourceSchemaCacheResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            published = datasource_publication_service.publish_schema_cache(
                session,
                datasource_id=request.datasource_id,
                schema_info=request.schema_info,
            )
            return worker_runtime_pb2.WorkerPublishDatasourceSchemaCacheResponse(schema_info=published)
        except AppError as exc:
            if exc.error_code != 'DATASOURCE_NOT_FOUND':
                raise
            raise _ThreadedRpcAbort(grpc.StatusCode.NOT_FOUND, str(exc)) from exc
        finally:
            close_rpc_session(session_gen)
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def GetDatasourceMetadata(
        self, request: worker_runtime_pb2.WorkerDatasourceMetadataRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerDatasourceMetadataResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            datasource = session.get(DataSource, request.datasource_id)
            if datasource is None:
                return worker_runtime_pb2.WorkerDatasourceMetadataResponse(found=False)
            response = worker_runtime_pb2.WorkerDatasourceMetadataResponse(
                found=True,
                id=datasource.id,
                name=datasource.name,
                source_type=_proto_value('DATA_SOURCE_TYPE', datasource.source_type),
                config=dict_to_struct(dict(datasource.config)),
                is_hidden=datasource.is_hidden,
                revision=int(datasource.revision),
                created_by=str(datasource.created_by),
            )
            if datasource.description is not None:
                response.description = datasource.description
            if isinstance(datasource.schema_cache, dict):
                response.schema_info.CopyFrom(schema_info_proto(dict(datasource.schema_cache)))
            descriptions = datasource_publication_service.column_description_map(session, datasource.id)
            if descriptions:
                response.column_descriptions.update(descriptions)
            return response
        finally:
            close_rpc_session(session_gen)
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def GetUdfCodes(
        self, request: worker_runtime_pb2.WorkerUdfCodesRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerUdfCodesResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            ids = [udf_id for udf_id in request.udf_ids if udf_id]
            if not ids:
                return worker_runtime_pb2.WorkerUdfCodesResponse()
            stmt = select(Udf).where(col(Udf.id).in_(ids))
            codes = {udf.id: udf.code for udf in session.execute(stmt).scalars().all()}
            return worker_runtime_pb2.WorkerUdfCodesResponse(codes=codes)
        finally:
            close_rpc_session(session_gen)
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def GetEngineCredentials(
        self, request: worker_runtime_pb2.WorkerEngineCredentialsRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerEngineCredentialsResponse:
        from backend_core.namespace_credentials_service import NamespaceCredentialError, resolve_namespace_engine_credentials

        try:
            access_key, secret_key = run_settings_db(
                resolve_namespace_engine_credentials,
                request.namespace,
                request.role,
            )
        except NamespaceCredentialError as exc:
            raise _ThreadedRpcAbort(grpc.StatusCode.NOT_FOUND, str(exc)) from exc
        return worker_runtime_pb2.WorkerEngineCredentialsResponse(access_key=access_key, secret_key=secret_key)

    @_run_async_handler_in_thread
    async def GetAnalysisMetadata(
        self, request: worker_runtime_pb2.WorkerAnalysisMetadataRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerAnalysisMetadataResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            analysis = session.get(Analysis, request.analysis_id)
            if analysis is None:
                return worker_runtime_pb2.WorkerAnalysisMetadataResponse(found=False)
            return worker_runtime_pb2.WorkerAnalysisMetadataResponse(found=True, name=analysis.name)
        finally:
            close_rpc_session(session_gen)
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def GetBuildCancelStatus(
        self, request: worker_runtime_pb2.WorkerBuildCancelStatusRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerBuildCancelStatusResponse:
        token = set_namespace_context(request.namespace)
        try:
            run = run_db(build_run_service.get_build_run, request.build_id)
            if run is None or run.status != BuildRunStatus.CANCELLED:
                return worker_runtime_pb2.WorkerBuildCancelStatusResponse(cancelled=False)
            cancelled_by = run.cancelled_by if isinstance(run.cancelled_by, str) else None
            response = worker_runtime_pb2.WorkerBuildCancelStatusResponse(cancelled=True, cancelled_by=cancelled_by)
            if isinstance(run.cancelled_at, datetime):
                response.cancelled_at.CopyFrom(datetime_to_timestamp(run.cancelled_at))
            return response
        finally:
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def UpdateBuildResult(
        self, request: worker_runtime_pb2.WorkerUpdateBuildResultRequest, context: grpc.aio.ServicerContext
    ) -> common_pb2.RuntimeWorkerResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
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
            return _response(request.build_id)
        finally:
            close_rpc_session(session_gen)
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def UpsertOutputDatasource(
        self, request: worker_runtime_pb2.WorkerUpsertOutputDatasourceRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerUpsertOutputDatasourceResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            claimed_publication = request.HasField('build_id')
            claim_fields = ('job_id', 'build_id', 'worker_id', 'claim_token', 'lease_generation')
            if any(request.HasField(field) for field in claim_fields) != all(request.HasField(field) for field in claim_fields):
                raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Output publication claim fields must be provided together')
            if claimed_publication:
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
            else:
                publication_claim = None
            notification_deliveries: list[dict[str, object]] = []
            for delivery in request.notification_delivery:
                delivery_kind = delivery.WhichOneof('delivery')
                if delivery_kind == 'email':
                    payload: dict[str, object] = {
                        'kind': EMAIL_DELIVERY_KIND,
                        'to': delivery.email.to,
                        'subject': delivery.email.subject,
                        'body': delivery.email.body,
                        'attachments': [],
                    }
                elif delivery_kind == 'telegram':
                    payload = {
                        'kind': TELEGRAM_DELIVERY_KIND,
                        'chat_id': delivery.telegram.chat_id,
                        'message': delivery.telegram.message,
                        'attachments': [],
                    }
                    if delivery.telegram.HasField('bot_token'):
                        payload['bot_token'] = delivery.telegram.bot_token
                else:
                    raise _ThreadedRpcAbort(
                        grpc.StatusCode.INVALID_ARGUMENT,
                        'Notification delivery command is missing its delivery payload',
                    )
                notification_deliveries.append(payload)
            try:
                datasource = datasource_commands.upsert_output_datasource(
                    session,
                    result_id=request.result_id,
                    name=request.name,
                    source_type=proto_value_to_enum_name(enums_pb2.DataSourceType, 'DATA_SOURCE_TYPE', request.source_type),
                    config=struct_to_dict(request.config),
                    schema_cache=schema_info_payload(request.schema_info),
                    keep_schema_cache=request.keep_schema_cache,
                    analysis_id=_optional_str(request, 'analysis_id'),
                    is_hidden=request.is_hidden if request.HasField('is_hidden') else None,
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
        finally:
            close_rpc_session(session_gen)
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def ListHealthChecks(
        self, request: worker_runtime_pb2.WorkerListHealthChecksRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerListHealthChecksResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            stmt = select(HealthCheck).where(sa(HealthCheck.datasource_id == request.datasource_id))
            checks = [check for check in session.execute(stmt).scalars().all() if check.enabled]
            return worker_runtime_pb2.WorkerListHealthChecksResponse(
                checks=[
                    worker_runtime_pb2.WorkerHealthCheckSpec(
                        id=check.id,
                        name=check.name,
                        check_type=_proto_value('HEALTH_CHECK_TYPE', check.check_type),
                        config=dict_to_struct(dict(check.config)),
                        critical=check.critical,
                    )
                    for check in checks
                ]
            )
        finally:
            close_rpc_session(session_gen)
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def RecordHealthCheckResults(
        self, request: worker_runtime_pb2.WorkerRecordHealthCheckResultsRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.CountResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            count = healthcheck_commands.record_results(
                session,
                (
                    HealthCheckResult(
                        id=str(uuid.uuid4()),
                        healthcheck_id=result.healthcheck_id,
                        passed=result.passed,
                        message=result.message,
                        details=struct_to_dict(result.details),
                        checked_at=timestamp_to_datetime(result.checked_at),
                    )
                    for result in request.results
                ),
            )
            return _count(count)
        finally:
            close_rpc_session(session_gen)
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def CreateEngineRun(
        self, request: worker_runtime_pb2.WorkerCreateEngineRunRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.IdResponse:
        token = set_namespace_context(request.namespace)
        try:
            run = run_db(
                engine_run_commands.create_engine_run,
                engine_run_service.create_engine_run_payload(
                    analysis_id=_optional_str(request, 'analysis_id'),
                    datasource_id=request.datasource_id,
                    kind=proto_value_to_enum_name(enums_pb2.EngineRunKind, 'ENGINE_RUN_KIND', request.kind),
                    status=proto_value_to_enum_name(enums_pb2.EngineRunStatus, 'ENGINE_RUN_STATUS', request.status),
                    request_json=struct_to_dict(request.request),
                    result_json=struct_field_to_dict(request, 'result'),
                    error_message=_optional_str(request, 'error_message'),
                    created_at=optional_timestamp_to_datetime(request, 'created_at'),
                    completed_at=optional_timestamp_to_datetime(request, 'completed_at'),
                    duration_ms=_optional_int(request, 'duration_ms'),
                    step_timings=dict(request.timing_by_key) if request.timing_by_key else None,
                    query_plan=_optional_str(request, 'query_plan'),
                    execution_entries=[_engine_run_execution_entry_payload(entry) for entry in request.execution_entry] or None,
                    progress=request.progress,
                    current_step=_optional_str(request, 'current_step'),
                    triggered_by=_optional_str(request, 'triggered_by'),
                    idempotency_key=_optional_str(request, 'idempotency_key'),
                ),
            )
            return _id(run.id)
        finally:
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def UpdateEngineRun(
        self, request: worker_runtime_pb2.WorkerUpdateEngineRunRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.IdResponse:
        kwargs = _engine_run_update_kwargs(request.update, merge_result=request.merge_result)
        token = set_namespace_context(request.namespace)
        try:
            run = run_db(lambda session: engine_run_commands.update_engine_run(session, request.run_id, **kwargs))
            return _id(run.id)
        finally:
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def GetEngineRunState(
        self, request: worker_runtime_pb2.WorkerEngineRunStateRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerEngineRunStateResponse:
        token = set_namespace_context(request.namespace)
        try:
            run = run_db(engine_run_service.get_engine_run, request.run_id)
            if run is None:
                return worker_runtime_pb2.WorkerEngineRunStateResponse(found=False)
            result_json = dict(run.result_json) if isinstance(run.result_json, dict) else {}
            cancelled_at = result_json.get('cancelled_at')
            cancelled_by = result_json.get('cancelled_by')
            response = worker_runtime_pb2.WorkerEngineRunStateResponse(
                found=True,
                status=_proto_value('ENGINE_RUN_STATUS', run.status),
                result=dict_to_struct(result_json),
                cancelled_by=cancelled_by if isinstance(cancelled_by, str) else None,
            )
            if isinstance(cancelled_at, str):
                response.cancelled_at.CopyFrom(datetime_to_timestamp(datetime.fromisoformat(cancelled_at)))
            return response
        finally:
            reset_namespace(token)

    @_run_control_handler_in_thread
    async def FailBuildJob(self, request: worker_runtime_pb2.WorkerFailBuildJobRequest, context: grpc.aio.ServicerContext) -> worker_runtime_pb2.BoolResponse:
        token = set_namespace_context(request.namespace)
        try:
            result = run_db(
                build_commands.fail_build_job,
                build_commands.BuildClaimCommand(
                    job_id=request.job_id,
                    build_id=request.build_id,
                    worker_id=request.worker_id,
                    claim_token=request.claim_token,
                    lease_generation=request.lease_generation,
                ),
                error=request.error,
            )
        finally:
            reset_namespace(token)
        return _bool(result is not None)

    @_run_control_handler_in_thread
    async def FinalizeBuildJob(
        self, request: worker_runtime_pb2.WorkerFinalizeBuildJobRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.BoolResponse:

        token = set_namespace_context(request.namespace)
        try:
            result = run_db(
                build_commands.finalize_build_job,
                build_commands.BuildClaimCommand(
                    job_id=request.job_id,
                    build_id=request.build_id,
                    worker_id=request.worker_id,
                    claim_token=request.claim_token,
                    lease_generation=request.lease_generation,
                ),
            )
        finally:
            reset_namespace(token)
        return _bool(result is not None)

    @_run_control_handler_in_thread
    async def ReleaseBuildWorkerJobs(self, request: common_pb2.RuntimeWorkerRequest, context: grpc.aio.ServicerContext) -> worker_runtime_pb2.CountResponse:
        if not request.target_namespace:
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Build worker release must target a namespace')
        token = set_namespace_context(request.target_namespace)
        try:
            released = len(run_db(build_job_service.release_worker_jobs, worker_id=request.worker_id))
        finally:
            reset_namespace(token)
        return _count(released)

    @_run_maintenance_handler_in_thread
    async def GetQueuedBuildJobCount(self, request: common_pb2.EmptyRequest, context: grpc.aio.ServicerContext) -> worker_runtime_pb2.CountResponse:
        if not request.namespace:
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Queued build count must target a namespace')
        token = set_namespace_context(request.namespace)
        try:
            count = run_db(build_job_service.queued_job_count)
        finally:
            reset_namespace(token)
        return _count(count)

    @_run_maintenance_handler_in_thread
    async def ReconcileExpiredBuildJobs(self, request: common_pb2.EmptyRequest, context: grpc.aio.ServicerContext) -> worker_runtime_pb2.CountResponse:
        if not request.namespace:
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Build job reconciliation must target a namespace')
        token = set_namespace_context(request.namespace)
        try:
            reconciled = run_db(scheduler_commands.reconcile_expired_build_jobs)
        finally:
            reset_namespace(token)
        return _count(reconciled)

    @_run_maintenance_handler_in_thread
    async def ReconcileExpiredComputeRequests(self, request: common_pb2.EmptyRequest, context: grpc.aio.ServicerContext) -> worker_runtime_pb2.CountResponse:
        if not request.namespace:
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Compute request reconciliation must target a namespace')
        token = set_namespace_context(request.namespace)
        try:
            reconciled = run_db(compute_requests_service.reconcile_expired_requests)
        finally:
            reset_namespace(token)
        return _count(reconciled)

    @_run_maintenance_handler_in_thread
    async def GetIdleBuildWorkerPids(self, request: common_pb2.EmptyRequest, context: grpc.aio.ServicerContext) -> worker_runtime_pb2.WorkerIdlePidsResponse:
        workers = run_settings_db(runtime_worker_service.list_workers, kind=RuntimeWorkerKind.BUILD_WORKER)
        return worker_runtime_pb2.WorkerIdlePidsResponse(pids=[worker.pid for worker in workers if worker.stopped_at is None and worker.active_jobs == 0])

    @_run_maintenance_handler_in_thread
    async def ListPendingRuntimeWorkNamespaces(
        self, request: worker_runtime_pb2.WorkerPendingRuntimeWorkNamespacesRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerNamespacesResponse:
        try:
            kinds = tuple(sorted({runtime_work_service.RuntimeWorkKind(kind) for kind in request.kinds})) or runtime_work_service.WORKER_RECOVERY_KINDS
        except ValueError as exc:
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, f'Unknown runtime work kind: {exc}') from exc
        return worker_runtime_pb2.WorkerNamespacesResponse(namespaces=_cached_pending_runtime_work_namespaces(kinds))

    @_run_async_handler_in_thread
    async def PersistBuildEvent(
        self, request: worker_runtime_pb2.WorkerPersistBuildEventRequest, context: grpc.aio.ServicerContext
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
            result = build_event_service.persist_build_event(
                session,
                build_id=request.build_id,
                execution_generation=request.lease_generation,
                event=event,
                resource_config_json=_build_resource_config_payload(request.build_resource_config) if request.HasField('build_resource_config') else None,
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

    @_run_async_handler_in_thread
    async def StartBuildRun(
        self, request: worker_runtime_pb2.WorkerStartBuildRunRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerStartBuildRunResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            claim = build_job_service.lock_active_job_claim(
                session,
                request.job_id,
                build_id=request.build_id,
                worker_id=request.worker_id,
                claim_token=request.claim_token,
                lease_generation=request.lease_generation,
            )
            if claim is None:
                return worker_runtime_pb2.WorkerStartBuildRunResponse()
            run = build_run_service.mark_build_running(session, request.build_id, execution_generation=request.lease_generation)
            if run is None or run.status != BuildRunStatus.RUNNING:
                return worker_runtime_pb2.WorkerStartBuildRunResponse()
            payload = worker_runtime_pb2.WorkerBuildRunPayload(
                id=run.id,
                namespace=run.namespace,
                analysis_id=run.analysis_id,
                analysis_name=run.analysis_name,
                analysis_pipeline=analysis_pipeline_from_payload(dict(run.request_json)),
                build_starter=_build_starter_proto(dict(run.starter_json)),
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
                payload.current_kind = _proto_value('ENGINE_RUN_KIND', run.current_kind)
            payload.started_at.CopyFrom(datetime_to_timestamp(run.started_at))
            if isinstance(run.resource_config_json, dict):
                payload.build_resource_config.CopyFrom(_build_resource_config_proto(dict(run.resource_config_json)))
            return worker_runtime_pb2.WorkerStartBuildRunResponse(run=payload)
        finally:
            close_rpc_session(session_gen)
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def PersistEngineSnapshot(
        self, request: worker_runtime_pb2.WorkerPersistEngineSnapshotRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.CountResponse:
        statuses = [_engine_status_info_payload(status) for status in request.engine_status]

        def _write(session: Any) -> None:
            engine_instance_service.persist_engine_snapshot(
                session,
                worker_id=request.worker_id,
                namespace=request.namespace,
                statuses=statuses,
            )

        run_settings_db(_write)
        runtime_ipc.notify_api_engine(request.namespace)
        return _count(len(statuses))

    @_run_maintenance_handler_in_thread
    async def ListPendingDatasourceDeletes(
        self, request: common_pb2.EmptyRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerPendingDatasourceDeletesResponse:
        if not request.namespace:
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Datasource delete listing must target a namespace')
        token = set_namespace_context(request.namespace)
        try:
            datasource_ids = run_db(lambda session: [datasource.id for datasource in datasource_delete_service.list_pending_deletes(session)])
        finally:
            reset_namespace(token)
        deletes = [
            worker_runtime_pb2.WorkerPendingDatasourceDelete(namespace=request.namespace, datasource_id=datasource_id) for datasource_id in datasource_ids
        ]
        return worker_runtime_pb2.WorkerPendingDatasourceDeletesResponse(deletes=deletes)

    @_run_maintenance_handler_in_thread
    async def FinalizeDatasourceDelete(
        self, request: worker_runtime_pb2.WorkerFinalizeDatasourceDeleteRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerFinalizeDatasourceDeleteResponse:
        token = set_namespace_context(request.namespace)
        session_gen = get_db()
        session = next(session_gen)
        try:
            deleted = datasource_delete_service.finalize_delete(session, request.datasource_id)
            return worker_runtime_pb2.WorkerFinalizeDatasourceDeleteResponse(deleted=deleted)
        finally:
            close_rpc_session(session_gen)
            reset_namespace(token)

    @_run_async_handler_in_thread
    async def GetTelegramSettings(
        self, request: common_pb2.EmptyRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerTelegramSettingsResponse:
        resolved = get_resolved_telegram_settings()
        return worker_runtime_pb2.WorkerTelegramSettingsResponse(enabled=bool(resolved.get('enabled')))

    @_run_async_handler_in_thread
    async def SendEmail(self, request: worker_runtime_pb2.WorkerSendEmailRequest, context: grpc.aio.ServicerContext) -> worker_runtime_pb2.BoolResponse:
        if not request.to:
            return _bool(False)
        token = set_namespace_context(request.namespace)
        try:
            run_db(
                runtime_outbox_service.enqueue_notification_delivery_command,
                {
                    'kind': EMAIL_DELIVERY_KIND,
                    'to': request.to,
                    'subject': request.subject,
                    'body': request.body,
                    'attachments': [
                        {'filename': item.filename, 'content_base64': item.content_base64, 'content_type': item.content_type} for item in request.attachments
                    ],
                },
            )
        finally:
            reset_namespace(token)
        return _bool(True)

    @_run_async_handler_in_thread
    async def SendTelegram(self, request: worker_runtime_pb2.WorkerSendTelegramRequest, context: grpc.aio.ServicerContext) -> worker_runtime_pb2.BoolResponse:
        token = set_namespace_context(request.namespace)
        try:
            payload: dict[str, object] = {
                'kind': TELEGRAM_DELIVERY_KIND,
                'chat_id': request.chat_id,
                'message': request.message,
                'attachments': [
                    {'filename': item.filename, 'content_base64': item.content_base64, 'content_type': item.content_type} for item in request.attachments
                ],
            }
            if request.HasField('bot_token'):
                payload['bot_token'] = request.bot_token

            run_db(
                runtime_outbox_service.enqueue_notification_delivery_command,
                payload,
            )
        finally:
            reset_namespace(token)
        return _bool(True)

    @_run_external_io_handler_in_thread
    async def GenerateAI(
        self, request: worker_runtime_pb2.WorkerGenerateAIRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerGenerateAIResponse:
        client = get_ai_client(
            request.provider,
            endpoint_url=_optional_str(request, 'endpoint_url'),
            api_key=_optional_str(request, 'api_key'),
        )
        outputs = client.generate_batch(list(request.prompts), model=request.model, options=struct_to_dict(request.options))
        return worker_runtime_pb2.WorkerGenerateAIResponse(outputs=outputs)

    @_run_async_handler_in_thread
    async def GetTelegramTargets(
        self, request: worker_runtime_pb2.WorkerTelegramTargetsRequest, context: grpc.aio.ServicerContext
    ) -> worker_runtime_pb2.WorkerTelegramTargetsResponse:
        datasource_id = _optional_str(request, 'datasource_id')

        def _list_targets(session: Any) -> list[tuple[str, str]]:
            if request.active_subscribers:
                rows = session.execute(select(TelegramSubscriber).where(col(TelegramSubscriber.is_active).is_(True))).scalars().all()
                return [(row.chat_id, row.bot_token) for row in rows if row.bot_token]
            if not datasource_id:
                return []
            listeners = (
                session.execute(
                    select(TelegramListener).where(sa(TelegramListener.datasource_id == datasource_id)),
                )
                .scalars()
                .all()
            )
            subscriber_ids = {listener.subscriber_id for listener in listeners}
            if not subscriber_ids:
                return []
            rows = (
                session.execute(
                    select(TelegramSubscriber).where(col(TelegramSubscriber.id).in_(subscriber_ids)).where(col(TelegramSubscriber.is_active).is_(True)),
                )
                .scalars()
                .all()
            )
            return [(row.chat_id, row.bot_token) for row in rows if row.bot_token]

        token = set_namespace_context(request.namespace)
        try:
            targets = run_db(_list_targets)
        finally:
            reset_namespace(token)
        return worker_runtime_pb2.WorkerTelegramTargetsResponse(
            targets=[worker_runtime_pb2.WorkerTelegramTarget(chat_id=chat_id, bot_token=bot_token) for chat_id, bot_token in targets]
        )


class SchedulerRuntimeServicer(scheduler_runtime_pb2_grpc.SchedulerRuntimeServiceServicer):
    @_run_control_handler_in_thread
    async def RegisterScheduler(
        self, request: scheduler_runtime_pb2.SchedulerRegisterRequest, context: grpc.aio.ServicerContext
    ) -> common_pb2.RuntimeWorkerResponse:

        def _register(session: Any) -> None:
            runtime_worker_service.register_worker(
                session,
                worker_id=request.worker_id,
                kind=RuntimeWorkerKind.SCHEDULER,
                hostname=request.hostname,
                pid=request.pid,
                capacity=request.capacity,
            )

        run_settings_db(_register)
        return _response(request.worker_id)

    @_run_scheduler_heartbeat_handler_in_thread
    async def HeartbeatScheduler(self, request: common_pb2.RuntimeWorkerRequest, context: grpc.aio.ServicerContext) -> common_pb2.RuntimeWorkerResponse:

        def _heartbeat(session: Any) -> None:
            runtime_worker_service.heartbeat_worker(session, worker_id=request.worker_id)

        run_settings_db(_heartbeat)
        return _response(request.worker_id)

    @_run_control_handler_in_thread
    async def StopScheduler(self, request: common_pb2.RuntimeWorkerRequest, context: grpc.aio.ServicerContext) -> common_pb2.RuntimeWorkerResponse:

        def _stop(session: Any) -> None:
            runtime_worker_service.mark_worker_stopped(session, worker_id=request.worker_id)

        run_settings_db(_stop)
        return _response(request.worker_id)

    @_run_maintenance_handler_in_thread
    async def ListDueScheduleNamespaces(
        self, request: common_pb2.EmptyRequest, context: grpc.aio.ServicerContext
    ) -> scheduler_runtime_pb2.SchedulerDueNamespacesResponse:
        due = run_settings_db(runtime_work_service.list_due_schedule_namespaces)
        return scheduler_runtime_pb2.SchedulerDueNamespacesResponse(
            namespaces=[scheduler_runtime_pb2.SchedulerDueNamespace(namespace=namespace, generation=generation) for namespace, generation in due]
        )

    @_run_maintenance_handler_in_thread
    async def RunDueSchedules(
        self, request: scheduler_runtime_pb2.SchedulerRunDueRequest, context: grpc.aio.ServicerContext
    ) -> scheduler_runtime_pb2.SchedulerRunDueResponse:
        if not request.target_namespace:
            raise _ThreadedRpcAbort(grpc.StatusCode.INVALID_ARGUMENT, 'Scheduler run must target a namespace')
        enqueued: list[scheduler_runtime_pb2.SchedulerEnqueuedRun] = []
        failures: list[scheduler_runtime_pb2.SchedulerRunFailure] = []
        namespace = request.target_namespace
        token = set_namespace_context(namespace)
        try:
            claimed = run_db(
                lambda session: [
                    (schedule.id, schedule.datasource_id, schedule.claim_token, schedule.lease_generation)
                    for schedule in scheduler_service.claim_due_schedules(
                        session,
                        worker_id=request.worker_id,
                    )
                ]
            )
            for schedule_id, datasource_id, claim_token, lease_generation in claimed:
                if claim_token is None:
                    raise RuntimeError(f'Schedule {schedule_id} claim token missing')
                try:

                    def _enqueue(
                        session: Any,
                        target_id: str = schedule_id,
                        target_token: str = claim_token,
                        target_generation: int = lease_generation,
                    ) -> str:
                        return scheduler_service.enqueue_schedule_run(
                            session,
                            target_id,
                            worker_id=request.worker_id,
                            claim_token=target_token,
                            lease_generation=target_generation,
                        )

                    build_id = run_db(_enqueue)
                    enqueued.append(
                        scheduler_runtime_pb2.SchedulerEnqueuedRun(
                            namespace=namespace,
                            schedule_id=schedule_id,
                            datasource_id=datasource_id,
                            build_id=build_id,
                        )
                    )
                except Exception as exc:

                    def _mark_failed(
                        session: Any,
                        target_id: str = schedule_id,
                        error: str = str(exc),
                        target_token: str = claim_token,
                        target_generation: int = lease_generation,
                    ) -> None:
                        scheduler_service.mark_schedule_enqueue_failed(
                            session,
                            target_id,
                            error=error,
                            claim_token=target_token,
                            lease_generation=target_generation,
                        )

                    run_db(_mark_failed)
                    failures.append(
                        scheduler_runtime_pb2.SchedulerRunFailure(
                            namespace=namespace,
                            schedule_id=schedule_id,
                            datasource_id=datasource_id,
                            error=str(exc),
                        )
                    )
            run_db(
                lambda session: scheduler_service.finish_schedule_work_scan(
                    session,
                    namespace=namespace,
                    generation=request.generation,
                )
            )
        finally:
            reset_namespace(token)
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
        'lease_validation=%s scheduler_validation=%s general_validation=2 database_budget=%s',
        _INTERNAL_RPC_WORKERS,
        _INTERNAL_LEASE_RPC_WORKERS,
        _INTERNAL_GENERAL_RPC_WORKERS,
        _INTERNAL_SCHEDULER_RPC_WORKERS,
        _INTERNAL_LEASE_VALIDATION_WORKERS,
        _INTERNAL_SCHEDULER_VALIDATION_WORKERS,
        settings.database_pool_size + settings.database_max_overflow,
    )
    executors: dict[Executor, int] = {}
    for executor, size in (
        (_INTERNAL_VALIDATION_EXECUTOR, 2),
        (_INTERNAL_LEASE_VALIDATION_EXECUTOR, _INTERNAL_LEASE_VALIDATION_WORKERS),
        (_INTERNAL_EXTERNAL_IO_EXECUTOR, 2),
        (_INTERNAL_LEASE_RPC_EXECUTOR, _INTERNAL_LEASE_RPC_WORKERS),
        (_INTERNAL_RPC_EXECUTOR, _INTERNAL_GENERAL_RPC_WORKERS),
    ):
        executors[executor] = max(executors.get(executor, 0), size)
    if _INTERNAL_SCHEDULER_VALIDATION_EXECUTOR is not None:
        executors[_INTERNAL_SCHEDULER_VALIDATION_EXECUTOR] = _INTERNAL_SCHEDULER_VALIDATION_WORKERS
    if _INTERNAL_SCHEDULER_RPC_EXECUTOR is not None:
        executors[_INTERNAL_SCHEDULER_RPC_EXECUTOR] = _INTERNAL_SCHEDULER_RPC_WORKERS

    async def prewarm(executor: Executor, size: int) -> None:
        await _prewarm_executor(executor, size)

    await asyncio.gather(*(prewarm(executor, size) for executor, size in executors.items()))


async def _start_runtime_grpc_server_on_loop() -> grpc.aio.Server:
    await _prewarm_internal_rpc_executors()
    server = grpc.aio.server(interceptors=(_BackendRequestValidationInterceptor(),))
    worker_runtime_pb2_grpc.add_WorkerRuntimeServiceServicer_to_server(WorkerRuntimeServicer(), server)
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


def start_runtime_grpc_server_in_thread() -> ThreadedRuntimeGrpcServer:
    ready: threading.Event = threading.Event()
    holder: dict[str, object] = {}

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            server = loop.run_until_complete(_start_runtime_grpc_server_on_loop())
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


async def start_runtime_grpc_server() -> ThreadedRuntimeGrpcServer:
    """Start runtime gRPC without sharing Uvicorn's event loop."""
    return await asyncio.to_thread(start_runtime_grpc_server_in_thread)
