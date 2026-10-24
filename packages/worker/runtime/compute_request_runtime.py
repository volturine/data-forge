from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any, cast

from google.protobuf import json_format, message

from dataforge_protocol import compute_pb2, datasource_pb2, enums_pb2, errors_pb2
from datasources import execution as datasource_execution
from operations.step_converter import analysis_pipeline_to_execution_payload
from runtime import compute_service as service
from runtime.compute_manager import (
    COMPUTE_WORKER_ADMISSION_PRIORITY_DATASOURCE,
    COMPUTE_WORKER_ADMISSION_PRIORITY_INTERACTIVE,
    COMPUTE_WORKER_ADMISSION_PRIORITY_LIFECYCLE,
    ComputeWorkerCapacityFull,
    ProcessManager,
)
from runtime.compute_request_context import reset_compute_request_id, set_compute_request_id
from runtime.config import settings
from runtime.domain.compute import schemas as compute_schemas
from runtime.domain.compute_requests.live import ComputeRequestWake, request_hub
from runtime.domain.domain_enums import domain_token
from runtime.exceptions import AppError, StaleComputeInputError, status_for_app_error
from runtime.executors import run_compute_in_thread, run_control_in_thread, run_shutdown_in_thread
from runtime.json_values import dict_to_struct
from runtime.namespace import reset_namespace, set_namespace_context
from runtime.object_store import object_store_url, upload_bytes
from runtime.worker_runtime import NamespaceRecovery, RuntimeNamespaceDirectory
from runtime.worker_runtime_client import (
    BackendWorkerRpcError,
    ComputeWorkerRunFinalization,
    DatasourceMetadata,
    WorkerRuntimeClient,
    async_client_from_env,
    client_from_env,
    compute_worker_status_result_proto,
    reset_datasource_metadata_snapshot,
    set_datasource_metadata_snapshot,
)

logger = logging.getLogger(__name__)


def _safe_engine_error_message(value: object) -> str:
    message = str(value)
    message = re.sub(r"(?i)(postgres(?:ql)?://)[^/@\s]+@", r"\1[REDACTED]@", message)
    message = re.sub(r"(?i)(password|secret|token|access[_-]?key)(\s*[=:]\s*)\S+", r"\1\2[REDACTED]", message)
    return message[:300]


# ``COMPUTE_WORKERS`` is enforced by ProcessManager admission. Per-RID slots
# serialize requests that reuse an existing compute worker.
_COMPUTE_WORKERS = max(1, settings.compute_workers)
# One dispatcher fills bounded async work slots instead of making every slot
# independently poll and scan namespaces.
_COMPUTE_REQUEST_RECOVERY_SECONDS = max(
    5.0,
    float(settings.runtime_reconciliation_poll_interval_seconds),
)
# Spread lease RPCs while keeping disconnected engine work bounded to ten seconds.
_COMPUTE_REQUEST_LEASE_RENEWAL_MAX_SECONDS = 10.0
_COMPUTE_WORKER_CAPACITY_RACE_TIMEOUT_SECONDS = 2.0
# Claims are short database transactions. A small refill batch avoids turning
# every parked execution slot into a concurrent database poller.
_COMPUTE_REQUEST_CLAIM_MAX_WORKERS = min(_COMPUTE_WORKERS, 4)
_TERMINAL_RPC_TIMEOUT_SECONDS = 15.0
_TERMINAL_PUBLISH_BACKOFF_SECONDS = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)
_DATASOURCE_REQUEST_KINDS = {
    enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
    enums_pb2.COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE,
    enums_pb2.COMPUTE_REQUEST_KIND_CREATE_ICEBERG_DATASOURCE,
    enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE,
    enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
    enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS,
    enums_pb2.COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS,
    enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_PREFLIGHT,
}
COMPUTE_WORKER_SHUTDOWN_REQUEST_KINDS = frozenset({enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE})
COMPUTE_WORKER_LIFECYCLE_REQUEST_KINDS = frozenset(
    {
        enums_pb2.COMPUTE_REQUEST_KIND_SPAWN_ENGINE,
        enums_pb2.COMPUTE_REQUEST_KIND_CONFIGURE_ENGINE,
    }
)
ALL_REQUEST_KINDS = (
    frozenset(_DATASOURCE_REQUEST_KINDS)
    | COMPUTE_WORKER_SHUTDOWN_REQUEST_KINDS
    | COMPUTE_WORKER_LIFECYCLE_REQUEST_KINDS
    | frozenset(
        {
            enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA,
            enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT,
            enums_pb2.COMPUTE_REQUEST_KIND_DOWNLOAD,
            enums_pb2.COMPUTE_REQUEST_KIND_EXPORT,
        }
    )
)
ACTIVE_REQUEST_KINDS = ALL_REQUEST_KINDS - COMPUTE_WORKER_SHUTDOWN_REQUEST_KINDS


def worker_runtime_client() -> WorkerRuntimeClient:
    return client_from_env()


def compute_request_worker_count() -> int:
    return _COMPUTE_WORKERS


def compute_request_claim_worker_count() -> int:
    return _COMPUTE_REQUEST_CLAIM_MAX_WORKERS


def _compute_request_kind_name(kind: enums_pb2.ComputeRequestKind) -> str:
    enum_name = enums_pb2.ComputeRequestKind.Name(kind)
    return enum_name.removeprefix("COMPUTE_REQUEST_KIND_").lower()


def _freeze_claimed_input_metadata(
    client: WorkerRuntimeClient,
    claimed: ClaimedComputeRequest,
) -> dict[tuple[str, str], DatasourceMetadata]:
    snapshot: dict[tuple[str, str], DatasourceMetadata] = {}
    for expected in claimed.command_envelope.command.input_revisions:
        key = (claimed.namespace, expected.datasource_id)
        if key in snapshot:
            raise ValueError(f"Compute request {claimed.id} contains duplicate datasource revision entries")
        metadata = client.datasource_metadata(namespace=claimed.namespace, datasource_id=expected.datasource_id)
        # A datasource can disappear between staging and claim. Preserve
        # its user-facing not-found result; a present datasource with a
        # changed revision is stale.
        if metadata.found and metadata.revision != expected.revision:
            raise StaleComputeInputError(
                expected.datasource_id,
                expected_revision=int(expected.revision),
                actual_revision=metadata.revision,
            )
        snapshot[key] = metadata
    return snapshot


def _engine_admission_priority(
    kind: enums_pb2.ComputeRequestKind,
    identity: compute_pb2.ComputeWorkerIdentity | None,
) -> int:
    if identity is not None and identity.scope == enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW:
        return COMPUTE_WORKER_ADMISSION_PRIORITY_DATASOURCE
    if kind in COMPUTE_WORKER_LIFECYCLE_REQUEST_KINDS:
        return COMPUTE_WORKER_ADMISSION_PRIORITY_LIFECYCLE
    return COMPUTE_WORKER_ADMISSION_PRIORITY_INTERACTIVE


async def _wait_after_engine_capacity_race(manager: ProcessManager) -> None:
    """Back off after execution loses a slot reserved by admission.

    ``spawn_compute_worker`` is intentionally non-blocking. A lifecycle/prewarm
    operation can take the last slot after admission returns, so the request
    must rejoin the capacity wait path. The old immediate ``continue`` made
    this a hot loop that repeatedly consumed the execution/control budget.
    The bounded wait also covers the cross-process advisory-slot case, where
    a different manager cannot directly wake this process's local condition.
    """
    await manager.wait_for_capacity(timeout_seconds=_COMPUTE_WORKER_CAPACITY_RACE_TIMEOUT_SECONDS)


@dataclass(frozen=True)
class ClaimedComputeRequest:
    id: str
    namespace: str
    kind: enums_pb2.ComputeRequestKind
    command_envelope: compute_pb2.ComputeCommandEnvelope
    worker_id: str
    claim_token: str
    lease_generation: int
    lease_ttl_seconds: float
    lease_deadline_monotonic: float | None = None
    command_hash: str | None = None


class ComputeRequestLeaseLost(RuntimeError):
    pass


def _lease_renewal_delay(lease_ttl_seconds: float, request_id: str | None = None) -> float:
    """Spread renewals deterministically while keeping them well inside expiry."""
    base_delay = min(max(lease_ttl_seconds, 0.0) / 3, _COMPUTE_REQUEST_LEASE_RENEWAL_MAX_SECONDS)
    if request_id is None or base_delay <= 0:
        return base_delay
    digest = hashlib.sha256(request_id.encode()).digest()
    phase = int.from_bytes(digest[:4], "big") / (2**32 - 1)
    return base_delay * (0.5 + phase * 0.5)


async def next_compute_request(
    worker_id: str,
    *,
    allowed_kinds: frozenset[enums_pb2.ComputeRequestKind] = ALL_REQUEST_KINDS,
    namespace: str,
) -> ClaimedComputeRequest | None:
    claim_started = time.monotonic()
    client = await async_client_from_env()
    claimed = await client.claim_compute_request_async(
        worker_id=worker_id,
        allowed_kinds=allowed_kinds,
        namespace=namespace,
    )
    if claimed is None:
        return None
    return ClaimedComputeRequest(
        id=claimed.id,
        namespace=claimed.namespace,
        kind=claimed.kind,
        command_envelope=claimed.command_envelope,
        worker_id=claimed.worker_id,
        claim_token=claimed.claim_token,
        lease_generation=claimed.lease_generation,
        lease_ttl_seconds=claimed.lease_ttl_seconds,
        lease_deadline_monotonic=(
            claimed.lease_deadline_monotonic if claimed.lease_deadline_monotonic is not None else claim_started + claimed.lease_ttl_seconds
        ),
        command_hash=claimed.command_hash,
    )


async def compute_request_loop(
    stop_event: asyncio.Event,
    *,
    worker_id: str,
    manager: ProcessManager,
    allowed_kinds: frozenset[enums_pb2.ComputeRequestKind] = ALL_REQUEST_KINDS,
    claim_semaphore: asyncio.Semaphore | None = None,
    poll_for_work: bool = True,
    max_concurrency: int | None = None,
    namespace_directory: RuntimeNamespaceDirectory,
    recovery: NamespaceRecovery | None = None,
    on_progress: Callable[[], None] | None = None,
) -> None:
    """Dispatch request wakes and bounded recovery work into the shared budget."""
    concurrency = max(1, max_concurrency or compute_request_worker_count())
    last_seen = request_hub.version()
    pending_wakes: deque[ComputeRequestWake] = deque()
    recent_request_ids: deque[str] = deque(maxlen=4096)
    seen_request_ids: set[str] = set()
    drain_namespaces: set[str] = set()
    drain_permits: dict[str, int] = {}
    in_flight: dict[asyncio.Task[bool], ComputeRequestWake] = {}
    recovery_tasks: set[asyncio.Task[None]] = set()
    recovery_limit = min(4, max(1, concurrency))
    recovery_semaphore = asyncio.Semaphore(recovery_limit)

    def enqueue_drain(namespace: str, *, permits: int = 1) -> None:
        drain_namespaces.add(namespace)
        drain_permits[namespace] = drain_permits.get(namespace, 0) + permits
        pending_wakes.extend(ComputeRequestWake(request_id=None, namespace=namespace, kind=None) for _ in range(permits))

    def namespace_has_work(namespace: str) -> bool:
        return any(wake.namespace == namespace for wake in pending_wakes) or any(wake.namespace == namespace for wake in in_flight.values())

    def enqueue_notifications(version: int) -> None:
        nonlocal last_seen
        if version == last_seen:
            return
        for wake in request_hub.payloads_since(last_seen):
            if not isinstance(wake, ComputeRequestWake) or not wake.namespace:
                continue
            if wake.request_id is None:
                if wake.kind is None:
                    enqueue_drain(wake.namespace)
                continue
            if wake.kind not in allowed_kinds:
                continue
            if wake.request_id in seen_request_ids:
                continue
            if len(recent_request_ids) == recent_request_ids.maxlen:
                seen_request_ids.discard(recent_request_ids.popleft())
            recent_request_ids.append(wake.request_id)
            seen_request_ids.add(wake.request_id)
            pending_wakes.append(wake)
            drain_namespaces.add(wake.namespace)
        last_seen = version

    async def run_one(namespace: str) -> bool:
        try:
            return await _run_once(
                worker_id=worker_id,
                manager=manager,
                allowed_kinds=allowed_kinds,
                namespace=namespace,
                claim_semaphore=claim_semaphore,
            )
        except Exception as exc:
            logger.warning("Compute request loop iteration failed; will retry: %s", exc)
            return False

    def schedule_recovery(namespace: str) -> None:
        if recovery is None:
            return

        async def reconcile() -> None:
            async with recovery_semaphore:
                await recovery.reconcile(namespace)

        task = asyncio.create_task(reconcile())
        recovery_tasks.add(task)
        task.add_done_callback(recovery_tasks.discard)

    try:
        next_recovery_poll = 0.0
        while not stop_event.is_set():
            if on_progress is not None:
                on_progress()
            enqueue_notifications(request_hub.version())
            if not pending_wakes and not in_flight:
                for namespace in tuple(drain_namespaces):
                    if drain_permits.get(namespace, 0) == 0:
                        enqueue_drain(namespace)
            while len(in_flight) < concurrency:
                if pending_wakes:
                    wake = pending_wakes.popleft()
                elif poll_for_work and time.monotonic() >= next_recovery_poll:
                    recovered_namespaces = await namespace_directory.snapshot()
                    next_recovery_poll = time.monotonic() + _COMPUTE_REQUEST_RECOVERY_SECONDS
                    if not recovered_namespaces:
                        break
                    for recovered_namespace in recovered_namespaces:
                        if namespace_has_work(recovered_namespace) or drain_permits.get(recovered_namespace, 0):
                            continue
                        # Recover each pending namespace in this pass. A single
                        # namespace per poll made missed-wake recovery scale as
                        # five seconds times the number of active tenants.
                        enqueue_drain(recovered_namespace)
                        schedule_recovery(recovered_namespace)
                    if not pending_wakes:
                        continue
                    wake = pending_wakes.popleft()
                else:
                    break
                task = asyncio.create_task(run_one(wake.namespace))
                in_flight[task] = wake

            wait_task = asyncio.create_task(request_hub.wait(last_seen))
            stop_task = asyncio.create_task(stop_event.wait())
            wait_tasks: set[asyncio.Task[Any]] = {wait_task, stop_task, *in_flight}
            poll_task = None
            if poll_for_work:
                poll_delay = max(0.0, next_recovery_poll - time.monotonic())
                poll_task = asyncio.create_task(asyncio.sleep(poll_delay))
                wait_tasks.add(poll_task)
            done, pending = await asyncio.wait(wait_tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                if task not in in_flight:
                    task.cancel()
            control_pending = [task for task in pending if task not in in_flight]
            if control_pending:
                await asyncio.gather(*control_pending, return_exceptions=True)
            if stop_task in done:
                return

            for task in tuple(in_flight):
                if task not in done:
                    continue
                wake = in_flight.pop(task)
                if wake.request_id is None:
                    if task.result():
                        pending_wakes.append(wake)
                    else:
                        remaining = drain_permits[wake.namespace] - 1
                        if remaining:
                            drain_permits[wake.namespace] = remaining
                        else:
                            drain_permits.pop(wake.namespace, None)
                            if not namespace_has_work(wake.namespace):
                                drain_namespaces.discard(wake.namespace)

            if wait_task in done:
                with contextlib.suppress(asyncio.CancelledError):
                    value = await wait_task
                    if isinstance(value, int):
                        enqueue_notifications(value)
            if poll_task is not None and poll_task in done:
                next_recovery_poll = 0.0
    finally:
        for recovery_task in recovery_tasks:
            recovery_task.cancel()
        if recovery_tasks:
            await asyncio.gather(*recovery_tasks, return_exceptions=True)
        tasks = list(in_flight)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def _run_once(
    *,
    worker_id: str,
    manager: ProcessManager,
    allowed_kinds: frozenset[enums_pb2.ComputeRequestKind] = ALL_REQUEST_KINDS,
    namespace: str,
    claim_semaphore: asyncio.Semaphore | None = None,
) -> bool:
    async def claim_once() -> ClaimedComputeRequest | None:
        async with claim_semaphore or contextlib.nullcontext():
            return await next_compute_request(
                worker_id,
                allowed_kinds=allowed_kinds,
                namespace=namespace,
            )

    claimed = await claim_once()
    if claimed is None:
        return False
    try:
        identity = _compute_worker_identity_for_claimed(claimed)
    except ValueError as exc:
        # A malformed command cannot become valid on retry. Fail it now rather
        # than letting the lease expire until the attempt budget is exhausted.
        await run_control_in_thread(_reject_malformed_request, claimed, exc)
        return True
    logger.debug(
        "Compute request claimed request_id=%s lease_generation=%s coordinator_generation=%s kind=%s namespace=%s resource_id=%s command_hash=%s",
        claimed.id,
        claimed.lease_generation,
        os.environ.get("RUNTIME_COORDINATOR_GENERATION", "-"),
        _compute_request_kind_name(claimed.kind),
        claimed.namespace,
        identity.resource_id if identity is not None else "-",
        claimed.command_hash or "-",
    )
    try:
        await _execute_request(claimed, manager)
    except ComputeRequestLeaseLost as exc:
        logger.warning(
            "Compute request lease was lost before execution completed request_id=%s namespace=%s reason=%s",
            claimed.id,
            claimed.namespace,
            exc,
        )
    return True


async def _execute_request(
    claimed: ClaimedComputeRequest,
    manager: ProcessManager,
) -> None:
    """Admit worker capacity before taking a compute-pool thread.

    Capacity wait is a real queue: the request sits with **no compute-pool
    thread** until a slot is free or the engine already exists for reuse. The
    exact-RID job slot serializes work on a reused engine before execution.
    Exact duplicate commands share one durable request and completed response
    in Postgres before they reach this gate.
    """
    identity = _compute_worker_identity_for_claimed(claimed)
    renewal_stop = asyncio.Event()
    lease_confirmed = asyncio.Event()
    renewal = asyncio.create_task(_renew_compute_lease(claimed, stop_event=renewal_stop, lease_confirmed=lease_confirmed))
    confirmation_wait = asyncio.create_task(lease_confirmed.wait())
    terminal_publication_started = threading.Event()
    terminal_published = threading.Event()
    try:
        # A claim starts with a short delivery lease. Do not start a cold
        # engine or wait for manager admission until the coordinator confirms
        # the first renewal to the longer execution lease.
        confirmation_done, _pending = await asyncio.wait(
            {renewal, confirmation_wait},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if renewal in confirmation_done:
            await renewal
            raise RuntimeError(f"Compute request {claimed.id} renewal stopped before its first confirmation")
        await confirmation_wait

        while True:
            owns_admission = False
            request_reserved = False
            engine_job_task: asyncio.Task[None] | None = None
            engine_job_acquired = False
            admission_task: asyncio.Task[bool] | None = None
            execution = None
            retry_after_capacity_race = False
            try:
                loop = asyncio.get_running_loop()
                admission_started = loop.time()
                if identity is None:

                    async def admit_without_engine() -> bool:
                        return False

                    admission = admit_without_engine
                else:
                    admission = partial(
                        manager.await_engine_request_admission,
                        identity,
                        namespace=claimed.namespace,
                        priority=_engine_admission_priority(claimed.kind, identity),
                    )

                # Do not take a compute thread until the manager has admitted
                # the exact worker identity and its per-RID slot.
                async def acquire_admission(admit=admission) -> bool:
                    nonlocal owns_admission, request_reserved
                    owns_admission = await admit()
                    if identity is not None and not owns_admission:
                        request_reserved = True
                    return owns_admission

                admission_task = asyncio.create_task(acquire_admission())
                admission_done, _admission_pending = await asyncio.wait(
                    {admission_task, renewal},
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=5.0,
                )
                if not admission_done:
                    logger.warning(
                        "Compute request still waiting for worker admission request_id=%s lease_generation=%s coordinator_generation=%s "
                        "worker_id=%s kind=%s namespace=%s resource_id=%s command_hash=%s wait_ms=%.1f",
                        claimed.id,
                        claimed.lease_generation,
                        os.environ.get("RUNTIME_COORDINATOR_GENERATION", "-"),
                        claimed.worker_id,
                        _compute_request_kind_name(claimed.kind),
                        claimed.namespace,
                        identity.resource_id if identity is not None else "-",
                        claimed.command_hash or "-",
                        (loop.time() - admission_started) * 1000,
                    )
                    admission_done, _admission_pending = await asyncio.wait(
                        {admission_task, renewal},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                if renewal in admission_done:
                    # A capacity waiter must not become a stale runner after its
                    # durable claim expires.  ProcessManager also removes the
                    # waiter and returns any admission when this task is
                    # cancelled below.
                    await renewal
                    raise RuntimeError(f"Compute request {claimed.id} lease renewal stopped unexpectedly")
                owns_admission = admission_task.result()
                manager_wait_ms = (loop.time() - admission_started) * 1000
                if identity is not None and owns_admission:
                    manager.reserve_engine_request(identity, namespace=claimed.namespace)
                    request_reserved = True

                if identity is not None:

                    async def acquire_engine_job_slot() -> None:
                        nonlocal engine_job_acquired
                        await manager.await_engine_job_slot(identity, namespace=claimed.namespace)
                        engine_job_acquired = True

                    engine_job_task = asyncio.create_task(acquire_engine_job_slot())
                    engine_job_done, _engine_job_pending = await asyncio.wait(
                        {engine_job_task, renewal},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if renewal in engine_job_done:
                        await renewal
                        raise RuntimeError(f"Compute request {claimed.id} lease renewal stopped unexpectedly")
                    await engine_job_task
                    engine_job_acquired = True

                if manager_wait_ms >= 250:
                    log_admission = logger.warning if manager_wait_ms >= 5000 else logger.info
                    log_admission(
                        "Compute request admitted request_id=%s lease_generation=%s coordinator_generation=%s worker_id=%s "
                        "kind=%s namespace=%s resource_id=%s command_hash=%s manager_wait_ms=%.1f",
                        claimed.id,
                        claimed.lease_generation,
                        os.environ.get("RUNTIME_COORDINATOR_GENERATION", "-"),
                        claimed.worker_id,
                        _compute_request_kind_name(claimed.kind),
                        claimed.namespace,
                        identity.resource_id if identity is not None else "-",
                        claimed.command_hash or "-",
                        manager_wait_ms,
                    )

                async def run_execution() -> None:
                    def execute_and_record_terminal(request: ClaimedComputeRequest, process_manager: ProcessManager) -> None:
                        if _execute_request_sync(
                            request,
                            process_manager,
                            terminal_publication_started,
                        ):
                            terminal_published.set()

                    # Shutdown must run even when every compute thread is busy, and
                    # must not occupy the control threads that release admissions.
                    executor = run_shutdown_in_thread if claimed.kind in COMPUTE_WORKER_SHUTDOWN_REQUEST_KINDS else run_compute_in_thread
                    await executor(execute_and_record_terminal, claimed, manager)

                execution = asyncio.create_task(run_execution())
                execution_done, _execution_pending = await asyncio.wait({execution, renewal}, return_when=asyncio.FIRST_COMPLETED)
                if execution in execution_done:
                    try:
                        await execution
                    except ComputeWorkerCapacityFull:
                        if renewal not in execution_done:
                            # Direct lifecycle work may have claimed the slot
                            # between reuse admission and execution. Rejoin the
                            # FIFO queue after releasing this admission and
                            # RID slot.
                            retry_after_capacity_race = True
                    else:
                        # Durable completion is authoritative if renewal and
                        # execution finish in the same event-loop turn. A late
                        # renewal failure must not cancel already-published work.
                        return
                if renewal in execution_done:
                    try:
                        await renewal
                    except ComputeRequestLeaseLost:
                        # A terminal RPC can commit before its executor future
                        # is delivered to this event loop. If a publication
                        # already started, let its fenced result settle before
                        # treating the lost renewal as a stale claim.
                        if terminal_publication_started.is_set():
                            await asyncio.gather(execution, return_exceptions=True)
                        if terminal_published.is_set():
                            return
                        if identity is not None:
                            with contextlib.suppress(Exception):
                                await run_control_in_thread(
                                    manager.cancel_engine_job,
                                    identity,
                                    namespace=claimed.namespace,
                                    job_id=claimed.id,
                                )
                            with contextlib.suppress(Exception):
                                await run_shutdown_in_thread(
                                    manager.shutdown_compute_worker_after_request_lease_loss,
                                    identity,
                                    namespace=claimed.namespace,
                                )
                        await asyncio.gather(execution, return_exceptions=True)
                        raise
                    raise RuntimeError(f"Compute request {claimed.id} lease renewal stopped unexpectedly")
            finally:
                if execution is not None and not execution.done():
                    execution.cancel()
                    # run_compute_in_thread does not finish cancellation until
                    # the underlying thread has stopped. Keep its manager
                    # admission and RID slot until that happens.
                    await asyncio.gather(execution, return_exceptions=True)
                if admission_task is not None and not admission_task.done():
                    admission_task.cancel()
                if admission_task is not None:
                    await asyncio.gather(admission_task, return_exceptions=True)
                if engine_job_task is not None and not engine_job_task.done():
                    engine_job_task.cancel()
                if engine_job_task is not None:
                    await asyncio.gather(engine_job_task, return_exceptions=True)
                if identity is not None and engine_job_acquired:
                    manager.release_engine_job_slot(identity, namespace=claimed.namespace)
                if identity is not None and request_reserved:
                    manager.release_engine_request(identity, namespace=claimed.namespace)
                if identity is not None and admission_task is not None:
                    await run_control_in_thread(
                        manager.release_spawn_admission,
                        identity,
                        namespace=claimed.namespace,
                        owned=owns_admission,
                    )
            if retry_after_capacity_race:
                await _wait_after_engine_capacity_race(manager)
                continue
    finally:
        if not confirmation_wait.done():
            confirmation_wait.cancel()
        await asyncio.gather(confirmation_wait, return_exceptions=True)
        renewal_stop.set()
        await asyncio.gather(renewal, return_exceptions=True)


async def _renew_compute_lease(
    claimed: ClaimedComputeRequest,
    *,
    stop_event: asyncio.Event,
    lease_confirmed: asyncio.Event | None = None,
) -> None:
    clock = asyncio.get_running_loop().time
    deadline = claimed.lease_deadline_monotonic if claimed.lease_deadline_monotonic is not None else clock() + claimed.lease_ttl_seconds
    remaining_at_start = deadline - clock()
    if remaining_at_start <= 0:
        raise ComputeRequestLeaseLost(f"Compute request {claimed.id} lease expired before execution could start")
    # A retired request is the cancellation signal for work whose browser
    # disconnected or whose engine is being torn down. The old ``ttl / 3``
    # interval made the default five-minute lease observable as a 100-second
    # cancellation delay, leaving a stale engine job occupying capacity.
    # Extend the short claim-delivery lease before cold startup or admission
    # waits can consume it. Later renewals are spread across the longer work
    # lease, so this one immediate heartbeat does not create a poll loop.
    delay = 0.0
    first_renewal_started = clock()
    client = await async_client_from_env()
    while True:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
            return
        except TimeoutError:
            pass
        remaining = deadline - clock()
        if remaining <= 0:
            raise ComputeRequestLeaseLost(f"Compute request {claimed.id} lease renewal was not confirmed before expiry")
        renewal_started = clock()
        try:
            lease_ttl_seconds = await client.renew_compute_request_lease(
                request_id=claimed.id,
                namespace=claimed.namespace,
                worker_id=claimed.worker_id,
                claim_token=claimed.claim_token,
                lease_generation=claimed.lease_generation,
                timeout_seconds=remaining,
            )
        except Exception as exc:
            remaining = deadline - clock()
            if remaining <= 0:
                raise ComputeRequestLeaseLost(f"Compute request {claimed.id} lease renewal was not confirmed before expiry") from exc
            delay = _lease_renewal_delay(min(remaining, 3.0), claimed.id)
            logger.warning("Compute request %s lease renewal failed; retrying before confirmed expiry: %s", claimed.id, exc)
            continue
        if lease_ttl_seconds is None:
            raise ComputeRequestLeaseLost(f"Compute request {claimed.id} lease is no longer active")
        deadline = renewal_started + lease_ttl_seconds
        if lease_confirmed is not None and not lease_confirmed.is_set():
            lease_confirmed.set()
            first_renewal_ms = (clock() - first_renewal_started) * 1000
            if first_renewal_ms >= 500:
                logger.warning(
                    "Compute request initial lease renewal confirmed request_id=%s namespace=%s "
                    "renewal_ms=%.1f remaining_delivery_lease_ms=%.1f work_lease_ttl_seconds=%s",
                    claimed.id,
                    claimed.namespace,
                    first_renewal_ms,
                    max(0.0, (deadline - clock()) * 1000),
                    lease_ttl_seconds,
                )
        delay = _lease_renewal_delay(lease_ttl_seconds, claimed.id)


def _datasource_result_from_payload(kind: enums_pb2.ComputeRequestKind, payload: dict[str, object]) -> datasource_pb2.DatasourceResult:
    result = datasource_pb2.DatasourceResult()
    if "error" in payload:
        result.error.CopyFrom(json_format.ParseDict(payload, datasource_pb2.DatasourceErrorResult()))
        return result
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA:
        result.schema.CopyFrom(json_format.ParseDict(payload, datasource_pb2.SchemaInfo()))
        return result
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS:
        result.column_stats.CopyFrom(json_format.ParseDict(payload, datasource_pb2.ColumnStatsResult()))
        return result
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS:
        proto_payload = dict(payload)
        raw_schema_diff = proto_payload.get("schema_diff")
        if isinstance(raw_schema_diff, list):
            converted = []
            for raw_diff in raw_schema_diff:
                if not isinstance(raw_diff, dict):
                    converted.append(raw_diff)
                    continue
                diff = dict(raw_diff)
                status = diff.get("status")
                if isinstance(status, str):
                    from runtime.protocol_mapping import enum_to_proto_value

                    diff["status"] = enum_to_proto_value("SCHEMA_DIFF_STATUS", status)
                converted.append(diff)
            proto_payload["schema_diff"] = converted
        result.snapshot_compare.CopyFrom(json_format.ParseDict(proto_payload, datasource_pb2.SnapshotCompareResult()))
        return result
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_PREFLIGHT:
        result.preflight.CopyFrom(json_format.ParseDict(payload, datasource_pb2.DatasourcePreflightResult()))
        return result
    raise ValueError(f"Unsupported datasource response kind: {_compute_request_kind_name(kind)}")


def _datasource_engine_job(
    manager: ProcessManager,
    claimed: ClaimedComputeRequest,
    kind: str,
    payload: dict[str, object],
) -> dict[str, object]:
    from runtime.compute_utils import await_compute_worker_result
    from runtime.exceptions import PipelineExecutionError

    identity = _compute_worker_identity_for_claimed(claimed)
    if identity is None:
        raise ValueError("Datasource work requires an exact RID engine identity")
    with manager.acquire_engine(identity) as engine:
        job_id = engine.datasource_job(kind, payload)
        result = await_compute_worker_result(engine, job_id=job_id)
    if result.get("error"):
        error_kind = result.get("error_kind", "-")
        error_details = result.get("error_details")
        error_type = error_details.get("exception_type", "-") if isinstance(error_details, dict) else "-"
        error_message = _safe_engine_error_message(result["error"]) if error_kind == "value_error" else "-"
        logger.error(
            "Datasource engine job failed request_id=%s resource_id=%s kind=%s error_kind=%s error_type=%s error_message=%s",
            claimed.id,
            identity.resource_id,
            kind,
            error_kind,
            error_type,
            error_message,
        )
        raise PipelineExecutionError(
            "Datasource computation failed",
            details={"error_kind": result.get("error_kind"), "resource_id": identity.resource_id},
        )
    data = result.get("data")
    if not isinstance(data, dict):
        raise ValueError("Datasource engine result must contain an object")
    return data


def _publish_staged_datasource(
    client: WorkerRuntimeClient,
    manager: ProcessManager,
    claimed: ClaimedComputeRequest,
    command: datasource_pb2.DatasourceCommand,
) -> datasource_pb2.DatasourceResult:
    from datetime import UTC, datetime

    from runtime.domain.datasource.source_types import DataSourceType
    from runtime.protocol_mapping import proto_value_to_enum_name, schema_info_proto, struct_to_dict

    operation = command.WhichOneof("command")
    create = operation != "ingest"
    metadata = None
    request: (
        datasource_pb2.CreateFileDatasourceCommand
        | datasource_pb2.CreateDatabaseDatasourceCommand
        | datasource_pb2.CreateIcebergDatasourceCommand
        | datasource_pb2.IngestDatasourceCommand
    )
    source: dict[str, object]
    branch: object
    if operation == "create_file":
        request = command.create_file
        source = {
            "source_type": "file",
            "file_path": request.file_path,
            "file_type": proto_value_to_enum_name(enums_pb2.DataSourceFileType, "DATA_SOURCE_FILE_TYPE", request.file_type),
            "options": struct_to_dict(request.options),
        }
        if request.HasField("csv_options"):
            source["csv_options"] = _message_to_service_payload(request.csv_options)
        for field in ("sheet_name", "start_row", "start_col", "end_col", "end_row", "has_header", "table_name", "named_range", "cell_range"):
            if request.HasField(field):
                source[field] = getattr(request, field)
        branch = "master"
    elif operation == "create_database":
        request = command.create_database
        source = {"source_type": "database", "connection_string": request.connection_string, "query": request.query}
        branch = request.branch
    elif operation == "create_iceberg":
        request = command.create_iceberg
        source = struct_to_dict(request.source)
        branch = request.branch
    elif operation == "ingest":
        metadata = datasource_execution.require_metadata(client, namespace=claimed.namespace, datasource_id=command.ingest.datasource_id)
        source, _source_type = datasource_execution.external_source(metadata)
        branch = (metadata.config or {}).get("branch") or source.get("branch")
        request = command.ingest
    else:
        raise ValueError("Datasource staging requires a create or ingest command")
    if not isinstance(branch, str) or not branch.strip():
        raise ValueError("Datasource branch is required")
    branch = branch.strip()
    source_type_value = source.get("source_type")
    if not isinstance(source_type_value, str):
        raise ValueError("Datasource source type is required")
    source_type = DataSourceType.require(source_type_value)
    if not source_type.supports_external_ingestion:
        raise ValueError("Datasource source is not ingestable")
    datasource_id = claimed.id if create else command.ingest.datasource_id
    staging_id = f"{datasource_id}__claim_{claimed.claim_token.replace('-', '_')}"
    target_path = object_store_url("clean", staging_id, branch, namespace=claimed.namespace)
    # Reuse the datasource's published table identity so earlier snapshots
    # remain available. New datasources use clean.<datasource_id>; reingests
    # keep the metadata_path already recorded on the datasource.
    table_path = datasource_execution.published_datasource_table_path(
        datasource_id,
        branch,
        namespace=claimed.namespace,
        existing_config=metadata.config if metadata is not None else None,
    )
    manifest_url = object_store_url(
        "runtime-staging", "datasource-stage", claimed.id, str(claimed.lease_generation), "manifest.json", namespace=claimed.namespace
    )
    client.register_datasource_stage(
        namespace=claimed.namespace,
        datasource_id=datasource_id,
        compute_request_id=claimed.id,
        worker_id=claimed.worker_id,
        claim_token=claimed.claim_token,
        lease_generation=claimed.lease_generation,
        prefix_url=target_path,
        manifest_url=manifest_url,
        catalog_identifier=f"clean.{target_path.rstrip('/').split('/')[-2]}",
    )
    run_id = datasource_execution.create_ingest_run(
        client,
        namespace=claimed.namespace,
        datasource_id=datasource_id,
        source_type=source_type,
        branch=branch,
        mode="initial_ingest" if create else "manual_ingest",
        triggered_by="manual",
    )
    started = time.monotonic()
    try:
        manifest = _datasource_engine_job(
            manager,
            claimed,
            "datasource_stage",
            {"source_config": source, "table_path": target_path, "manifest_url": manifest_url},
        )
        schema_info = schema_info_proto(manifest)
        client.update_compute_worker_run(namespace=claimed.namespace, run_id=run_id, fields={"current_step": "Importing staged batches", "progress": 0.7})
        table, published_table_path = datasource_execution.import_staged_parquet_files(
            manifest, staged_prefix=target_path, table_path=table_path, database_url=settings.database_url
        )
        if create:
            config: dict[str, object] = {}
        else:
            assert metadata is not None
            config = dict(metadata.config or {})
        config.update(datasource_execution.build_iceberg_config(published_table_path, branch, source_config=source))
        if not create:
            for key in ("time_travel_snapshot_id", "time_travel_snapshot_timestamp_ms", "time_travel_ui"):
                config.pop(key, None)
        datasource_execution.set_snapshot_metadata(config, table)
        # The snapshot added by this ingest references the staged parquet files
        # under the claim prefix. Record it in the published config so the
        # publication settles the cleanup intent: the prefix is part of table
        # history for as long as any snapshot references it.
        config["ingest"] = {
            **({"ingested_at": datetime.now(UTC).replace(tzinfo=None).isoformat()} if not create else {}),
            "claim_prefix": target_path,
        }
        if create:
            assert isinstance(
                request,
                (datasource_pb2.CreateFileDatasourceCommand, datasource_pb2.CreateDatabaseDatasourceCommand, datasource_pb2.CreateIcebergDatasourceCommand),
            )
            record = client.publish_datasource_create(
                namespace=claimed.namespace,
                datasource_id=datasource_id,
                name=request.name,
                description=request.description if request.HasField("description") else None,
                source_type="iceberg",
                config=config,
                schema_info=schema_info,
                compute_request_id=claimed.id,
                worker_id=claimed.worker_id,
                claim_token=claimed.claim_token,
                lease_generation=claimed.lease_generation,
                owner_id=request.owner_id if request.HasField("owner_id") else None,
            )
        else:
            assert metadata is not None and metadata.revision is not None
            record = client.publish_datasource_ingest(
                namespace=claimed.namespace,
                datasource_id=datasource_id,
                config=config,
                expected_revision=int(metadata.revision),
                schema_info=schema_info,
                worker_id=claimed.worker_id,
                claim_token=claimed.claim_token,
                lease_generation=claimed.lease_generation,
                compute_request_id=claimed.id,
            )
        datasource_execution.complete_ingest_run(
            client,
            namespace=claimed.namespace,
            run_id=run_id,
            started=started,
            record=record,
            original_source_type=source_type,
            metadata_path=published_table_path,
        )
        result = datasource_pb2.DatasourceResult()
        result.datasource.CopyFrom(record)
        return result
    except BackendWorkerRpcError as exc:
        datasource_execution.fail_ingest_run(client, namespace=claimed.namespace, run_id=run_id, started=started, exc=exc)
        if exc.error_code == "FAILED_PRECONDITION":
            raise datasource_execution.DatasourcePublicationClaimLost("Datasource publication claim is no longer active") from exc
        raise
    except Exception as exc:
        datasource_execution.fail_ingest_run(client, namespace=claimed.namespace, run_id=run_id, started=started, exc=exc)
        raise


def _execute_datasource_command(
    client: WorkerRuntimeClient,
    claimed: ClaimedComputeRequest,
    manager: ProcessManager,
    command: datasource_pb2.DatasourceCommand,
) -> datasource_pb2.DatasourceResult:
    from runtime.protocol_mapping import schema_info_payload, schema_info_proto, struct_to_dict

    operation = command.WhichOneof("command")
    if operation in {"create_file", "create_database", "create_iceberg", "ingest"}:
        return _publish_staged_datasource(client, manager, claimed, command)
    if operation == "preflight":
        request = command.preflight
        action = {
            enums_pb2.DATASOURCE_PREFLIGHT_ACTION_INITIAL: "excel_preflight",
            enums_pb2.DATASOURCE_PREFLIGHT_ACTION_PREVIEW: "excel_preview",
            enums_pb2.DATASOURCE_PREFLIGHT_ACTION_RESOLVE_SELECTION: "excel_resolve_selection",
        }[request.action]
        payload = _message_to_service_payload(request)
        result = _datasource_engine_job(manager, claimed, action, {"preflight": payload})
        return _datasource_result_from_payload(claimed.kind, result)
    if operation not in {"schema", "column_stats", "compare_iceberg_snapshots"}:
        raise ValueError("Unsupported datasource compute operation")
    request = getattr(command, operation)
    metadata = datasource_execution.require_metadata(client, namespace=claimed.namespace, datasource_id=request.datasource_id)
    if metadata.revision is None:
        raise ValueError("Datasource snapshot is missing its revision")
    payload = {
        "datasource_metadata": {
            "id": metadata.id,
            "name": metadata.name,
            "source_type": metadata.source_type,
            "config": metadata.config,
            "revision": metadata.revision,
            "is_hidden": metadata.is_hidden,
            "description": metadata.description,
            "column_descriptions": metadata.column_descriptions or {},
        }
    }
    if operation == "schema":
        sheet_name = request.sheet_name if request.HasField("sheet_name") else None
        if metadata.schema_cache and sheet_name is None and not request.refresh:
            try:
                cached = schema_info_proto(metadata.schema_cache)
            except ValueError:
                cached = None
            if cached is not None and cached.columns:
                datasource_execution.attach_column_descriptions(metadata, cached)
                return _datasource_result_from_payload(claimed.kind, schema_info_payload(cached))
        payload["sheet_name"] = sheet_name
        schema = schema_info_proto(_datasource_engine_job(manager, claimed, "datasource_schema", payload))
        if sheet_name is None:
            schema = client.publish_datasource_schema_cache(
                namespace=claimed.namespace,
                datasource_id=request.datasource_id,
                expected_revision=int(metadata.revision),
                schema_info=schema,
                compute_request_id=claimed.id,
                worker_id=claimed.worker_id,
                claim_token=claimed.claim_token,
                lease_generation=claimed.lease_generation,
            )
        datasource_execution.attach_column_descriptions(metadata, schema)
        return _datasource_result_from_payload(claimed.kind, schema_info_payload(schema))
    if operation == "column_stats":
        payload.update(
            {
                "column_name": request.column_name,
                "use_sample": request.use_sample,
                "sample_size": request.sample_size,
                "datasource_config": struct_to_dict(request.datasource_config),
            }
        )
        result = _datasource_engine_job(manager, claimed, "datasource_column_stats", payload)
    else:
        payload.update({"snapshot_a": request.snapshot_a, "snapshot_b": request.snapshot_b, "row_limit": request.row_limit})
        result = _datasource_engine_job(manager, claimed, "datasource_snapshot_compare", payload)
    return _datasource_result_from_payload(claimed.kind, result)


def _execute_request_sync(
    claimed: ClaimedComputeRequest,
    manager: ProcessManager,
    terminal_publication_started: threading.Event | None = None,
) -> bool:
    client = worker_runtime_client()
    namespace_token = set_namespace_context(claimed.namespace)
    request_token = set_compute_request_id(claimed.id)

    def publish_complete(
        *,
        response: compute_pb2.ComputeResponse,
        artifact_path: str | None = None,
        artifact_name: str | None = None,
        artifact_content_type: str | None = None,
        compute_worker_run_finalization: ComputeWorkerRunFinalization | None = None,
    ) -> None:
        if terminal_publication_started is not None:
            terminal_publication_started.set()
        _complete_request(
            client,
            claimed,
            response=response,
            artifact_path=artifact_path,
            artifact_name=artifact_name,
            artifact_content_type=artifact_content_type,
            compute_worker_run_finalization=compute_worker_run_finalization,
        )

    metadata_snapshot_token = None
    try:
        metadata_snapshot_token = set_datasource_metadata_snapshot(_freeze_claimed_input_metadata(client, claimed))
        if claimed.kind in _DATASOURCE_REQUEST_KINDS:
            if claimed.command_envelope.command.WhichOneof("command") != "datasource":
                raise ValueError("compute command envelope must contain datasource")
            datasource_command = claimed.command_envelope.command.datasource
            try:
                result = _execute_datasource_command(client, claimed, manager, datasource_command)
            except datasource_execution.DatasourceNotFound as exc:
                payload: dict[str, object] = {"error": "datasource_not_found", "message": str(exc)}
                result = _datasource_result_from_payload(claimed.kind, payload)
            except datasource_execution.DatasourcePublicationClaimLost as exc:
                raise ComputeRequestLeaseLost(str(exc) or "Datasource publication claim is no longer active") from exc
            except BackendWorkerRpcError as exc:
                if exc.error_code == "FAILED_PRECONDITION":
                    raise ComputeRequestLeaseLost("Datasource publication claim is no longer active") from exc
                raise
            source_artifact = None
            if datasource_command.WhichOneof("command") == "preflight":
                preflight = datasource_command.preflight
                if preflight.action == enums_pb2.DATASOURCE_PREFLIGHT_ACTION_INITIAL and preflight.delete_source:
                    source_artifact = preflight.source_path
            publish_complete(
                response=compute_pb2.ComputeResponse(datasource=result),
                artifact_path=source_artifact,
                artifact_name="preflight-source" if source_artifact else None,
                artifact_content_type="application/vnd.dataforge.preflight-source" if source_artifact else None,
            )
            return True

        if claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW:
            preview_request = cast(compute_pb2.StepPreviewCommand, _compute_command_from_claimed(claimed, "preview"))
            analysis_pipeline = analysis_pipeline_to_execution_payload(preview_request.analysis_pipeline)
            request_json = _step_request_json(preview_request, analysis_pipeline)
            preview_started = time.monotonic()
            preview_outcome = service.preview_step(
                manager=manager,
                target_step_id=preview_request.target_step_id,
                analysis_pipeline=analysis_pipeline,
                row_limit=preview_request.row_limit,
                page=preview_request.page,
                analysis_id=preview_request.analysis_id if preview_request.HasField("analysis_id") else None,
                compute_worker_identity=preview_request.engine_identity if preview_request.HasField("engine_identity") else None,
                resource_config=_resource_config_from_command(preview_request),
                tab_id=preview_request.tab_id if preview_request.HasField("tab_id") else None,
                request_json=request_json,
                request_id=claimed.id,
                command_hash=claimed.command_hash,
            )
            response_ready = time.monotonic()
            preview_response_envelope = _preview_result(preview_outcome.response)
            response_encoded = time.monotonic()
            logger.info(
                "Compute preview response ready request_id=%s worker_id=%s service_ms=%.1f encode_ms=%.1f",
                claimed.id,
                claimed.worker_id,
                (response_ready - preview_started) * 1000,
                (response_encoded - response_ready) * 1000,
            )
            publication_started = time.monotonic()
            publish_complete(
                response=preview_response_envelope,
                compute_worker_run_finalization=preview_outcome.compute_worker_run_finalization,
            )
            logger.info(
                "Compute preview response published request_id=%s worker_id=%s publish_ms=%.1f",
                claimed.id,
                claimed.worker_id,
                (time.monotonic() - publication_started) * 1000,
            )
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA:
            schema_request = cast(compute_pb2.StepSchemaCommand, _compute_command_from_claimed(claimed, "schema"))
            if not schema_request.HasField("analysis_id"):
                raise ValueError("analysis_id is required")
            schema_response = service.get_step_schema(
                manager=manager,
                target_step_id=schema_request.target_step_id,
                analysis_id=schema_request.analysis_id,
                analysis_pipeline=analysis_pipeline_to_execution_payload(schema_request.analysis_pipeline),
                tab_id=schema_request.tab_id if schema_request.HasField("tab_id") else None,
            )
            publish_complete(
                response=compute_pb2.ComputeResponse(
                    schema=compute_pb2.StepSchemaResult(
                        step_id=schema_response.step_id, columns=schema_response.columns, column_types=schema_response.column_types
                    )
                )
            )
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT:
            row_count_request = cast(compute_pb2.StepRowCountCommand, _compute_command_from_claimed(claimed, "row_count"))
            if not row_count_request.HasField("analysis_id"):
                raise ValueError("analysis_id is required")
            analysis_pipeline = analysis_pipeline_to_execution_payload(row_count_request.analysis_pipeline)
            request_json = _step_request_json(row_count_request, analysis_pipeline)
            row_count_response = service.get_step_row_count(
                manager=manager,
                target_step_id=row_count_request.target_step_id,
                analysis_id=row_count_request.analysis_id,
                analysis_pipeline=analysis_pipeline,
                tab_id=row_count_request.tab_id if row_count_request.HasField("tab_id") else None,
                request_json=request_json,
            )
            publish_complete(
                response=compute_pb2.ComputeResponse(
                    row_count=compute_pb2.StepRowCountResult(step_id=row_count_response.step_id, row_count=row_count_response.row_count)
                )
            )
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_DOWNLOAD:
            download_request = cast(compute_pb2.DownloadCommand, _compute_command_from_claimed(claimed, "download"))
            file_bytes, filename, content_type = service.download_step(
                manager=manager,
                target_step_id=download_request.target_step_id,
                analysis_pipeline=analysis_pipeline_to_execution_payload(download_request.analysis_pipeline),
                export_format=domain_token("ExportFormat", download_request.format),
                filename=download_request.filename,
                analysis_id=download_request.analysis_id if download_request.HasField("analysis_id") else None,
                tab_id=download_request.tab_id if download_request.HasField("tab_id") else None,
            )
            artifact_path = object_store_url("runtime-artifacts", claimed.id, filename)
            upload_bytes(file_bytes, artifact_path)
            publish_complete(
                response=compute_pb2.ComputeResponse(ack=compute_pb2.ComputeAckResult(success=True)),
                artifact_path=artifact_path,
                artifact_name=filename,
                artifact_content_type=content_type,
            )
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_EXPORT:
            export_request = cast(compute_pb2.ExportCommand, _compute_command_from_claimed(claimed, "export"))
            export_operation_result = service.export_data(
                manager=manager,
                target_step_id=export_request.target_step_id,
                analysis_pipeline=analysis_pipeline_to_execution_payload(export_request.analysis_pipeline),
                filename=export_request.filename,
                iceberg_options=_message_to_service_payload(export_request.iceberg_options) if export_request.HasField("iceberg_options") else None,
                analysis_id=export_request.analysis_id if export_request.HasField("analysis_id") else None,
                tab_id=export_request.tab_id if export_request.HasField("tab_id") else None,
                result_id=export_request.result_id if export_request.HasField("result_id") else None,
            )
            export_result = compute_pb2.ExportResult(
                success=True,
                filename=export_operation_result.datasource_name,
                format=export_request.format,
                destination=export_request.destination,
                message=f"Created datasource {export_operation_result.datasource_name}",
                datasource_id=export_operation_result.datasource_id,
                datasource_name=export_operation_result.datasource_name,
            )
            publish_complete(response=compute_pb2.ComputeResponse(export=export_result))
        elif claimed.kind in {enums_pb2.COMPUTE_REQUEST_KIND_SPAWN_ENGINE, enums_pb2.COMPUTE_REQUEST_KIND_CONFIGURE_ENGINE}:
            is_configure = claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_CONFIGURE_ENGINE
            field_name = "configure_engine" if is_configure else "spawn_engine"
            command = cast(compute_pb2.ComputeWorkerLifecycleCommand, _compute_command_from_claimed(claimed, field_name))
            identity = command.engine_identity
            resource_config = _resource_config_from_command(command)
            if is_configure:
                if resource_config is None:
                    raise ValueError("resource_config is required")
                logger.info("Restarting engine for %s with new config: %s", identity.resource_id, resource_config)
            # spawn_compute_worker transfers the replaced engine's capacity to its replacement atomically.
            manager.spawn_compute_worker(identity, resource_config=resource_config)
            publish_complete(
                response=compute_pb2.ComputeResponse(engine_status=compute_worker_status_result_proto(manager.get_compute_worker_status(identity)))
            )
        elif claimed.kind == enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE:
            command = cast(compute_pb2.ComputeWorkerLifecycleCommand, _compute_command_from_claimed(claimed, "shutdown_engine"))
            identity = command.engine_identity
            # Shutdown is idempotent: capacity eviction, idle reaping, or a prior
            # crash may already have removed the container. Missing engines are a
            # successful terminal state, matching reconciliation rules.
            manager.shutdown_compute_worker(identity)
            publish_complete(response=compute_pb2.ComputeResponse(ack=compute_pb2.ComputeAckResult(success=True)))
        else:
            raise ValueError(f"Unsupported compute request kind: {_compute_request_kind_name(claimed.kind)}")
        return True
    except ComputeRequestLeaseLost, ComputeWorkerCapacityFull:
        # A stale claim or replaced publication fence drains without failing the request as an infrastructure error.
        # Capacity-full propagates so the async runner can park without holding a pool thread.
        raise
    except Exception as exc:
        error_to_report = exc
        compute_worker_run_finalization: ComputeWorkerRunFinalization | None = None
        if isinstance(exc, service.PreviewExecutionError):
            error_to_report = exc.error
            compute_worker_run_finalization = exc.compute_worker_run_finalization
        error = _error_result(error_to_report)
        status_code = error.status_code if error.HasField("status_code") else None
        try:
            if terminal_publication_started is not None:
                terminal_publication_started.set()
            _fail_request_with_retry(
                client,
                claimed,
                error_message=_error_message(error_to_report),
                error=error,
                compute_worker_run_finalization=compute_worker_run_finalization,
            )
        except BackendWorkerRpcError as publish_exc:
            if publish_exc.status_code == 412:
                logger.info("Compute request %s ended after its lease was retired", claimed.id)
                return False
            raise
        if status_code is not None and status_code >= 500:
            logger.error("Compute request %s failed: %s", claimed.id, error_to_report, exc_info=True)
        elif status_code is not None and status_code >= 400:
            logger.info("Compute request %s rejected: %s", claimed.id, error_to_report)
        else:
            logger.warning("Compute request %s failed: %s", claimed.id, error_to_report)
        return True
    finally:
        if metadata_snapshot_token is not None:
            reset_datasource_metadata_snapshot(metadata_snapshot_token)
        reset_compute_request_id(request_token)
        reset_namespace(namespace_token)
        client.close()


_STATELESS_COMMAND_FIELDS = {
    enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA: "schema",
    enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT: "row_count",
    enums_pb2.COMPUTE_REQUEST_KIND_DOWNLOAD: "download",
    enums_pb2.COMPUTE_REQUEST_KIND_EXPORT: "export",
}


def _stateless_compute_worker_identity_for_command(command: message.Message) -> compute_pb2.ComputeWorkerIdentity:
    # The identity needs only analysis_id, so the pipeline is not decoded to read it.
    return service.default_stateless_compute_worker_identity(cast(Any, command).analysis_pipeline.analysis_id)


def _compute_worker_identity_for_claimed(claimed: ClaimedComputeRequest) -> compute_pb2.ComputeWorkerIdentity | None:
    """Identity that will need a capacity slot, or None if no Polars engine is required."""
    kind = claimed.kind
    if kind in _DATASOURCE_REQUEST_KINDS:
        command = claimed.command_envelope.command.datasource
        command_name = command.WhichOneof("command")
        if command_name is None:
            raise ValueError("datasource compute command is missing its operation")
        if command_name in {"create_file", "create_database", "create_iceberg"}:
            resource_id = claimed.id
        elif command_name == "preflight":
            resource_id = command.preflight.preflight_id
        else:
            resource_id = getattr(command, command_name).datasource_id
        return compute_pb2.ComputeWorkerIdentity(
            scope=enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW,
            reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
            datasource_id=resource_id,
            resource_id=resource_id,
        )
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE:
        # Shutdown frees capacity; never waits for a slot.
        return None
    if kind in {
        enums_pb2.COMPUTE_REQUEST_KIND_SPAWN_ENGINE,
        enums_pb2.COMPUTE_REQUEST_KIND_CONFIGURE_ENGINE,
    }:
        field = "spawn_engine" if kind == enums_pb2.COMPUTE_REQUEST_KIND_SPAWN_ENGINE else "configure_engine"
        return cast(compute_pb2.ComputeWorkerLifecycleCommand, _compute_command_from_claimed(claimed, field)).engine_identity
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW:
        preview = cast(compute_pb2.StepPreviewCommand, _compute_command_from_claimed(claimed, "preview"))
        if preview.HasField("engine_identity"):
            return preview.engine_identity
        return _stateless_compute_worker_identity_for_command(preview)
    if kind in _STATELESS_COMMAND_FIELDS:
        return _stateless_compute_worker_identity_for_command(_compute_command_from_claimed(claimed, _STATELESS_COMMAND_FIELDS[kind]))
    return None


def _compute_command_from_claimed(claimed: ClaimedComputeRequest, field_name: str) -> message.Message:
    command = claimed.command_envelope.command
    if command.WhichOneof("command") != field_name:
        raise ValueError(f"compute command envelope must contain {field_name}")
    return cast(message.Message, getattr(command, field_name))


def _message_to_service_payload(value: message.Message) -> dict[str, object]:
    decoded = json_format.MessageToDict(
        value,
        preserving_proto_field_name=True,
        use_integers_for_enums=True,
    )
    if not isinstance(decoded, dict):
        raise ValueError(f"{value.DESCRIPTOR.full_name} must decode to an object")
    return cast(dict[str, object], decoded)


def _step_request_json(command: message.Message, analysis_pipeline: dict[str, object]) -> dict[str, object]:
    request_json = _message_to_service_payload(command)
    if "analysis_pipeline" in request_json:
        request_json["analysis_pipeline"] = analysis_pipeline
    return request_json


def _resource_config_from_command(
    command: compute_pb2.StepPreviewCommand | compute_pb2.ComputeWorkerLifecycleCommand,
) -> dict[str, object] | None:
    if not command.HasField("resource_config"):
        return None
    config = command.resource_config
    return {field: getattr(config, field) for field in ("max_threads", "max_memory_mb", "streaming_chunk_size") if config.HasField(field)}


def _preview_result(value: compute_schemas.StepPreviewResponse) -> compute_pb2.ComputeResponse:
    result = compute_pb2.StepPreviewResult(
        step_id=value.step_id,
        columns=value.columns,
        column_types=value.column_types or {},
        rows=[dict_to_struct(row) for row in value.data],
        total_rows=value.total_rows,
        page=value.page,
        page_size=value.page_size,
    )
    if value.metadata is not None:
        result.metadata.CopyFrom(dict_to_struct(value.metadata))
    return compute_pb2.ComputeResponse(preview=result)


def _retry_terminal_publication(claimed: ClaimedComputeRequest, publication: str, publish: Callable[[], None]) -> None:
    for attempt, delay in enumerate((*_TERMINAL_PUBLISH_BACKOFF_SECONDS, None), start=1):
        try:
            publish()
            return
        except BackendWorkerRpcError as exc:
            if exc.error_code not in {"UNAVAILABLE", "DEADLINE_EXCEEDED"} or delay is None:
                raise
            logger.warning("Compute request %s %s publication failed (attempt %s); retrying: %s", claimed.id, publication, attempt, exc)
            time.sleep(delay)


def _complete_request(
    client: WorkerRuntimeClient,
    claimed: ClaimedComputeRequest,
    *,
    response: compute_pb2.ComputeResponse,
    artifact_path: str | None = None,
    artifact_name: str | None = None,
    artifact_content_type: str | None = None,
    compute_worker_run_finalization: ComputeWorkerRunFinalization | None = None,
) -> None:
    _retry_terminal_publication(
        claimed,
        "completion",
        partial(
            client.complete_compute_request,
            namespace=claimed.namespace,
            request_id=claimed.id,
            kind=claimed.kind,
            worker_id=claimed.worker_id,
            claim_token=claimed.claim_token,
            lease_generation=claimed.lease_generation,
            response=response,
            artifact_path=artifact_path,
            artifact_name=artifact_name,
            artifact_content_type=artifact_content_type,
            compute_worker_run_finalization=compute_worker_run_finalization,
            timeout_seconds=_TERMINAL_RPC_TIMEOUT_SECONDS,
        ),
    )


def _reject_malformed_request(claimed: ClaimedComputeRequest, exc: ValueError) -> None:
    client = worker_runtime_client()
    try:
        _fail_request_with_retry(client, claimed, error_message=_error_message(exc), error=_error_result(exc))
    except BackendWorkerRpcError as publish_exc:
        if publish_exc.status_code != 412:
            raise
    finally:
        client.close()
    logger.info("Compute request %s rejected as malformed: %s", claimed.id, exc)


def _fail_request_with_retry(
    client: WorkerRuntimeClient,
    claimed: ClaimedComputeRequest,
    *,
    error_message: str,
    error: compute_pb2.ComputeErrorResult,
    compute_worker_run_finalization: ComputeWorkerRunFinalization | None = None,
) -> None:
    _retry_terminal_publication(
        claimed,
        "failure",
        partial(
            client.fail_compute_request,
            namespace=claimed.namespace,
            request_id=claimed.id,
            kind=claimed.kind,
            worker_id=claimed.worker_id,
            claim_token=claimed.claim_token,
            lease_generation=claimed.lease_generation,
            error_message=error_message,
            error=error,
            compute_worker_run_finalization=compute_worker_run_finalization,
            timeout_seconds=_TERMINAL_RPC_TIMEOUT_SECONDS,
        ),
    )


def _error_message(exc: Exception) -> str:
    if isinstance(exc, BackendWorkerRpcError):
        return exc.error
    if isinstance(exc, AppError):
        return exc.message
    return str(exc)


def _error_result(exc: Exception) -> compute_pb2.ComputeErrorResult:
    if isinstance(exc, BackendWorkerRpcError):
        result = compute_pb2.ComputeErrorResult(error=exc.error, status_code=exc.status_code)
        if exc.error_code is not None:
            protocol_error_code = f"ERROR_CODE_{exc.error_code}"
            if protocol_error_code in errors_pb2.ErrorCode.DESCRIPTOR.values_by_name:
                result.error_code = cast(errors_pb2.ErrorCode, errors_pb2.ErrorCode.Value(protocol_error_code))
        if exc.details:
            result.details.CopyFrom(dict_to_struct(exc.details))
        return result
    if isinstance(exc, AppError):
        result = compute_pb2.ComputeErrorResult(
            error=exc.message,
            status_code=status_for_app_error(exc),
            error_code=cast(errors_pb2.ErrorCode, exc.error_code_value),
        )
        if exc.details:
            result.details.CopyFrom(dict_to_struct(exc.details))
        return result
    if isinstance(exc, ValueError):
        return compute_pb2.ComputeErrorResult(error=str(exc), status_code=400)
    return compute_pb2.ComputeErrorResult(error="An internal error occurred", status_code=500)
