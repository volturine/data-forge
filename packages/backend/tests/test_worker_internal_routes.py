from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import MappingProxyType, SimpleNamespace
from typing import Any, cast

import pytest
from google.protobuf import json_format, struct_pb2, timestamp_pb2
from sqlmodel import Session, select

import backend_grpc.server as backend_grpc_server
from backend_core import build_jobs_service, build_runs_service, compute_requests_service, engine_instances_service, engine_runs_service
from backend_core.claiming import CLAIM_DELIVERY_LEASE_SECONDS
from backend_core.config import settings
from backend_core.database import RuntimeCoordinatorFenced, database_pool_snapshot, run_settings_db
from backend_core.domain.build_jobs.models import BuildJobStatus
from backend_core.domain.build_runs.models import BuildRunStatus
from backend_core.domain.compute import schemas as compute_schemas
from backend_core.domain.compute_requests.models import command_from_payload, response_envelope
from backend_core.domain.datasource.source_types import DataSourceType
from backend_core.domain.engine_instances.models import EngineInstanceStatus
from backend_core.domain.engine_runs.schemas import EngineRunKind, EngineRunStatus
from backend_core.namespace import get_namespace
from backend_core.namespace_credentials_service import NamespaceCredentialError
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.runtime_events.models import RuntimeOutboxEvent
from backend_core.persistence.runtime_workers.models import RuntimeWorker
from backend_core.persistence.scheduler.models import Schedule
from backend_core.persistence.telegram.models import TelegramListener, TelegramSubscriber
from backend_core.persistence.udfs.models import Udf
from backend_grpc.server import WorkerRuntimeServicer
from dataforge_protocol import common_pb2, compute_pb2, datasource_pb2, enums_pb2, runtime_coordinator_pb2, worker_runtime_pb2
from modules.scheduler.service import reconcile_schedule_run


def dict_to_struct(payload: dict[str, object]) -> struct_pb2.Struct:
    return json_format.ParseDict(cast(Any, payload), struct_pb2.Struct())


@pytest.mark.parametrize(
    ('active_generation', 'supplied_generation', 'status'),
    [
        (None, '1', backend_grpc_server.grpc.StatusCode.UNAVAILABLE),
        (1, None, backend_grpc_server.grpc.StatusCode.UNAUTHENTICATED),
        (1, 'not-a-generation', backend_grpc_server.grpc.StatusCode.INVALID_ARGUMENT),
        (1, '0', backend_grpc_server.grpc.StatusCode.INVALID_ARGUMENT),
        (2, '1', backend_grpc_server.grpc.StatusCode.FAILED_PRECONDITION),
    ],
)
def test_worker_runtime_rpc_requires_the_active_coordinator_generation(
    active_generation: int | None,
    supplied_generation: object,
    status,
) -> None:
    rejection = backend_grpc_server._runtime_generation_rejection(active_generation, supplied_generation)

    assert rejection is not None
    assert rejection[0] == status


def test_worker_runtime_rpc_accepts_only_the_active_coordinator_generation() -> None:
    assert backend_grpc_server._runtime_generation_rejection(7, '7') is None


@pytest.mark.parametrize('fenced_check', [1, 2, None])
@pytest.mark.asyncio
async def test_generate_ai_fences_provider_call_and_result_against_owner_generation(
    fenced_check: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ImmediateExecutor:
        def submit(self, function, /, *args, **kwargs):
            future = Future()
            try:
                future.set_result(function(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)
            return future

    class Context:
        def __init__(self, token: str) -> None:
            self._metadata = (
                ('x-internal-token', token),
                ('x-runtime-coordinator-generation', '7'),
            )
            self.abort_status = None

        def invocation_metadata(self):
            return self._metadata

        async def abort(self, status, details: str) -> None:
            self.abort_status = status
            raise RuntimeError(details)

    monkeypatch.setattr(settings, 'internal_api_token', 'generate-ai-test-token')
    monkeypatch.setattr(backend_grpc_server, '_INTERNAL_EXTERNAL_IO_EXECUTOR', ImmediateExecutor())
    monkeypatch.setattr(backend_grpc_server, 'active_runtime_coordinator_generation', lambda: 7)

    fence_calls = 0
    provider_calls = 0

    def check_generation(function, *args, **kwargs):
        nonlocal fence_calls
        fence_calls += 1
        if fence_calls == fenced_check:
            raise RuntimeCoordinatorFenced('Runtime coordinator generation 7 is fenced by generation 8')
        session = SimpleNamespace(execute=lambda _statement: None)
        return function(session, *args, **kwargs)

    def generate_batch(prompts, *, model: str, options: dict[str, object]) -> list[str]:
        nonlocal provider_calls
        assert prompts == ['prompt']
        assert model == 'test-model'
        assert options == {}
        assert fence_calls == 1
        provider_calls += 1
        return ['generated']

    monkeypatch.setattr(backend_grpc_server, 'run_settings_db', check_generation)
    monkeypatch.setattr(backend_grpc_server, 'get_ai_client', lambda *_args, **_kwargs: SimpleNamespace(generate_batch=generate_batch))

    context = Context(settings.internal_api_token)
    request = worker_runtime_pb2.WorkerGenerateAIRequest(
        provider=enums_pb2.AI_PROVIDER_OPENROUTER,
        prompts=['prompt'],
        model='test-model',
    )

    if fenced_check is None:
        response = await WorkerRuntimeServicer().GenerateAI(request, context)
        assert list(response.outputs) == ['generated']
        assert fence_calls == 2
        assert provider_calls == 1
    else:
        with pytest.raises(RuntimeError, match='generation 7 is fenced'):
            await WorkerRuntimeServicer().GenerateAI(request, context)
        assert context.abort_status == backend_grpc_server.grpc.StatusCode.FAILED_PRECONDITION
        assert fence_calls == fenced_check
        assert provider_calls == int(fenced_check == 2)


def datetime_to_timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(value)
    return timestamp


def compute_claim_request(
    worker_id: str,
    *allowed_kinds: enums_pb2.ComputeRequestKind,
) -> common_pb2.RuntimeWorkerRequest:
    return common_pb2.RuntimeWorkerRequest(
        worker_id=worker_id,
        protocol_version=2,
        allowed_compute_request_kinds=allowed_kinds,
        target_namespace='default',
    )


def test_runtime_rpc_executor_sizes_stay_within_database_budget() -> None:
    assert backend_grpc_server._runtime_rpc_executor_sizes(32, 13) == (8, 32, 1)
    assert backend_grpc_server._runtime_rpc_executor_sizes(16, 13) == (4, 16, 1)
    assert backend_grpc_server._runtime_rpc_executor_sizes(8, 13) == (4, 8, 1)
    assert backend_grpc_server._runtime_rpc_executor_sizes(1, 4) == (1, 2, 1)
    assert backend_grpc_server._runtime_rpc_executor_sizes(100, 13) == (25, 32, 1)
    with pytest.raises(ValueError, match='at least four pooled database connections'):
        backend_grpc_server._runtime_rpc_executor_sizes(1, 0)

    for pool_size, overflow in ((100, 13), (32, 13), (16, 13), (8, 13), (1, 4)):
        sizes = backend_grpc_server._runtime_rpc_executor_sizes(pool_size, overflow)
        database_capacity = pool_size + overflow
        assert sum(sizes) <= max(database_capacity - 1, 1)
        assert sizes[1] >= 1
        assert sizes[0] <= pool_size
        assert sizes[2] <= 1

    assert backend_grpc_server._INTERNAL_GENERAL_VALIDATION_WORKERS == backend_grpc_server._INTERNAL_GENERAL_RPC_WORKERS


@pytest.mark.asyncio
async def test_prewarm_executor_starts_every_configured_thread() -> None:
    with ThreadPoolExecutor(max_workers=3) as executor:
        await backend_grpc_server._prewarm_executor(executor, 3)
        assert len(cast(Any, executor)._threads) == 3


class FakeGrpcContext:
    def __init__(self, token: str) -> None:
        self._metadata = (('x-internal-token', token),)
        self.abort_loop: asyncio.AbstractEventLoop | None = None

    def invocation_metadata(self) -> tuple[tuple[str, str], ...]:
        return self._metadata

    async def abort(self, _code, details: str) -> None:
        self.abort_loop = asyncio.get_running_loop()
        raise RuntimeError(details)


@pytest.mark.asyncio
async def test_get_engine_credentials_aborts_on_grpc_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend_core.namespace_credentials_service as namespace_credentials_service

    async def allow_internal_call(_context) -> None:
        return None

    def missing_credentials(_session, namespace: str, role: str) -> tuple[str, str]:
        assert namespace == 'tenant-a'
        assert role == 'reader'
        raise NamespaceCredentialError('credentials are missing')

    def settings_db(function, *args, **kwargs):
        return function(object(), *args, **kwargs)

    monkeypatch.setattr(backend_grpc_server, '_require_internal_token', allow_internal_call)
    monkeypatch.setattr(backend_grpc_server, 'run_settings_db', settings_db)
    monkeypatch.setattr(namespace_credentials_service, 'resolve_namespace_engine_credentials', missing_credentials)
    context = FakeGrpcContext(settings.internal_api_token)

    with pytest.raises(RuntimeError, match='credentials are missing'):
        await WorkerRuntimeServicer().GetEngineCredentials(
            worker_runtime_pb2.WorkerEngineCredentialsRequest(namespace='tenant-a', role='reader'),
            context,
        )

    assert context.abort_loop is asyncio.get_running_loop()


@pytest.mark.asyncio
async def test_lease_validation_isolated_from_general_rpc_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    general_executor = ThreadPoolExecutor(max_workers=1)
    lease_executor = ThreadPoolExecutor(max_workers=1)
    scheduler_executor = ThreadPoolExecutor(max_workers=1)
    general_release = threading.Event()
    general_started = threading.Event()
    validation_ran = threading.Event()

    def block_general_validation() -> None:
        general_started.set()
        general_release.wait(timeout=2)

    general_blocker = general_executor.submit(block_general_validation)
    assert general_started.wait(timeout=1)
    monkeypatch.setattr(backend_grpc_server, '_INTERNAL_VALIDATION_EXECUTOR', general_executor)
    monkeypatch.setattr(backend_grpc_server, '_INTERNAL_LEASE_VALIDATION_EXECUTOR', lease_executor)
    monkeypatch.setattr(backend_grpc_server, '_INTERNAL_SCHEDULER_VALIDATION_EXECUTOR', scheduler_executor)
    monkeypatch.setattr(backend_grpc_server, 'active_runtime_coordinator_generation', lambda: 7)

    interceptor = backend_grpc_server._BackendRequestValidationInterceptor()
    interceptor._validator = cast(Any, SimpleNamespace(validate=lambda _request: validation_ran.set()))
    method = f'{backend_grpc_server._WORKER_RUNTIME_SERVICE_PREFIX}RenewComputeRequestLeases'
    scheduler_heartbeat = '/dataforge_protocol.SchedulerRuntimeService/HeartbeatScheduler'
    assert backend_grpc_server._validation_executor(scheduler_heartbeat) is scheduler_executor
    assert backend_grpc_server._validation_executor(f'{backend_grpc_server._WORKER_RUNTIME_SERVICE_PREFIX}HeartbeatWorker') is lease_executor
    assert backend_grpc_server._validation_executor(method) is lease_executor
    generation_assertion = f'{backend_grpc_server._WORKER_RUNTIME_SERVICE_PREFIX}AssertCoordinatorGeneration'
    assert backend_grpc_server._validation_executor(generation_assertion) is general_executor
    assert backend_grpc_server._rpc_admission_lane(generation_assertion) is backend_grpc_server._RPC_ADMISSION_LANES['general']
    assert backend_grpc_server._rpc_admission_lane(method) is backend_grpc_server._RPC_ADMISSION_LANES['critical']
    assert backend_grpc_server._validation_executor(generation_assertion.rsplit('/', 1)[0] + '/GetCoordinatorGeneration') is lease_executor

    async def echo(request, _context):
        return request

    async def continuation(_details):
        return backend_grpc_server.grpc.unary_unary_rpc_method_handler(echo)

    class Context:
        def invocation_metadata(self):
            return ((backend_grpc_server._RUNTIME_GENERATION_METADATA_KEY, '7'),)

        async def abort(self, _status, details):
            raise AssertionError(f'lease validation unexpectedly aborted: {details}')

    request = worker_runtime_pb2.WorkerRenewComputeRequestLeasesRequest(
        namespace='tenant-a',
        worker_id='worker-1',
        renewals=[
            worker_runtime_pb2.WorkerComputeRequestLeaseRenewal(
                request_id='request-1',
                claim_token='claim-1',
                lease_generation=1,
            )
        ],
    )
    try:
        wrapped = await interceptor.intercept_service(continuation, SimpleNamespace(method=method))
        assert wrapped is not None and wrapped.unary_unary is not None
        response = await cast(Any, wrapped.unary_unary)(request, Context())
        assert response is request
        assert validation_ran.is_set()
        assert not general_release.is_set()
    finally:
        general_release.set()
        general_blocker.result(timeout=1)
        general_executor.shutdown(wait=True)
        lease_executor.shutdown(wait=True)
        scheduler_executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_generation_assertion_burst_cannot_starve_worker_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    generation = 7
    guard_started = threading.Event()
    release_guard = threading.Event()
    guard_calls = 0

    def coordinator_guard() -> None:
        nonlocal guard_calls
        guard_calls += 1
        guard_started.set()
        assert release_guard.wait(timeout=5)

    async def allow_internal_call(_context):
        return backend_grpc_server.RpcMetadata(MappingProxyType(dict(_context.invocation_metadata())))

    monkeypatch.setattr(backend_grpc_server, 'active_runtime_coordinator_generation', lambda: generation)
    monkeypatch.setattr(backend_grpc_server, '_require_internal_token', allow_internal_call)
    monkeypatch.setattr(backend_grpc_server, 'run_critical_settings_db', lambda function: function(object()))
    heartbeat_calls: list[tuple[str, int | None]] = []
    monkeypatch.setattr(
        backend_grpc_server.runtime_worker_service,
        'heartbeat_worker',
        lambda _session, *, worker_id, active_jobs: heartbeat_calls.append((worker_id, active_jobs)),
    )

    general_lane = backend_grpc_server._RpcAdmissionLane('general-generation-test', 1, queue_limit=8)
    critical_lane = backend_grpc_server._RpcAdmissionLane('critical-heartbeat-test', 1)
    monkeypatch.setattr(
        backend_grpc_server,
        '_RPC_ADMISSION_LANES',
        {
            'general': general_lane,
            'critical': critical_lane,
            'scheduler': backend_grpc_server._RpcAdmissionLane('scheduler-test', 1),
            'external-io': backend_grpc_server._RpcAdmissionLane('external-test', 1),
        },
    )

    interceptor = backend_grpc_server._BackendRequestValidationInterceptor()
    interceptor._validator = cast(Any, SimpleNamespace(validate=lambda _request: None))
    coordinator_servicer = backend_grpc_server.RuntimeCoordinatorServicer(coordinator_guard)
    worker_servicer = WorkerRuntimeServicer()
    coordinator_method = f'/{runtime_coordinator_pb2.DESCRIPTOR.services_by_name["RuntimeCoordinatorService"].full_name}/AssertCoordinatorGeneration'
    heartbeat_method = f'{backend_grpc_server._WORKER_RUNTIME_SERVICE_PREFIX}HeartbeatWorker'

    async def coordinator_continuation(_details):
        return backend_grpc_server.grpc.unary_unary_rpc_method_handler(coordinator_servicer.AssertCoordinatorGeneration)

    async def heartbeat_continuation(_details):
        return backend_grpc_server.grpc.unary_unary_rpc_method_handler(worker_servicer.HeartbeatWorker)

    class Context:
        def invocation_metadata(self):
            return (
                (backend_grpc_server._RUNTIME_GENERATION_METADATA_KEY, '7'),
                ('x-internal-token', settings.internal_api_token),
            )

        def time_remaining(self):
            return None

        async def abort(self, status, details):
            raise RuntimeError(f'{status.name}: {details}')

    coordinator_handler = await interceptor.intercept_service(coordinator_continuation, SimpleNamespace(method=coordinator_method))
    heartbeat_handler = await interceptor.intercept_service(heartbeat_continuation, SimpleNamespace(method=heartbeat_method))
    assert coordinator_handler is not None and coordinator_handler.unary_unary is not None
    assert heartbeat_handler is not None and heartbeat_handler.unary_unary is not None

    valid_request = runtime_coordinator_pb2.RuntimeCoordinatorGenerationRequest(generation=generation)
    blocked_call = asyncio.create_task(coordinator_handler.unary_unary(valid_request, cast(Any, Context())))
    try:
        assert await asyncio.to_thread(guard_started.wait, 2)
        queued_guards = [asyncio.create_task(coordinator_handler.unary_unary(valid_request, cast(Any, Context()))) for _ in range(general_lane.queue_limit)]
        for _ in range(100):
            if general_lane.pending_count == general_lane.queue_limit:
                break
            await asyncio.sleep(0.01)
        assert general_lane.active_count == 1
        assert general_lane.pending_count == general_lane.queue_limit
        assert backend_grpc_server._rpc_admission_lane(coordinator_method) is general_lane
        assert backend_grpc_server._rpc_admission_lane(heartbeat_method) is critical_lane

        heartbeat = worker_runtime_pb2.RuntimeWorkerHeartbeatRequest(worker_id='worker-heartbeat', active_jobs=0)
        response = await asyncio.wait_for(heartbeat_handler.unary_unary(heartbeat, cast(Any, Context())), timeout=1)
        assert response.worker_id == 'worker-heartbeat'
        assert heartbeat_calls == [('worker-heartbeat', 0)]

        release_guard.set()
        results = await asyncio.gather(blocked_call, *queued_guards)
        assert all(result.generation == generation for result in results)
        assert guard_calls == general_lane.queue_limit + 1

        stale_context = Context()
        stale_request = runtime_coordinator_pb2.RuntimeCoordinatorGenerationRequest(generation=generation - 1)
        with pytest.raises(RuntimeError, match='FAILED_PRECONDITION: Runtime coordinator generation 6 is fenced by 7'):
            await coordinator_handler.unary_unary(stale_request, cast(Any, stale_context))
        assert guard_calls == general_lane.queue_limit + 1

        class StaleMetadataContext(Context):
            def invocation_metadata(self):
                return (
                    (backend_grpc_server._RUNTIME_GENERATION_METADATA_KEY, '6'),
                    ('x-internal-token', settings.internal_api_token),
                )

        with pytest.raises(RuntimeError, match='FAILED_PRECONDITION: Runtime coordinator generation 6 is fenced by 7'):
            await coordinator_handler.unary_unary(valid_request, cast(Any, StaleMetadataContext()))
        assert guard_calls == general_lane.queue_limit + 1
    finally:
        release_guard.set()
        await asyncio.gather(blocked_call, *locals().get('queued_guards', []), return_exceptions=True)


def test_compute_claim_rpc_executor_runs_a_db_pool_bounded_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allow_internal_call(_context) -> None:
        return None

    monkeypatch.setattr(backend_grpc_server, '_require_internal_token', allow_internal_call)
    capacity = min(4, backend_grpc_server._INTERNAL_GENERAL_RPC_WORKERS)
    release = threading.Event()
    capacity_reached = threading.Event()
    started_count = 0
    started_lock = threading.Lock()

    def blocked_handler(_servicer, request, _metadata):
        nonlocal started_count
        with started_lock:
            started_count += 1
            if started_count == capacity:
                capacity_reached.set()
        assert release.wait(timeout=5)
        return request

    claim_handler = backend_grpc_server._run_claim_handler_in_thread(blocked_handler)

    async def exercise() -> None:
        calls = [asyncio.create_task(claim_handler(None, index, None)) for index in range(capacity)]
        assert await asyncio.to_thread(capacity_reached.wait, 2)
        release.set()
        assert await asyncio.gather(*calls) == list(range(capacity))

    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_lease_rpcs_do_not_queue_behind_lifecycle_control(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allow_internal_call(_context) -> None:
        return None

    monkeypatch.setattr(backend_grpc_server, '_require_internal_token', allow_internal_call)
    release = threading.Event()
    lane_filled = threading.Event()
    control_started = threading.Event()
    started_count = 0
    started_lock = threading.Lock()

    def blocked_handler(_servicer, request, _metadata):
        nonlocal started_count
        with started_lock:
            started_count += 1
            if started_count == backend_grpc_server._INTERNAL_LEASE_RPC_WORKERS:
                lane_filled.set()
            if request == 'control':
                control_started.set()
        assert release.wait(timeout=5)
        return request

    lease_handler = backend_grpc_server._run_critical_runtime_handler_in_thread(blocked_handler)
    control_handler = backend_grpc_server._run_control_handler_in_thread(blocked_handler)

    async def exercise() -> None:
        assert backend_grpc_server._INTERNAL_LEASE_RPC_WORKERS > 0
        lease_calls = [asyncio.create_task(lease_handler(None, f'lease-{index}', None)) for index in range(backend_grpc_server._INTERNAL_LEASE_RPC_WORKERS)]
        assert await asyncio.to_thread(lane_filled.wait, 2)
        control_call = asyncio.create_task(control_handler(None, 'control', None))
        assert await asyncio.to_thread(control_started.wait, 2)
        release.set()
        expected = [f'lease-{index}' for index in range(len(lease_calls))] + ['control']
        assert await asyncio.gather(*lease_calls, control_call) == expected

    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_scheduler_heartbeat_bypasses_saturated_general_rpc_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allow_internal_call(_context) -> None:
        return None

    monkeypatch.setattr(backend_grpc_server, '_require_internal_token', allow_internal_call)
    general_release = threading.Event()
    general_lane_full = threading.Event()
    heartbeat_started = threading.Event()
    started_count = 0
    started_lock = threading.Lock()

    def block_general_handler(_servicer, request, _metadata):
        nonlocal started_count
        with started_lock:
            started_count += 1
            if started_count == backend_grpc_server._INTERNAL_GENERAL_RPC_WORKERS:
                general_lane_full.set()
        assert general_release.wait(timeout=5)
        return request

    def heartbeat_handler(_servicer, request, _metadata):
        heartbeat_started.set()
        return request

    general_handler = backend_grpc_server._run_control_handler_in_thread(block_general_handler)
    liveness_handler = backend_grpc_server._run_scheduler_heartbeat_handler_in_thread(heartbeat_handler)

    async def exercise() -> None:
        general_calls = [
            asyncio.create_task(general_handler(None, f'general-{index}', None)) for index in range(backend_grpc_server._INTERNAL_GENERAL_RPC_WORKERS)
        ]
        assert await asyncio.to_thread(general_lane_full.wait, 2)
        assert await asyncio.wait_for(liveness_handler(None, 'heartbeat', None), timeout=1) == 'heartbeat'
        assert heartbeat_started.is_set()
        general_release.set()
        assert await asyncio.gather(*general_calls) == [f'general-{index}' for index in range(len(general_calls))]

    try:
        asyncio.run(exercise())
    finally:
        general_release.set()


def test_scheduler_heartbeat_does_not_queue_behind_saturated_lease_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allow_internal_call(_context) -> None:
        return None

    monkeypatch.setattr(backend_grpc_server, '_require_internal_token', allow_internal_call)
    lease_executor = ThreadPoolExecutor(max_workers=1)
    scheduler_executor = ThreadPoolExecutor(max_workers=1)
    release_lease = threading.Event()
    lease_started = threading.Event()
    heartbeat_started = threading.Event()
    monkeypatch.setattr(backend_grpc_server, '_INTERNAL_LEASE_RPC_EXECUTOR', lease_executor)
    monkeypatch.setattr(backend_grpc_server, '_INTERNAL_SCHEDULER_RPC_EXECUTOR', scheduler_executor)

    def blocked_lease(_servicer, request, _metadata):
        lease_started.set()
        assert release_lease.wait(timeout=5)
        return request

    def heartbeat(_servicer, request, _metadata):
        heartbeat_started.set()
        return request

    lease_handler = backend_grpc_server._run_critical_runtime_handler_in_thread(blocked_lease)
    liveness_handler = backend_grpc_server._run_scheduler_heartbeat_handler_in_thread(heartbeat)

    async def exercise() -> None:
        lease_call = asyncio.create_task(lease_handler(None, 'lease', None))
        assert await asyncio.to_thread(lease_started.wait, 1)
        assert await asyncio.wait_for(liveness_handler(None, 'heartbeat', None), timeout=1) == 'heartbeat'
        assert heartbeat_started.is_set()
        release_lease.set()
        assert await lease_call == 'lease'

    try:
        asyncio.run(exercise())
    finally:
        release_lease.set()
        lease_executor.shutdown(wait=True)
        scheduler_executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_fifty_general_rpc_waiters_fit_and_critical_rpc_progresses(monkeypatch: pytest.MonkeyPatch) -> None:
    queue_limit = backend_grpc_server._runtime_rpc_admission_queue_limit(32)
    assert queue_limit == 64
    assert backend_grpc_server._runtime_rpc_admission_queue_limit(100) == 200
    general_lane = backend_grpc_server._RpcAdmissionLane('general-test', 1, queue_limit=queue_limit)
    critical_lane = backend_grpc_server._RpcAdmissionLane('critical-test', 1)
    monkeypatch.setattr(
        backend_grpc_server,
        '_RPC_ADMISSION_LANES',
        {
            'general': general_lane,
            'critical': critical_lane,
            'scheduler': backend_grpc_server._RpcAdmissionLane('scheduler-test', 1),
            'external-io': backend_grpc_server._RpcAdmissionLane('external-test', 1),
        },
    )
    monkeypatch.setattr(backend_grpc_server, 'active_runtime_coordinator_generation', lambda: 7)
    interceptor = backend_grpc_server._BackendRequestValidationInterceptor()
    interceptor._validator = cast(Any, SimpleNamespace(validate=lambda _request: None))
    release_general = asyncio.Event()
    general_started = asyncio.Event()
    general_calls_started = 0
    admission_waits_ms: list[float] = []

    async def blocked_general(_request, _context):
        nonlocal general_calls_started
        general_calls_started += 1
        timing = backend_grpc_server._RPC_TIMING.get()
        assert timing is not None
        admission_waits_ms.append(timing['admission_queue_ms'])
        general_started.set()
        await release_general.wait()
        return 'general'

    async def heartbeat(_request, _context):
        return 'heartbeat'

    async def general_continuation(_details):
        return backend_grpc_server.grpc.unary_unary_rpc_method_handler(blocked_general)

    async def critical_continuation(_details):
        return backend_grpc_server.grpc.unary_unary_rpc_method_handler(heartbeat)

    class Context:
        def invocation_metadata(self):
            return ((backend_grpc_server._RUNTIME_GENERATION_METADATA_KEY, '7'),)

        def time_remaining(self):
            return None

        async def abort(self, status, details):
            raise RuntimeError(f'{status.name}: {details}')

    general_method = f'{backend_grpc_server._WORKER_RUNTIME_SERVICE_PREFIX}ClaimBuildJob'
    critical_method = f'{backend_grpc_server._WORKER_RUNTIME_SERVICE_PREFIX}HeartbeatWorker'
    general_handler = await interceptor.intercept_service(general_continuation, SimpleNamespace(method=general_method))
    critical_handler = await interceptor.intercept_service(critical_continuation, SimpleNamespace(method=critical_method))
    assert general_handler is not None and general_handler.unary_unary is not None
    assert critical_handler is not None and critical_handler.unary_unary is not None

    first_general = asyncio.create_task(general_handler.unary_unary(common_pb2.EmptyRequest(), cast(Any, Context())))
    queued_general: list[asyncio.Task[str]] = []
    try:
        await asyncio.wait_for(general_started.wait(), timeout=2)
        queued_general = [asyncio.create_task(general_handler.unary_unary(common_pb2.EmptyRequest(), cast(Any, Context()))) for _ in range(50)]
        await asyncio.sleep(0)
        assert general_lane.pending_count == 50
        queued_general.extend(
            asyncio.create_task(general_handler.unary_unary(common_pb2.EmptyRequest(), cast(Any, Context())))
            for _ in range(queue_limit - general_lane.pending_count)
        )
        await asyncio.sleep(0)
        assert general_lane.pending_count == queue_limit

        cancelled_general = queued_general.pop()
        cancelled_general.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled_general
        assert general_lane.pending_count == queue_limit - 1

        replacement_general = asyncio.create_task(general_handler.unary_unary(common_pb2.EmptyRequest(), cast(Any, Context())))
        queued_general.append(replacement_general)
        await asyncio.sleep(0)
        assert general_lane.pending_count == queue_limit
        with pytest.raises(RuntimeError, match='RESOURCE_EXHAUSTED'):
            await general_handler.unary_unary(common_pb2.EmptyRequest(), cast(Any, Context()))
        assert await asyncio.wait_for(critical_handler.unary_unary(common_pb2.EmptyRequest(), cast(Any, Context())), timeout=1) == 'heartbeat'
        release_general.set()
        assert await asyncio.gather(first_general, *queued_general) == ['general'] * (queue_limit + 1)
        assert general_lane.pending_count == 0
        assert general_calls_started == queue_limit + 1
        assert len(admission_waits_ms) == queue_limit + 1
        assert admission_waits_ms[0] < 10
        assert max(admission_waits_ms[1:]) > 0
    finally:
        release_general.set()
        await asyncio.gather(first_general, *queued_general, return_exceptions=True)


class _AdmissionContext:
    def __init__(self, remaining: float | None = None) -> None:
        self.remaining = remaining

    def time_remaining(self) -> float | None:
        return self.remaining


def _admission_context(*, remaining: float | None = None) -> _AdmissionContext:
    return _AdmissionContext(remaining)


@pytest.mark.asyncio
async def test_rpc_admission_queues_burst_beyond_active_width() -> None:
    lane = backend_grpc_server._RpcAdmissionLane('critical-test', 2, queue_limit=3)
    context = _admission_context()

    assert await lane.acquire(context)
    assert await lane.acquire(context)
    queued = [asyncio.create_task(lane.acquire(context)) for _ in range(3)]
    await asyncio.sleep(0)
    assert lane.active_count == 2
    assert lane.pending_count == 3

    lane.release()
    lane.release()
    assert await asyncio.gather(*queued[:2]) == [True, True]
    assert lane.active_count == 2
    assert lane.pending_count == 1
    lane.release()
    assert await queued[2]
    assert lane.pending_count == 0
    lane.release()
    lane.release()
    assert lane.active_count == 0

    granted_lane = backend_grpc_server._RpcAdmissionLane('critical-grant-race-test', 1, queue_limit=1)
    assert await granted_lane.acquire(_admission_context())
    granted_then_cancelled = asyncio.create_task(granted_lane.acquire(_admission_context()))
    await asyncio.sleep(0)
    granted_lane.release()
    granted_then_cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await granted_then_cancelled
    assert granted_lane.active_count == 0


@pytest.mark.asyncio
async def test_rpc_admission_cancellation_and_deadline_remove_waiters() -> None:
    lane = backend_grpc_server._RpcAdmissionLane('critical-test', 1, queue_limit=2)
    assert await lane.acquire(_admission_context())

    cancelled = asyncio.create_task(lane.acquire(_admission_context()))
    await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert lane.pending_count == 0
    assert lane.active_count == 1

    with pytest.raises(TimeoutError):
        await lane.acquire(_admission_context(remaining=0.001))
    assert lane.pending_count == 0
    assert lane.active_count == 1
    lane.release()
    assert lane.active_count == 0


@pytest.mark.asyncio
async def test_rpc_admission_rejects_only_after_bounded_pending_capacity_is_full() -> None:
    lane = backend_grpc_server._RpcAdmissionLane('critical-test', 1, queue_limit=1)
    context = _admission_context()
    assert await lane.acquire(context)

    queued = asyncio.create_task(lane.acquire(context))
    await asyncio.sleep(0)
    assert lane.pending_count == 1
    assert not await lane.acquire(context)
    assert lane.pending_count == 1

    lane.release()
    assert await queued
    lane.release()
    assert lane.active_count == 0


@pytest.mark.asyncio
async def test_rpc_admission_critical_lane_is_independent_of_general_queue() -> None:
    general = backend_grpc_server._RpcAdmissionLane('general-test', 1, queue_limit=1)
    critical = backend_grpc_server._RpcAdmissionLane('critical-test', 1, queue_limit=1)
    context = _admission_context()

    assert await general.acquire(context)
    general_waiter = asyncio.create_task(general.acquire(context))
    await asyncio.sleep(0)
    assert general.pending_count == 1
    assert await critical.acquire(context)
    assert critical.active_count == 1

    critical.release()
    general.release()
    assert await general_waiter
    general.release()


@pytest.mark.asyncio
async def test_cancelled_rpc_waits_for_running_handler_and_uses_copied_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    started = threading.Event()
    release = threading.Event()
    settled = threading.Event()
    rpc_metadata = backend_grpc_server.RpcMetadata(MappingProxyType({'x-test': 'copied'}))

    async def authenticate(_context):
        return rpc_metadata

    def handler(_servicer, request, metadata):
        assert metadata is rpc_metadata
        started.set()
        assert release.wait(timeout=5)
        settled.set()
        return request

    monkeypatch.setattr(backend_grpc_server, '_require_internal_token', authenticate)
    wrapped = backend_grpc_server._run_control_handler_in_thread(handler)
    call = asyncio.create_task(wrapped(None, 'terminal-write', object()))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        call.cancel()
        await asyncio.sleep(0.05)
        assert not call.done()
        assert not settled.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await call
        assert settled.is_set()
    finally:
        release.set()
        await asyncio.gather(call, return_exceptions=True)


def _context(monkeypatch: pytest.MonkeyPatch) -> FakeGrpcContext:
    token = 'test-internal-token'
    monkeypatch.setattr(settings, 'internal_api_token', token)
    return FakeGrpcContext(token)


def _schema_payload() -> dict[str, object]:
    return {
        'analysis_id': 'analysis-2',
        'target_step_id': 'source',
        'analysis_pipeline': {
            'analysis_id': 'analysis-2',
            'tabs': [
                {
                    'id': 'tab-1',
                    'datasource': {'id': 'datasource-1', 'analysis_tab_id': 'tab-1', 'source_type': 'file', 'config': {'branch': 'main'}},
                    'output': {'result_id': 'result-1', 'filename': 'result.csv', 'format': 'csv'},
                    'steps': [],
                }
            ],
        },
    }


def _create_request(
    test_db_session: Session,
    *,
    namespace: str,
    kind: enums_pb2.ComputeRequestKind,
    request_json: dict[str, object],
):
    return compute_requests_service.create_request(
        test_db_session,
        namespace=namespace,
        kind=kind,
        command=command_from_payload(kind, request_json),
    )


@pytest.mark.asyncio
async def test_internal_worker_grpc_registers_heartbeats_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    worker_id = f'local-worker:{uuid.uuid4()}'
    servicer = WorkerRuntimeServicer()

    await servicer.RegisterWorker(
        worker_runtime_pb2.RuntimeWorkerRegisterRequest(
            worker_id=worker_id,
            kind=enums_pb2.RUNTIME_WORKER_KIND_BUILD_WORKER,
            hostname='worker-host',
            pid=123,
            capacity=1,
        ),
        cast(Any, context),
    )
    await servicer.HeartbeatWorker(worker_runtime_pb2.RuntimeWorkerHeartbeatRequest(worker_id=worker_id, active_jobs=1), context)

    worker = run_settings_db(lambda session: session.get(RuntimeWorker, worker_id))
    assert worker is not None
    assert worker.active_jobs == 1

    await servicer.StopWorker(common_pb2.RuntimeWorkerRequest(worker_id=worker_id), context)
    worker = run_settings_db(lambda session: session.get(RuntimeWorker, worker_id))
    assert worker is not None
    assert worker.stopped_at is not None


@pytest.mark.asyncio
async def test_pending_runtime_namespaces_are_filtered_by_work_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    requested_kinds = []

    def cached_namespaces(kinds):
        requested_kinds.append(kinds)
        return ['default']

    monkeypatch.setattr(backend_grpc_server, '_cached_pending_runtime_work_namespaces', cached_namespaces)
    response = await WorkerRuntimeServicer().ListPendingRuntimeWorkNamespaces(
        worker_runtime_pb2.WorkerPendingRuntimeWorkNamespacesRequest(kinds=['build']),
        cast(Any, context),
    )

    assert response.namespaces == ['default']
    assert [[kind.value for kind in kinds] for kinds in requested_kinds] == [['build']]


def test_pending_namespace_cache_refreshes_unrelated_kinds_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend_grpc_server, '_RUNTIME_PENDING_NAMESPACE_CACHE', {})
    monkeypatch.setattr(backend_grpc_server, '_RUNTIME_WORK_CACHE_MISS_LOCKS', {})
    both_queries_started = threading.Barrier(2)

    def run_settings_db(_operation):
        both_queries_started.wait(timeout=2)
        return ['default']

    monkeypatch.setattr(backend_grpc_server, 'run_settings_db', run_settings_db)
    work_kinds = backend_grpc_server.runtime_work_service.RuntimeWorkKind
    with ThreadPoolExecutor(max_workers=2) as executor:
        build = executor.submit(backend_grpc_server._cached_pending_runtime_work_namespaces, (work_kinds.BUILD,))
        compute = executor.submit(backend_grpc_server._cached_pending_runtime_work_namespaces, (work_kinds.COMPUTE,))
        assert build.result(timeout=3) == ['default']
        assert compute.result(timeout=3) == ['default']


@pytest.mark.asyncio
async def test_internal_worker_grpc_claims_and_finalizes_build_job(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    worker_id = f'local-worker:{uuid.uuid4()}'
    build_id = str(uuid.uuid4())
    build_runs_service.create_build_run(
        test_db_session,
        build_id=build_id,
        namespace='default',
        analysis_id=str(uuid.uuid4()),
        analysis_name='gRPC boundary test',
        request_json={'analysis_pipeline': {'analysis_id': str(uuid.uuid4()), 'tabs': []}, 'tab_id': 'tab-1'},
        starter_json={'triggered_by': 'test'},
        status=BuildRunStatus.COMPLETED,
        created_at=datetime.now(UTC),
    )
    job = build_jobs_service.create_job(test_db_session, build_id=build_id, namespace='default')
    servicer = WorkerRuntimeServicer()

    response = await servicer.ClaimBuildJob(
        common_pb2.RuntimeWorkerRequest(worker_id=worker_id, protocol_version=2, target_namespace='default'),
        context,
    )

    assert response.HasField('job')
    assert response.job.job_id == job.id
    assert response.job.build_id == build_id
    assert response.job.namespace == 'default'
    assert response.job.claim_token
    assert response.job.lease_generation == 1
    assert response.job.HasField('lease_expires_at')
    assert response.job.attempt == 1
    assert response.job.lease_ttl_seconds == CLAIM_DELIVERY_LEASE_SECONDS
    test_db_session.refresh(job)
    assert job.status == BuildJobStatus.RUNNING
    assert job.lease_owner == worker_id
    assert job.claim_token == response.job.claim_token

    renewed = await servicer.RenewBuildJobLease(
        worker_runtime_pb2.WorkerBuildJobClaimRequest(
            job_id=job.id,
            namespace='default',
            claim_token=response.job.claim_token,
            lease_generation=response.job.lease_generation,
            worker_id=worker_id,
        ),
        cast(Any, context),
    )
    assert renewed.renewed is True
    assert renewed.HasField('lease_expires_at')

    finalized = await servicer.FinalizeBuildJob(
        worker_runtime_pb2.WorkerFinalizeBuildJobRequest(
            job_id=job.id,
            build_id=build_id,
            namespace='default',
            claim_token=response.job.claim_token,
            lease_generation=response.job.lease_generation,
            worker_id=worker_id,
        ),
        cast(Any, context),
    )
    assert finalized.value is True
    test_db_session.refresh(job)
    assert job.status == BuildJobStatus.COMPLETED
    assert job.lease_owner is None
    assert job.claim_token is None

    replayed = await servicer.FinalizeBuildJob(
        worker_runtime_pb2.WorkerFinalizeBuildJobRequest(
            job_id=job.id,
            build_id=build_id,
            namespace='default',
            claim_token=response.job.claim_token,
            lease_generation=response.job.lease_generation,
            worker_id=worker_id,
        ),
        cast(Any, context),
    )
    assert replayed.value is True


@pytest.mark.asyncio
async def test_internal_worker_grpc_does_not_finalize_job_before_build_is_terminal(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    worker_id = f'local-worker:{uuid.uuid4()}'
    build_id = str(uuid.uuid4())
    build_runs_service.create_build_run(
        test_db_session,
        build_id=build_id,
        namespace='default',
        analysis_id=str(uuid.uuid4()),
        analysis_name='Active finalization rejection',
        request_json={'analysis_pipeline': {'analysis_id': str(uuid.uuid4()), 'tabs': []}},
        starter_json={'triggered_by': 'test'},
        status=BuildRunStatus.RUNNING,
        execution_generation=1,
        created_at=datetime.now(UTC),
    )
    job = build_jobs_service.create_job(test_db_session, build_id=build_id, namespace='default')
    claimed = build_jobs_service.claim_next_job(test_db_session, worker_id=worker_id)
    assert claimed is not None
    assert claimed.claim_token is not None

    finalized = await WorkerRuntimeServicer().FinalizeBuildJob(
        worker_runtime_pb2.WorkerFinalizeBuildJobRequest(
            job_id=job.id,
            build_id=build_id,
            namespace='default',
            claim_token=claimed.claim_token,
            lease_generation=claimed.lease_generation,
            worker_id=worker_id,
        ),
        cast(Any, context),
    )

    assert finalized.value is False
    test_db_session.expire_all()
    stored = test_db_session.get(type(job), job.id)
    assert stored is not None
    assert stored.status == BuildJobStatus.RUNNING
    assert stored.claim_token == claimed.claim_token


@pytest.mark.asyncio
async def test_internal_worker_grpc_fails_job_and_build_run_atomically(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    worker_id = f'local-worker:{uuid.uuid4()}'
    build_id = str(uuid.uuid4())
    build_runs_service.create_build_run(
        test_db_session,
        build_id=build_id,
        namespace='default',
        analysis_id=str(uuid.uuid4()),
        analysis_name='Atomic worker failure',
        request_json={'analysis_pipeline': {'analysis_id': str(uuid.uuid4()), 'tabs': []}},
        starter_json={'triggered_by': 'test'},
        status=BuildRunStatus.RUNNING,
        execution_generation=1,
        created_at=datetime.now(UTC),
    )
    job = build_jobs_service.create_job(test_db_session, build_id=build_id, namespace='default')
    claimed = build_jobs_service.claim_next_job(test_db_session, worker_id=worker_id)
    assert claimed is not None
    assert claimed.claim_token is not None
    request = worker_runtime_pb2.WorkerFailBuildJobRequest(
        job_id=job.id,
        build_id=build_id,
        namespace='default',
        claim_token=claimed.claim_token,
        lease_generation=claimed.lease_generation,
        worker_id=worker_id,
        error='worker crashed before emitting a terminal event',
    )

    failed = await WorkerRuntimeServicer().FailBuildJob(request, cast(Any, context))

    assert failed.value is True
    test_db_session.expire_all()
    stored_job = test_db_session.get(type(job), job.id)
    stored_run = build_runs_service.get_build_run(test_db_session, build_id)
    events = build_runs_service.list_build_events_after(test_db_session, build_id)
    assert stored_job is not None
    assert stored_job.status == BuildJobStatus.FAILED
    assert stored_job.claim_token is None
    assert stored_run is not None
    assert stored_run.status == BuildRunStatus.FAILED
    assert stored_run.error_message == request.error
    assert stored_run.execution_generation == claimed.lease_generation
    assert [event.type for event in events] == ['failed']
    assert events[0].payload_json['error'] == request.error

    replayed = await WorkerRuntimeServicer().FailBuildJob(request, cast(Any, context))
    assert replayed.value is True
    assert len(build_runs_service.list_build_events_after(test_db_session, build_id)) == 1


@pytest.mark.asyncio
async def test_internal_worker_grpc_counts_and_releases_jobs(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    worker_id = f'local-worker:{uuid.uuid4()}'
    build_id = str(uuid.uuid4())
    job = build_jobs_service.create_job(test_db_session, build_id=build_id, namespace='default')
    servicer = WorkerRuntimeServicer()

    queued = await servicer.GetQueuedBuildJobCount(common_pb2.EmptyRequest(namespace='default'), context)
    assert queued.count >= 1

    await servicer.ClaimBuildJob(
        common_pb2.RuntimeWorkerRequest(worker_id=worker_id, protocol_version=2, target_namespace='default'),
        context,
    )
    released = await servicer.ReleaseBuildWorkerJobs(
        common_pb2.RuntimeWorkerRequest(worker_id=worker_id, protocol_version=2, target_namespace='default'),
        context,
    )
    assert released.count == 1
    test_db_session.refresh(job)
    assert job.status == BuildJobStatus.QUEUED
    assert job.lease_owner is None


@pytest.mark.parametrize('build_already_completed', [False, True])
@pytest.mark.asyncio
async def test_build_job_count_recovers_exhausted_scheduled_job(
    test_db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    build_already_completed: bool,
) -> None:
    context = _context(monkeypatch)
    now = datetime.now(UTC)
    schedule = Schedule(
        id=str(uuid.uuid4()),
        datasource_id=str(uuid.uuid4()),
        cron_expression='0 * * * *',
        enabled=True,
        lease_owner='scheduler:test',
        lease_expires_at=now + timedelta(minutes=5),
        created_at=now,
    )
    test_db_session.add(schedule)
    test_db_session.commit()
    build_id = str(uuid.uuid4())
    analysis_id = str(uuid.uuid4())
    build_runs_service.create_build_run(
        test_db_session,
        build_id=build_id,
        namespace='default',
        schedule_id=schedule.id,
        analysis_id=analysis_id,
        analysis_name='scheduled recovery',
        request_json={'analysis_pipeline': {'analysis_id': analysis_id, 'tabs': []}},
        starter_json={'triggered_by': f'schedule:{schedule.id}'},
        status=BuildRunStatus.COMPLETED if build_already_completed else BuildRunStatus.RUNNING,
        created_at=now,
    )
    if build_already_completed:
        build_runs_service.append_build_event(
            test_db_session,
            build_id=build_id,
            event=compute_schemas.BuildCompleteEvent(
                build_id=build_id,
                analysis_id=analysis_id,
                emitted_at=now,
                progress=1.0,
                elapsed_ms=1,
                total_steps=1,
                tabs_built=1,
                results=[],
                duration_ms=1,
            ),
        )
    job = build_jobs_service.create_job(test_db_session, build_id=build_id, namespace='default')
    claimed = build_jobs_service.claim_next_job(test_db_session, worker_id='worker:lost')
    assert claimed is not None
    claimed.lease_expires_at = now - timedelta(seconds=1)
    test_db_session.add(claimed)
    test_db_session.commit()

    await WorkerRuntimeServicer().ReconcileExpiredBuildJobs(common_pb2.EmptyRequest(namespace='default'), context)
    count = await WorkerRuntimeServicer().GetQueuedBuildJobCount(common_pb2.EmptyRequest(namespace='default'), context)

    assert count.count == 0
    test_db_session.expire_all()
    assert reconcile_schedule_run(test_db_session, build_id=build_id) is not None
    test_db_session.expire_all()
    recovered_job = test_db_session.get(type(job), job.id)
    recovered_run = build_runs_service.get_build_run(test_db_session, build_id)
    recovered_schedule = test_db_session.get(Schedule, schedule.id)
    assert recovered_job is not None and recovered_job.status == BuildJobStatus.FAILED
    expected_run_status = BuildRunStatus.COMPLETED if build_already_completed else BuildRunStatus.ORPHANED
    assert recovered_run is not None and recovered_run.status == expected_run_status
    assert recovered_schedule is not None
    assert recovered_schedule.lease_owner is None
    assert recovered_schedule.lease_expires_at is None
    if build_already_completed:
        assert recovered_schedule.last_successful_build_id == build_id
    else:
        assert recovered_schedule.last_failure_at is not None


@pytest.mark.asyncio
async def test_build_job_claim_rejects_incompatible_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)

    with pytest.raises(RuntimeError, match='protocol version is incompatible'):
        await WorkerRuntimeServicer().ClaimBuildJob(
            common_pb2.RuntimeWorkerRequest(worker_id='old-worker', protocol_version=1),
            context,
        )


@pytest.mark.asyncio
async def test_internal_worker_grpc_claims_completes_and_fails_compute_requests(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    worker_id = f'build-manager:{uuid.uuid4()}'
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE,
        request_json={
            'engine_identity': {
                'scope': 'analysis_interactive',
                'reuse_policy': 'shared',
                'resource_id': 'analysis-1',
                'analysis_id': 'analysis-1',
            }
        },
    )
    servicer = WorkerRuntimeServicer()

    response = await servicer.ClaimComputeRequest(
        compute_claim_request(worker_id, enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE),
        context,
    )

    assert response.HasField('request')
    assert response.request.id == request.id
    assert response.request.namespace == 'default'
    assert response.request.kind == enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE
    assert response.request.command.command.WhichOneof('command') == 'shutdown_engine'
    engine_identity = response.request.command.command.shutdown_engine.engine_identity
    assert engine_identity.scope == enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE
    assert engine_identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_SHARED
    assert engine_identity.analysis_id == 'analysis-1'
    assert engine_identity.resource_id == 'analysis-1'
    test_db_session.refresh(request)
    assert request.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING
    assert request.lease_owner == worker_id
    assert response.request.claim_token
    assert response.request.lease_generation == 1
    assert response.request.attempt == 1
    assert response.request.HasField('lease_expires_at')
    assert response.request.lease_ttl_seconds == CLAIM_DELIVERY_LEASE_SECONDS

    renewed = await servicer.RenewComputeRequestLeases(
        worker_runtime_pb2.WorkerRenewComputeRequestLeasesRequest(
            namespace='default',
            worker_id=worker_id,
            renewals=[
                worker_runtime_pb2.WorkerComputeRequestLeaseRenewal(
                    request_id=request.id,
                    claim_token=response.request.claim_token,
                    lease_generation=response.request.lease_generation,
                )
            ],
        ),
        context,
    )
    assert len(renewed.renewals) == 1
    assert renewed.renewals[0].request_id == request.id
    assert renewed.renewals[0].renewed is True
    assert renewed.renewals[0].lease_ttl_seconds == settings.runtime_work_lease_ttl_seconds

    await servicer.CompleteComputeRequest(
        worker_runtime_pb2.WorkerCompleteComputeRequestRequest(
            namespace='default',
            request_id=request.id,
            worker_id=worker_id,
            claim_token=response.request.claim_token,
            lease_generation=response.request.lease_generation,
            response_envelope=response_envelope(
                kind=enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE,
                request_id=request.id,
                status=enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED,
                payload={'success': True},
            ),
        ),
        context,
    )
    test_db_session.refresh(request)
    assert request.status == enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED

    failed_request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA,
        request_json=_schema_payload(),
    )
    response = await servicer.ClaimComputeRequest(
        compute_claim_request(worker_id, enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA),
        context,
    )
    assert response.request.id == failed_request.id

    await servicer.FailComputeRequest(
        worker_runtime_pb2.WorkerFailComputeRequestRequest(
            namespace='default',
            request_id=failed_request.id,
            worker_id=worker_id,
            claim_token=response.request.claim_token,
            lease_generation=response.request.lease_generation,
            error_message='boom',
            response_envelope=response_envelope(
                kind=enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA,
                request_id=failed_request.id,
                status=enums_pb2.COMPUTE_REQUEST_STATUS_FAILED,
                payload={'error': 'boom', 'status_code': 500},
                error_message='boom',
            ),
        ),
        context,
    )
    test_db_session.refresh(failed_request)
    assert failed_request.status == enums_pb2.COMPUTE_REQUEST_STATUS_FAILED


@pytest.mark.asyncio
async def test_preview_completion_finalizes_engine_run_in_the_same_rpc(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    worker_id = f'preview-worker:{uuid.uuid4()}'
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json={**_schema_payload(), 'row_limit': 100, 'page': 1},
    )
    engine_run = engine_runs_service.create_engine_run(
        test_db_session,
        engine_runs_service.create_engine_run_payload(
            analysis_id='analysis-2',
            datasource_id='datasource-1',
            kind=EngineRunKind.PREVIEW,
            status=EngineRunStatus.RUNNING,
            request_json={},
            result_json={},
        ),
    )
    claimed = await WorkerRuntimeServicer().ClaimComputeRequest(
        compute_claim_request(worker_id, enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW),
        context,
    )
    assert claimed.HasField('request')
    completed_at = datetime.now(UTC)
    update = worker_runtime_pb2.WorkerEngineRunUpdateFields(
        status=enums_pb2.ENGINE_RUN_STATUS_SUCCESS,
        progress=1.0,
    )
    update.result_json.CopyFrom(dict_to_struct({'results': [{'status': 'success'}]}))
    update.completed_at.CopyFrom(datetime_to_timestamp(completed_at))

    await WorkerRuntimeServicer().CompleteComputeRequest(
        worker_runtime_pb2.WorkerCompleteComputeRequestRequest(
            namespace='default',
            request_id=request.id,
            worker_id=worker_id,
            claim_token=claimed.request.claim_token,
            lease_generation=claimed.request.lease_generation,
            response_envelope=response_envelope(
                kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
                request_id=request.id,
                status=enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED,
                payload={'step_id': 'source', 'columns': [], 'column_types': {}, 'data': [], 'total_rows': 0, 'page': 1, 'page_size': 100},
            ),
            engine_run_finalization=worker_runtime_pb2.WorkerEngineRunFinalization(
                run_id=engine_run.id,
                update=update,
            ),
        ),
        context,
    )

    test_db_session.expire_all()
    stored_request = test_db_session.get(type(request), request.id)
    stored_run = engine_runs_service.get_engine_run(test_db_session, engine_run.id)
    assert stored_request is not None
    assert stored_request.status == enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
    assert stored_run is not None
    assert stored_run.status == EngineRunStatus.SUCCESS
    assert stored_run.completed_at is not None
    assert stored_run.result_json == {'results': [{'status': 'success'}]}


@pytest.mark.asyncio
async def test_compute_request_claim_does_not_reclaim_the_calling_worker(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    worker_id = f'build-manager:{uuid.uuid4()}'
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE,
        request_json={
            'engine_identity': {
                'scope': 'analysis_interactive',
                'reuse_policy': 'shared',
                'resource_id': 'self-reclaim-regression',
                'analysis_id': 'self-reclaim-regression',
            }
        },
    )
    claimed = compute_requests_service.claim_next_request(test_db_session, worker_id=worker_id)
    assert claimed is not None
    assert claimed.claim_token is not None
    original_claim_token = claimed.claim_token
    original_generation = claimed.lease_generation
    original_attempts = claimed.attempts

    def fake_run_settings_db(func, *args, **kwargs):
        if func is backend_grpc_server.runtime_worker_service.reclaimable_worker_ids:
            return {worker_id}
        raise AssertionError(f'Unexpected settings database callback: {func!r}')

    def fake_run_db(func, *args, **kwargs):
        return func(test_db_session, *args, **kwargs)

    monkeypatch.setattr(backend_grpc_server, 'run_settings_db', fake_run_settings_db)
    monkeypatch.setattr(backend_grpc_server, 'run_db', fake_run_db)

    response = await WorkerRuntimeServicer().ClaimComputeRequest(
        compute_claim_request(worker_id, enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE),
        context,
    )

    assert not response.HasField('request')
    test_db_session.expire_all()
    stored = test_db_session.get(type(request), request.id)
    assert stored is not None
    assert stored.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING
    assert stored.lease_owner == worker_id
    assert stored.claim_token == original_claim_token
    assert stored.lease_generation == original_generation
    assert stored.attempts == original_attempts


@pytest.mark.asyncio
async def test_compute_request_claim_targets_one_namespace_without_scanning(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    claimed_namespaces: list[str] = []

    def fake_run_settings_db(func, *args, **kwargs):
        if func is backend_grpc_server.runtime_worker_service.reclaimable_worker_ids:
            return set()
        raise AssertionError(f'Unexpected settings database callback: {func!r}')

    def fake_run_db(func, *args, **kwargs):
        if func is backend_grpc_server.compute_requests_service.claim_next_request:
            claimed_namespaces.append(get_namespace())
            return None
        raise AssertionError(f'Unexpected tenant database callback: {func!r}')

    monkeypatch.setattr(backend_grpc_server, 'run_settings_db', fake_run_settings_db)
    monkeypatch.setattr(backend_grpc_server, 'run_db', fake_run_db)

    response = await WorkerRuntimeServicer().ClaimComputeRequest(
        common_pb2.RuntimeWorkerRequest(
            worker_id='build-manager:fair-claim',
            protocol_version=2,
            target_namespace='other',
        ),
        context,
    )

    assert not response.HasField('request')
    assert claimed_namespaces == ['other']


@pytest.mark.asyncio
async def test_internal_worker_grpc_publishes_datasource_create(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)

    class _Response:
        def model_dump(self, *, mode: str) -> dict[str, object]:
            assert mode == 'json'
            return {
                'id': 'ds-1',
                'name': 'Created',
                'source_type': 'iceberg',
                'created_by': 'import',
                'config': {'branch': 'main'},
            }

    def fake_create_datasource(_session, **kwargs):
        assert kwargs['name'] == 'Created'
        assert kwargs['datasource_id'] == 'ds-1'
        assert kwargs['source_type'] == 'iceberg'
        return _Response()

    monkeypatch.setattr('modules.datasource.publication_service.create_datasource', fake_create_datasource)

    response = await WorkerRuntimeServicer().PublishDatasourceCreate(
        worker_runtime_pb2.WorkerPublishDatasourceCreateRequest(
            namespace='default',
            datasource_id='ds-1',
            name='Created',
            source_type=enums_pb2.DATA_SOURCE_TYPE_ICEBERG,
            config=dict_to_struct({'branch': 'main'}),
        ),
        context,
    )

    assert response.datasource.id == 'ds-1'
    assert response.datasource.name == 'Created'


@pytest.mark.asyncio
async def test_internal_worker_grpc_maps_lost_datasource_publication_claim(monkeypatch: pytest.MonkeyPatch, test_db_session: Session) -> None:
    context = _context(monkeypatch)
    from modules.datasource.publication_service import DatasourcePublicationClaimLost

    def reject_publication(_session, **_kwargs):
        raise DatasourcePublicationClaimLost('Datasource publication claim is no longer active')

    monkeypatch.setattr('modules.datasource.publication_service.publish_ingest', reject_publication)

    with pytest.raises(RuntimeError, match='publication claim is no longer active'):
        await WorkerRuntimeServicer().PublishDatasourceIngest(
            worker_runtime_pb2.WorkerPublishDatasourceIngestRequest(
                namespace='default',
                datasource_id='ds-1',
                config=dict_to_struct({'branch': 'main'}),
                expected_revision=1,
                compute_request_id='req-1',
                worker_id='worker-1',
                claim_token='claim-1',
                lease_generation=1,
            ),
            context,
        )


@pytest.mark.asyncio
async def test_schema_publication_rejects_expired_and_replaced_compute_claim(monkeypatch: pytest.MonkeyPatch, test_db_session: Session) -> None:
    context = _context(monkeypatch)
    datasource_id = str(uuid.uuid4())
    test_db_session.add(
        DataSource(
            id=datasource_id,
            name='Claim fenced schema',
            source_type=DataSourceType.FILE.value,
            config={'file_path': 's3://bucket/source.csv'},
            revision=2,
            schema_cache={'columns': [{'name': 'current', 'dtype': 'Int64', 'nullable': True}]},
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        request_json={'datasource_id': datasource_id, 'refresh': True},
    )
    stale_claim = compute_requests_service.claim_next_request(test_db_session, worker_id='worker:old')
    assert stale_claim is not None
    assert stale_claim.id == request.id
    stale_token = stale_claim.claim_token
    stale_generation = stale_claim.lease_generation
    assert stale_token is not None
    stale_claim.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    test_db_session.add(stale_claim)
    test_db_session.commit()

    replacement = compute_requests_service.claim_next_request(test_db_session, worker_id='worker:new')
    assert replacement is not None
    assert replacement.id == request.id
    assert replacement.claim_token != stale_token

    with pytest.raises(RuntimeError, match='claim is no longer active'):
        await WorkerRuntimeServicer().PublishDatasourceSchemaCache(
            worker_runtime_pb2.WorkerPublishDatasourceSchemaCacheRequest(
                namespace='default',
                datasource_id=datasource_id,
                schema_info=datasource_pb2.SchemaInfo(columns=[datasource_pb2.ColumnSchema(name='obsolete', dtype='String', nullable=True)]),
                expected_revision=2,
                compute_request_id=request.id,
                worker_id='worker:old',
                claim_token=stale_token,
                lease_generation=stale_generation,
            ),
            context,
        )

    test_db_session.expire_all()
    stored = test_db_session.get(DataSource, datasource_id)
    assert stored is not None
    assert stored.schema_cache == {'columns': [{'name': 'current', 'dtype': 'Int64', 'nullable': True}]}


@pytest.mark.asyncio
async def test_schema_publication_rejects_valid_claim_for_another_datasource(monkeypatch: pytest.MonkeyPatch, test_db_session: Session) -> None:
    context = _context(monkeypatch)
    source_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    original_schema = {'columns': [{'name': 'current', 'dtype': 'Int64', 'nullable': True}]}
    for datasource_id, name in ((source_id, 'Schema source'), (other_id, 'Foreign target')):
        test_db_session.add(
            DataSource(
                id=datasource_id,
                name=name,
                source_type=DataSourceType.FILE.value,
                config={'file_path': 's3://bucket/source.csv'},
                revision=2,
                schema_cache=original_schema,
                created_at=datetime.now(UTC),
            )
        )
    test_db_session.commit()
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        request_json={'datasource_id': source_id, 'refresh': True},
    )
    claim = compute_requests_service.claim_next_request(test_db_session, worker_id='worker:schema')
    assert claim is not None and claim.id == request.id and claim.claim_token is not None

    with pytest.raises(RuntimeError, match='targets a different datasource'):
        await WorkerRuntimeServicer().PublishDatasourceSchemaCache(
            worker_runtime_pb2.WorkerPublishDatasourceSchemaCacheRequest(
                namespace='default',
                datasource_id=other_id,
                schema_info=datasource_pb2.SchemaInfo(columns=[datasource_pb2.ColumnSchema(name='foreign', dtype='String', nullable=True)]),
                expected_revision=2,
                compute_request_id=claim.id,
                worker_id='worker:schema',
                claim_token=claim.claim_token,
                lease_generation=claim.lease_generation,
            ),
            context,
        )

    test_db_session.expire_all()
    for datasource_id in (source_id, other_id):
        stored = test_db_session.get(DataSource, datasource_id)
        assert stored is not None and stored.schema_cache == original_schema


@pytest.mark.asyncio
async def test_internal_worker_grpc_uses_typed_schema_info_for_datasource_metadata(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    datasource_id = str(uuid.uuid4())
    test_db_session.add(
        DataSource(
            id=datasource_id,
            name='Typed schema datasource',
            source_type=DataSourceType.FILE.value,
            config={'file_path': 's3://bucket/source.csv'},
            schema_cache={'columns': [{'name': 'id', 'dtype': 'Int64', 'nullable': False}], 'row_count': 1},
            is_hidden=False,
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()

    original_dict_to_struct = backend_grpc_server.dict_to_struct

    def verify_session_released(payload: dict[str, object]) -> struct_pb2.Struct:
        assert database_pool_snapshot().get('tenant_checkedout', 0) == 0
        return original_dict_to_struct(payload)

    monkeypatch.setattr(backend_grpc_server, 'dict_to_struct', verify_session_released)

    response = await WorkerRuntimeServicer().GetDatasourceMetadata(
        worker_runtime_pb2.WorkerDatasourceMetadataRequest(namespace='default', datasource_id=datasource_id),
        context,
    )

    assert response.found is True
    assert response.schema_info.columns[0].name == 'id'
    assert response.schema_info.row_count == 1


@pytest.mark.parametrize(
    ('method_name', 'expected_phases'),
    [
        (
            'CreateEngineRun',
            (
                'payload_conversion_ms',
                'db_unit_ms',
                'engine_run_payload_service_ms',
                'engine_run_persistence_service_ms',
                'response_transformation_ms',
                'grpc_response_serialization_ms',
            ),
        ),
        (
            'GetDatasourceMetadata',
            (
                'db_unit_ms',
                'datasource_row_lookup_ms',
                'datasource_payload_conversion_ms',
                'column_descriptions_service_ms',
                'response_transformation_ms',
                'grpc_response_serialization_ms',
            ),
        ),
    ],
)
@pytest.mark.asyncio
async def test_slow_metadata_and_engine_run_rpcs_log_ordered_phase_timings(
    method_name: str,
    expected_phases: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class ImmediateExecutor:
        def submit(self, function, /, *args, **kwargs):
            future = Future()
            try:
                future.set_result(function(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)
            return future

    class FakeClock:
        current = 0.0

        def __call__(self) -> float:
            self.current += 0.2
            return self.current

    monkeypatch.setattr(backend_grpc_server, '_RPC_PHASE_MONOTONIC', FakeClock())
    monkeypatch.setattr(settings, 'internal_api_token', 'phase-test-token')
    monkeypatch.setattr(backend_grpc_server, '_INTERNAL_RPC_EXECUTOR', ImmediateExecutor())
    monkeypatch.setattr(backend_grpc_server, '_validation_executor', lambda _method: ImmediateExecutor())
    monkeypatch.setattr(backend_grpc_server, 'active_runtime_coordinator_generation', lambda: 7)
    monkeypatch.setattr(
        backend_grpc_server,
        '_RPC_ADMISSION_LANES',
        {
            'general': backend_grpc_server._RpcAdmissionLane('general-phase-test', 1),
            'critical': backend_grpc_server._RpcAdmissionLane('critical-phase-test', 1),
            'scheduler': backend_grpc_server._RpcAdmissionLane('scheduler-phase-test', 1),
            'external-io': backend_grpc_server._RpcAdmissionLane('external-phase-test', 1),
        },
    )

    servicer = WorkerRuntimeServicer()
    request: Any
    if method_name == 'CreateEngineRun':
        monkeypatch.setattr(backend_grpc_server.engine_run_service, 'create_engine_run_payload', lambda **fields: fields)
        monkeypatch.setattr(
            backend_grpc_server.engine_run_commands,
            'create_engine_run',
            lambda _session, _payload: SimpleNamespace(id='phase-test-run'),
        )
        monkeypatch.setattr(backend_grpc_server, 'run_db', lambda function, *args, **kwargs: function(object(), *args, **kwargs))
        request = worker_runtime_pb2.WorkerCreateEngineRunRequest(
            namespace='default',
            datasource_id='phase-test-datasource',
            kind=enums_pb2.ENGINE_RUN_KIND_PREVIEW,
            status=enums_pb2.ENGINE_RUN_STATUS_SUCCESS,
            request=dict_to_struct({'target_step_id': 'source'}),
        )
    else:
        datasource = SimpleNamespace(
            id='phase-test-datasource',
            name='Phase test datasource',
            source_type='file',
            config={'file_path': 's3://bucket/source.csv'},
            is_hidden=False,
            revision=1,
            created_by='phase-test-owner',
            description=None,
            schema_cache=None,
        )

        class FakeSession:
            def get(self, _model, datasource_id: str):
                assert datasource_id == datasource.id
                return datasource

        def fake_get_db():
            yield FakeSession()

        monkeypatch.setattr(backend_grpc_server, 'get_db', fake_get_db)
        monkeypatch.setattr(
            backend_grpc_server.datasource_publication_service,
            'column_description_map',
            lambda _session, _datasource_id: {'column': 'description'},
        )
        request = worker_runtime_pb2.WorkerDatasourceMetadataRequest(
            namespace='default',
            datasource_id='phase-test-datasource',
        )

    class Context:
        def invocation_metadata(self):
            return (
                (backend_grpc_server._RUNTIME_GENERATION_METADATA_KEY, '7'),
                ('x-internal-token', 'phase-test-token'),
            )

        def time_remaining(self):
            return None

        async def abort(self, status, details):
            raise RuntimeError(f'{status.name}: {details}')

    async def continuation(_details):
        return backend_grpc_server.grpc.unary_unary_rpc_method_handler(
            getattr(servicer, method_name),
            response_serializer=lambda response: response.SerializeToString(),
        )

    interceptor = backend_grpc_server._BackendRequestValidationInterceptor()
    interceptor._validator = cast(Any, SimpleNamespace(validate=lambda _request: None))
    rpc_method = f'{backend_grpc_server._WORKER_RUNTIME_SERVICE_PREFIX}{method_name}'
    handler = await interceptor.intercept_service(continuation, SimpleNamespace(method=rpc_method))
    assert handler is not None and handler.unary_unary is not None and handler.response_serializer is not None

    caplog.set_level(logging.WARNING, logger='backend_grpc.server')
    response = await handler.unary_unary(request, cast(Any, Context()))
    assert handler.response_serializer(response)

    record = next(record for record in caplog.records if f'method={method_name} ' in record.getMessage())
    message = record.getMessage()
    assert 'phase_timings_ms=' in message
    positions = [message.index(phase) for phase in expected_phases]
    assert positions == sorted(positions)
    assert 'phase-test-owner' not in message
    assert 's3://bucket/source.csv' not in message


@pytest.mark.asyncio
async def test_internal_worker_grpc_upserts_output_datasource_with_typed_schema_info(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    datasource_id = str(uuid.uuid4())

    response = await WorkerRuntimeServicer().UpsertOutputDatasource(
        worker_runtime_pb2.WorkerUpsertOutputDatasourceRequest(
            namespace='default',
            result_id=datasource_id,
            name='Typed output',
            source_type=enums_pb2.DATA_SOURCE_TYPE_ANALYSIS,
            config=dict_to_struct({'metadata_path': 's3://bucket/output'}),
            schema_info=datasource_pb2.SchemaInfo(
                columns=[datasource_pb2.ColumnSchema(name='score', dtype='Float64', nullable=True)],
                row_count=10,
            ),
            keep_schema_cache=False,
            notification_delivery=[
                worker_runtime_pb2.WorkerNotificationDelivery(
                    email=worker_runtime_pb2.WorkerEmailDelivery(to='owner@example.com', subject='Ready', body='Output published')
                )
            ],
        ),
        context,
    )

    datasource = test_db_session.get(DataSource, response.datasource_id)
    assert datasource is not None
    assert datasource.schema_cache == {
        'columns': [{'name': 'score', 'dtype': 'Float64', 'nullable': True}],
        'row_count': 10,
    }
    outbox = test_db_session.execute(select(RuntimeOutboxEvent)).scalars().one()
    assert outbox.payload_json == {
        'kind': 'email_delivery',
        'to': 'owner@example.com',
        'subject': 'Ready',
        'body': 'Output published',
        'attachments': [],
    }


@pytest.mark.asyncio
async def test_internal_worker_grpc_rejects_stale_output_publication_without_mutating_datasource(
    test_db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(monkeypatch)
    datasource_id = str(uuid.uuid4())
    build_id = str(uuid.uuid4())
    analysis_id = str(uuid.uuid4())
    build_runs_service.create_build_run(
        test_db_session,
        build_id=build_id,
        namespace='default',
        analysis_id=analysis_id,
        analysis_name='Stale publication test',
        request_json={'analysis_pipeline': {'analysis_id': analysis_id, 'tabs': []}},
        starter_json={'triggered_by': 'test'},
        status=BuildRunStatus.RUNNING,
        execution_generation=1,
        created_at=datetime.now(UTC),
    )
    build_jobs_service.create_job(test_db_session, build_id=build_id, namespace='default')
    claimed = build_jobs_service.claim_next_job(test_db_session, worker_id='worker:publisher')
    assert claimed is not None
    test_db_session.add(
        DataSource(
            id=datasource_id,
            name='Published output',
            source_type=DataSourceType.ICEBERG.value,
            config={'metadata_path': 's3://bucket/published'},
            schema_cache={'columns': [{'name': 'old', 'dtype': 'Int64', 'nullable': False}]},
            is_hidden=False,
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()

    with pytest.raises(RuntimeError, match='lease is no longer active'):
        await WorkerRuntimeServicer().UpsertOutputDatasource(
            worker_runtime_pb2.WorkerUpsertOutputDatasourceRequest(
                namespace='default',
                result_id=datasource_id,
                name='Stale output',
                source_type=enums_pb2.DATA_SOURCE_TYPE_ICEBERG,
                config=dict_to_struct({'metadata_path': 's3://bucket/stale'}),
                schema_info=datasource_pb2.SchemaInfo(columns=[datasource_pb2.ColumnSchema(name='new', dtype='String', nullable=True)]),
                job_id=claimed.id,
                build_id=build_id,
                worker_id='worker:publisher',
                claim_token='stale-token',
                lease_generation=claimed.lease_generation,
                build_result=dict_to_struct({'current_output_id': datasource_id}),
                notification_delivery=[
                    worker_runtime_pb2.WorkerNotificationDelivery(
                        email=worker_runtime_pb2.WorkerEmailDelivery(to='owner@example.com', subject='Stale', body='Must not enqueue')
                    )
                ],
            ),
            cast(Any, context),
        )

    test_db_session.expire_all()
    datasource = test_db_session.get(DataSource, datasource_id)
    build = build_runs_service.get_build_run(test_db_session, build_id)
    assert datasource is not None
    assert datasource.name == 'Published output'
    assert datasource.config == {'metadata_path': 's3://bucket/published'}
    assert datasource.schema_cache == {'columns': [{'name': 'old', 'dtype': 'Int64', 'nullable': False}]}
    assert build is not None
    assert build.result_json is None
    assert list(test_db_session.execute(select(RuntimeOutboxEvent)).scalars().all()) == []


@pytest.mark.asyncio
async def test_internal_worker_grpc_rolls_back_output_publication_when_notification_staging_fails(
    test_db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(monkeypatch)
    datasource_id = str(uuid.uuid4())
    build_id = str(uuid.uuid4())
    analysis_id = str(uuid.uuid4())
    build_runs_service.create_build_run(
        test_db_session,
        build_id=build_id,
        namespace='default',
        analysis_id=analysis_id,
        analysis_name='Atomic publication test',
        request_json={'analysis_pipeline': {'analysis_id': analysis_id, 'tabs': []}},
        starter_json={'triggered_by': 'test'},
        status=BuildRunStatus.RUNNING,
        execution_generation=1,
        created_at=datetime.now(UTC),
    )
    build_jobs_service.create_job(test_db_session, build_id=build_id, namespace='default')
    claimed = build_jobs_service.claim_next_job(test_db_session, worker_id='worker:publisher')
    assert claimed is not None
    test_db_session.add(
        DataSource(
            id=datasource_id,
            name='Published output',
            source_type=DataSourceType.ICEBERG.value,
            config={'metadata_path': 's3://bucket/published'},
            is_hidden=False,
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()

    def reject_notification(_session: Session, _payload: dict[str, object]) -> RuntimeOutboxEvent:
        raise RuntimeError('notification staging failed')

    monkeypatch.setattr('modules.datasource.commands.runtime_outbox_service.enqueue_notification_delivery', reject_notification)

    with pytest.raises(RuntimeError, match='notification staging failed'):
        await WorkerRuntimeServicer().UpsertOutputDatasource(
            worker_runtime_pb2.WorkerUpsertOutputDatasourceRequest(
                namespace='default',
                result_id=datasource_id,
                name='Uncommitted output',
                source_type=enums_pb2.DATA_SOURCE_TYPE_ICEBERG,
                config=dict_to_struct({'metadata_path': 's3://bucket/uncommitted'}),
                schema_info=datasource_pb2.SchemaInfo(),
                job_id=claimed.id,
                build_id=build_id,
                worker_id='worker:publisher',
                claim_token=claimed.claim_token,
                lease_generation=claimed.lease_generation,
                build_result=dict_to_struct({'current_output_id': datasource_id}),
                notification_delivery=[
                    worker_runtime_pb2.WorkerNotificationDelivery(
                        email=worker_runtime_pb2.WorkerEmailDelivery(to='owner@example.com', subject='Ready', body='Must roll back')
                    )
                ],
            ),
            cast(Any, context),
        )

    test_db_session.expire_all()
    datasource = test_db_session.get(DataSource, datasource_id)
    build = build_runs_service.get_build_run(test_db_session, build_id)
    assert datasource is not None
    assert datasource.name == 'Published output'
    assert datasource.config == {'metadata_path': 's3://bucket/published'}
    assert build is not None
    assert build.result_json is None
    assert list(test_db_session.execute(select(RuntimeOutboxEvent)).scalars().all()) == []


@pytest.mark.asyncio
async def test_internal_worker_grpc_returns_udf_codes_by_id(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    udf_id = str(uuid.uuid4())
    test_db_session.add(
        Udf(
            id=udf_id,
            name='typed_lookup',
            signature={'inputs': [], 'output_dtype': 'String'},
            code='def udf():\n    return "typed"',
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()

    response = await WorkerRuntimeServicer().GetUdfCodes(
        worker_runtime_pb2.WorkerUdfCodesRequest(namespace='default', udf_ids=[udf_id, 'missing-udf']),
        context,
    )

    assert response.codes == {udf_id: 'def udf():\n    return "typed"'}


@pytest.mark.asyncio
async def test_internal_worker_grpc_returns_active_telegram_targets(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    test_db_session.add_all(
        [
            TelegramSubscriber(chat_id='active-chat', title='Active', bot_token='tok-active', is_active=True, subscribed_at=datetime.now(UTC)),
            TelegramSubscriber(chat_id='inactive-chat', title='Inactive', bot_token='tok-inactive', is_active=False, subscribed_at=datetime.now(UTC)),
            TelegramSubscriber(chat_id='empty-token-chat', title='No token', bot_token='', is_active=True, subscribed_at=datetime.now(UTC)),
        ]
    )
    test_db_session.commit()

    response = await WorkerRuntimeServicer().GetTelegramTargets(
        worker_runtime_pb2.WorkerTelegramTargetsRequest(namespace='default', active_subscribers=True),
        context,
    )

    assert [(target.chat_id, target.bot_token) for target in response.targets] == [('active-chat', 'tok-active')]


@pytest.mark.asyncio
async def test_internal_worker_grpc_returns_datasource_telegram_targets(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    active = TelegramSubscriber(chat_id='datasource-chat', title='Datasource', bot_token='tok-ds', is_active=True, subscribed_at=datetime.now(UTC))
    inactive = TelegramSubscriber(chat_id='inactive-chat', title='Inactive', bot_token='tok-inactive', is_active=False, subscribed_at=datetime.now(UTC))
    other = TelegramSubscriber(chat_id='other-chat', title='Other', bot_token='tok-other', is_active=True, subscribed_at=datetime.now(UTC))
    test_db_session.add_all([active, inactive, other])
    test_db_session.commit()
    active_id = active.id
    inactive_id = inactive.id
    other_id = other.id
    assert active_id is not None
    assert inactive_id is not None
    assert other_id is not None
    test_db_session.add_all(
        [
            TelegramListener(subscriber_id=active_id, datasource_id='datasource-target'),
            TelegramListener(subscriber_id=inactive_id, datasource_id='datasource-target'),
            TelegramListener(subscriber_id=other_id, datasource_id='other-datasource'),
        ]
    )
    test_db_session.commit()

    response = await WorkerRuntimeServicer().GetTelegramTargets(
        worker_runtime_pb2.WorkerTelegramTargetsRequest(namespace='default', datasource_id='datasource-target'),
        context,
    )

    assert [(target.chat_id, target.bot_token) for target in response.targets] == [('datasource-chat', 'tok-ds')]


@pytest.mark.asyncio
async def test_internal_worker_grpc_creates_engine_run_with_typed_execution_entries(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    request = worker_runtime_pb2.WorkerCreateEngineRunRequest(
        namespace='default',
        analysis_id='analysis-1',
        datasource_id='datasource-1',
        kind=enums_pb2.ENGINE_RUN_KIND_PREVIEW,
        status=enums_pb2.ENGINE_RUN_STATUS_SUCCESS,
        request=dict_to_struct({'target_step_id': 'source'}),
        result=dict_to_struct({'row_count': 1}),
        timing_by_key={'filter': 12.5},
        execution_entry=[
            compute_pb2.EngineRunExecutionEntry(
                key='filter',
                label='Filter',
                category=enums_pb2.ENGINE_RUN_EXECUTION_CATEGORY_STEP,
                order=0,
                duration_ms=12.5,
                share_pct=100.0,
                step_type=enums_pb2.STEP_TYPE_FILTER,
            )
        ],
        progress=1.0,
        idempotency_key='preview-request-grpc',
    )
    servicer = WorkerRuntimeServicer()
    response = await servicer.CreateEngineRun(request, context)
    retry = await servicer.CreateEngineRun(request, context)

    assert retry.id == response.id == request.idempotency_key

    run = engine_runs_service.get_engine_run(test_db_session, response.id)
    assert run is not None
    assert run.step_timings == {'filter': 12.5}
    assert run.execution_entries[0].category == 'step'
    assert run.execution_entries[0].metadata == {'step_type': 'filter'}


@pytest.mark.asyncio
async def test_internal_worker_grpc_updates_engine_run_with_typed_fields(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    servicer = WorkerRuntimeServicer()
    created = await servicer.CreateEngineRun(
        worker_runtime_pb2.WorkerCreateEngineRunRequest(
            namespace='default',
            analysis_id='analysis-1',
            datasource_id='datasource-1',
            kind=enums_pb2.ENGINE_RUN_KIND_PREVIEW,
            status=enums_pb2.ENGINE_RUN_STATUS_RUNNING,
            request=dict_to_struct({'target_step_id': 'source'}),
            progress=0.25,
        ),
        context,
    )

    completed_at = datetime.now(UTC)
    response = await servicer.UpdateEngineRun(
        worker_runtime_pb2.WorkerUpdateEngineRunRequest(
            namespace='default',
            run_id=created.id,
            merge_result=False,
            update=worker_runtime_pb2.WorkerEngineRunUpdateFields(
                status=enums_pb2.ENGINE_RUN_STATUS_SUCCESS,
                result_json=dict_to_struct({'row_count': 2}),
                completed_at=datetime_to_timestamp(completed_at),
                duration_ms=42,
                step_timings=worker_runtime_pb2.EngineRunStepTimings(values={'filter': 2.5}),
                execution_entries=worker_runtime_pb2.EngineRunExecutionEntryList(
                    entries=[
                        compute_pb2.EngineRunExecutionEntry(
                            key='filter',
                            label='Filter',
                            category=enums_pb2.ENGINE_RUN_EXECUTION_CATEGORY_STEP,
                            order=0,
                            duration_ms=2.5,
                            step_type=enums_pb2.STEP_TYPE_FILTER,
                        )
                    ]
                ),
                progress=1.0,
                current_step='filter',
            ),
        ),
        context,
    )

    assert response.id == created.id
    run = engine_runs_service.get_engine_run(test_db_session, created.id)
    assert run is not None
    assert run.status == 'success'
    assert run.result_json is not None
    assert run.result_json['row_count'] == 2
    assert run.step_timings == {'filter': 2.5}
    assert run.current_step == 'filter'
    assert run.progress == 1.0
    assert run.execution_entries[0].metadata == {'step_type': 'filter'}


@pytest.mark.asyncio
async def test_internal_worker_grpc_persists_typed_engine_snapshot(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    context = _context(monkeypatch)
    monkeypatch.setattr(backend_grpc_server, '_SLOW_ENGINE_SNAPSHOT_PHASE_SECONDS', 0)
    queued_notifications: list[tuple[Any, dict[str, object], bool]] = []

    def queue_notification(session: Any, payload: dict[str, object]) -> None:
        queued_notifications.append((session, payload, session.in_transaction()))

    def reject_direct_notification(_namespace: str) -> None:
        pytest.fail('engine snapshot must not use the direct notification connection')

    monkeypatch.setattr(engine_instances_service.runtime_ipc, 'notify_runtime_payload_on_commit', queue_notification)
    monkeypatch.setattr(engine_instances_service.runtime_ipc, 'notify_api_engine', reject_direct_notification)

    response = await WorkerRuntimeServicer().PersistEngineSnapshot(
        worker_runtime_pb2.WorkerPersistEngineSnapshotRequest(
            worker_id='worker-typed-snapshot',
            namespace='default',
            engine_status=[
                compute_pb2.EngineStatusResult(
                    analysis_id='analysis-1',
                    resource_id='datasource-1',
                    status=enums_pb2.ENGINE_STATUS_HEALTHY,
                    container_id='container-1234',
                    image_digest='sha256:abc',
                    lifecycle_status=enums_pb2.ENGINE_INSTANCE_STATUS_RUNNING,
                    supervisor_id='worker-typed-snapshot',
                    owner_id='worker-typed-snapshot',
                    last_activity=datetime.now(UTC).isoformat(),
                    current_job_id='job-1',
                    resource_config=compute_pb2.EngineResourceConfig(max_threads=2),
                    effective_resources=compute_pb2.EngineResourceConfig(max_threads=2, max_memory_mb=1024),
                    defaults=compute_pb2.EngineDefaults(max_threads=2, max_memory_mb=1024, streaming_chunk_size=500),
                    scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW,
                    reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
                    datasource_id='datasource-1',
                )
            ],
        ),
        cast(Any, context),
    )

    assert response.count == 1
    phase_log = next(record.getMessage() for record in caplog.records if 'Slow PersistEngineSnapshot phases' in record.getMessage())
    assert 'worker_id=worker-typed-snapshot' in phase_log
    assert 'namespace=default' in phase_log
    assert 'status_count=1' in phase_log
    assert 'protobuf_to_status_conversion_ms=' in phase_log
    assert 'settings_db_persistence_ms=' in phase_log
    assert 'advisory_lock_wait_ms=' in phase_log
    assert 'snapshot_write_ms=' in phase_log
    assert 'active_id_mapping_ms=' in phase_log
    assert 'existing_row_query_fetch_ms=' in phase_log
    assert 'applying_statuses_ms=' in phase_log
    assert 'stale_row_sweep_ms=' in phase_log
    assert 'notification_enqueue_ms=' in phase_log
    assert 'snapshot_commit_ms=' in phase_log
    assert len(queued_notifications) == 1
    _session, payload, transaction_active = queued_notifications[0]
    assert payload == {'kind': 'engine', 'namespace': 'default'}
    assert transaction_active

    instances = [
        instance
        for instance in run_settings_db(engine_instances_service.list_engine_instances, namespace='default')
        if instance.worker_id == 'worker-typed-snapshot'
    ]
    assert len(instances) == 1
    assert instances[0].resource_config_json == {'max_threads': 2}
    assert instances[0].effective_resources_json == {'max_threads': 2, 'max_memory_mb': 1024}
    assert instances[0].container_id == 'container-1234'
    assert instances[0].image_digest == 'sha256:abc'
    assert instances[0].status == EngineInstanceStatus.RUNNING


@pytest.mark.asyncio
async def test_internal_worker_grpc_persists_build_event(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    build_id = str(uuid.uuid4())
    worker_id = f'local-worker:{uuid.uuid4()}'
    analysis_id = str(uuid.uuid4())
    build_runs_service.create_build_run(
        test_db_session,
        build_id=build_id,
        namespace='default',
        analysis_id=analysis_id,
        analysis_name='Event gRPC boundary test',
        request_json={'analysis_pipeline': {'analysis_id': analysis_id, 'tabs': []}, 'tab_id': 'tab-1'},
        starter_json={'triggered_by': 'test'},
        status=BuildRunStatus.RUNNING,
        execution_generation=1,
        created_at=datetime.now(UTC),
    )
    build_jobs_service.create_job(test_db_session, build_id=build_id, namespace='default')
    job = build_jobs_service.claim_next_job(test_db_session, worker_id=worker_id)
    assert job is not None
    assert job.claim_token is not None
    claim_token = job.claim_token
    lease_generation = job.lease_generation
    event = compute_schemas.BuildCompleteEvent(
        build_id=build_id,
        analysis_id=analysis_id,
        emitted_at=datetime.now(UTC),
        elapsed_ms=12,
        total_steps=0,
        tabs_built=1,
        results=[],
        duration_ms=12,
    )

    response = await WorkerRuntimeServicer().PersistBuildEvent(
        worker_runtime_pb2.WorkerPersistBuildEventRequest(
            namespace='default',
            build_id=build_id,
            job_id=job.id,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_generation=lease_generation,
            build_event=compute_pb2.BuildEvent(
                namespace='default',
                context=compute_pb2.BuildEventContext(
                    build_id=build_id,
                    analysis_id=analysis_id,
                    emitted_at=datetime_to_timestamp(event.emitted_at),
                ),
                completed=compute_pb2.BuildTerminalEvent(
                    progress=event.progress,
                    elapsed_ms=event.elapsed_ms,
                    total_steps=event.total_steps,
                    tabs_built=event.tabs_built,
                    duration_ms=event.duration_ms,
                ),
            ),
        ),
        context,
    )

    assert response.sequence == 1
    run = build_runs_service.get_build_run(test_db_session, build_id)
    assert run is not None
    assert run.status == BuildRunStatus.COMPLETED

    build_jobs_service.mark_job_cancelled(test_db_session, job.id)
    stale = await WorkerRuntimeServicer().PersistBuildEvent(
        worker_runtime_pb2.WorkerPersistBuildEventRequest(
            namespace='default',
            build_id=build_id,
            job_id=job.id,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_generation=lease_generation,
            build_event=compute_pb2.BuildEvent(
                namespace='default',
                context=compute_pb2.BuildEventContext(
                    build_id=build_id,
                    analysis_id=analysis_id,
                    emitted_at=datetime_to_timestamp(datetime.now(UTC)),
                ),
                completed=compute_pb2.BuildTerminalEvent(
                    progress=1,
                    elapsed_ms=13,
                    total_steps=0,
                    tabs_built=1,
                    duration_ms=13,
                ),
            ),
        ),
        context,
    )
    assert not stale.HasField('sequence')


@pytest.mark.asyncio
async def test_internal_worker_grpc_starts_build_run_and_returns_payload(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    database_session_state = threading.local()
    original_run_db = backend_grpc_server.run_db
    original_get_db = backend_grpc_server.get_db
    original_pipeline_parser = backend_grpc_server.analysis_pipeline_from_payload

    def tracked_run_db(function, *args, **kwargs):
        database_session_state.active = True
        try:
            return original_run_db(function, *args, **kwargs)
        finally:
            database_session_state.active = False

    def tracked_get_db():
        session_gen = original_get_db()
        session = next(session_gen)
        database_session_state.active = True
        try:
            yield session
        finally:
            database_session_state.active = False
            backend_grpc_server.close_rpc_session(session_gen)

    def parse_pipeline_without_database_session(payload: dict[str, object]):
        assert not getattr(database_session_state, 'active', False)
        return original_pipeline_parser(payload)

    monkeypatch.setattr(backend_grpc_server, 'run_db', tracked_run_db)
    monkeypatch.setattr(backend_grpc_server, 'get_db', tracked_get_db)
    monkeypatch.setattr(backend_grpc_server, 'analysis_pipeline_from_payload', parse_pipeline_without_database_session)
    build_id = str(uuid.uuid4())
    worker_id = f'local-worker:{uuid.uuid4()}'
    analysis_id = str(uuid.uuid4())
    build_runs_service.create_build_run(
        test_db_session,
        build_id=build_id,
        namespace='default',
        analysis_id=analysis_id,
        analysis_name='Start gRPC boundary test',
        request_json={
            'analysis_pipeline': {
                'analysis_id': analysis_id,
                'tabs': [
                    {
                        'id': 'tab-1',
                        'datasource': {
                            'id': 'datasource-1',
                            'analysis_tab_id': 'tab-1',
                            'source_type': 'schedule',
                            'config': {'branch': 'main'},
                        },
                        'output': {'result_id': 'result-1', 'filename': 'result.parquet', 'format': 'parquet'},
                        'steps': [],
                    }
                ],
            },
            'tab_id': 'tab-1',
        },
        starter_json={'triggered_by': 'test'},
        resource_config_json={'max_threads': 4, 'max_memory_mb': 1024, 'streaming_chunk_size': 500},
        status=BuildRunStatus.QUEUED,
        current_kind=EngineRunKind.BUILD.value,
        created_at=datetime.now(UTC),
    )
    build_jobs_service.create_job(test_db_session, build_id=build_id, namespace='default')
    job = build_jobs_service.claim_next_job(test_db_session, worker_id=worker_id)
    assert job is not None
    assert job.claim_token is not None

    response = await WorkerRuntimeServicer().StartBuildRun(
        worker_runtime_pb2.WorkerStartBuildRunRequest(
            namespace='default',
            build_id=build_id,
            job_id=job.id,
            worker_id=worker_id,
            claim_token=job.claim_token,
            lease_generation=job.lease_generation,
        ),
        context,
    )

    assert response.HasField('run')
    assert response.run.id == build_id
    assert response.run.analysis_id == analysis_id
    assert response.run.analysis_pipeline.analysis_id == analysis_id
    assert response.run.analysis_pipeline.tabs[0].datasource.source_type == enums_pb2.DATA_SOURCE_TYPE_SCHEDULE
    assert response.run.tab_id == 'tab-1'
    assert response.run.current_kind == enums_pb2.ENGINE_RUN_KIND_BUILD
    assert response.run.build_starter.triggered_by == 'test'
    assert response.run.build_resource_config.max_threads == 4
    assert response.run.build_resource_config.max_memory_mb == 1024
    assert response.run.build_resource_config.streaming_chunk_size == 500
    run = build_runs_service.get_build_run(test_db_session, build_id)
    assert run is not None
    assert run.status == BuildRunStatus.RUNNING
    assert run.execution_generation == job.lease_generation
    assert run.current_kind == EngineRunKind.BUILD.value


@pytest.mark.asyncio
async def test_internal_worker_grpc_lists_and_finalizes_datasource_delete(test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    datasource_id = str(uuid.uuid4())
    test_db_session.add(
        DataSource(
            id=datasource_id,
            name='Pending delete datasource',
            source_type=DataSourceType.FILE.value,
            config={'file_path': 's3://external-bucket/source.csv', 'file_type': 'csv'},
            is_hidden=True,
            is_pending_delete=True,
            created_at=datetime.now(UTC),
            delete_requested_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()
    servicer = WorkerRuntimeServicer()

    response = await servicer.ListPendingDatasourceDeletes(common_pb2.EmptyRequest(namespace='default'), context)
    assert (datasource_id, 'default') in {(item.datasource_id, item.namespace) for item in response.deletes}

    finalized = await servicer.FinalizeDatasourceDelete(
        worker_runtime_pb2.WorkerFinalizeDatasourceDeleteRequest(namespace='default', datasource_id=datasource_id),
        context,
    )
    assert finalized.deleted is True
    test_db_session.expire_all()
    assert test_db_session.get(DataSource, datasource_id) is None
