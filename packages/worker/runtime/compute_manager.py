from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

from dataforge_protocol import compute_pb2, enums_pb2
from runtime.compute_request_context import get_compute_request_id
from runtime.config import settings
from runtime.docker_compute_worker import DockerComputeWorker, reconcile_deployment_containers
from runtime.domain.compute.base import ComputeWorker, ComputeWorkerStatusInfo
from runtime.domain.compute.schemas import ComputeWorkerStatus
from runtime.executors import run_control_in_thread
from runtime.namespace import get_namespace, reset_namespace, set_namespace_context

logger = logging.getLogger(__name__)

_RESOURCE_KEYS = frozenset({"max_threads", "max_memory_mb", "streaming_chunk_size"})
_COMPUTE_WORKER_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS = 30.0
_DOCKER_RECONCILE_INTERVAL_SECONDS = 60.0
_SLOW_ENGINE_ACQUISITION_SECONDS = 5.0

# Admission classes are scheduled round-robin. Datasource work can still be
# shared by many tabs, while interactive and lifecycle/build work cannot be
# starved by a sustained burst in another class.
COMPUTE_WORKER_ADMISSION_PRIORITY_DATASOURCE = 0
COMPUTE_WORKER_ADMISSION_PRIORITY_INTERACTIVE = 1
COMPUTE_WORKER_ADMISSION_PRIORITY_LIFECYCLE = 2
_COMPUTE_WORKER_ADMISSION_PRIORITIES = (
    COMPUTE_WORKER_ADMISSION_PRIORITY_DATASOURCE,
    COMPUTE_WORKER_ADMISSION_PRIORITY_INTERACTIVE,
    COMPUTE_WORKER_ADMISSION_PRIORITY_LIFECYCLE,
)


ComputeWorkerIdentity = compute_pb2.ComputeWorkerIdentity
ComputeWorkerFactory = Callable[[ComputeWorkerIdentity, dict | None], ComputeWorker]
ComputeWorkerSnapshotListener = Callable[[list[ComputeWorkerStatusInfo]], None]


class ComputeWorkerCapacityFull(Exception):
    """No free engine slot at the moment of claim (lost race after admission).

    Callers must not hold a compute runner while waiting. Prefer
    :meth:`ProcessManager.await_spawn_admission` *before* taking a runner so
    capacity wait happens with zero runner threads.
    """


@dataclass(frozen=True, slots=True)
class ComputeWorkerIdentityKey:
    namespace: str
    scope: int
    reuse_policy: int
    resource_id: str


@dataclass(frozen=True, slots=True)
class _WarmWorkerCleanup:
    engine: ComputeWorker
    identity: ComputeWorkerIdentityKey
    request_id: str
    attempts: int = 0


_WARM_WORKER_CLEANUP_RETRY_BASE_SECONDS = 0.25
_WARM_WORKER_CLEANUP_RETRY_MAX_SECONDS = 4.0


@dataclass(slots=True)
class _CapacityAdmission:
    evicted: tuple[ComputeWorkerIdentityKey, ComputeWorkerInfo, ComputeWorkerIdentity] | None = None
    eviction_event: threading.Event | None = None
    # Reserve one warm candidate explicitly so a burst cannot all observe the
    # same non-empty pool and then claim it while they race to pop the pool.
    warm_claim: bool = False
    # True when this admission expects a new container process rather than a
    # ready warm worker. Used only to balance startup diagnostics.
    cold_start: bool = False
    # Once the compute runner takes ownership, request cancellation must not
    # return its capacity while the synchronous Docker start is still running.
    claimed: bool = False
    released: bool = False


@dataclass(slots=True)
class _SpawnWaiter:
    key: ComputeWorkerIdentityKey
    loop: asyncio.AbstractEventLoop
    future: asyncio.Future[bool]
    priority: int
    reserve_existing_request: bool = False
    owns_admission: bool = False
    reserved_existing_request: bool = False


@dataclass(slots=True)
class _EngineJobSlot:
    lock: asyncio.Lock
    loop: asyncio.AbstractEventLoop
    references: int = 0


def _compute_worker_identity_analysis_id(identity: ComputeWorkerIdentity) -> str | None:
    return identity.analysis_id if identity.HasField("analysis_id") else None


def _compute_worker_identity_datasource_id(identity: ComputeWorkerIdentity) -> str | None:
    return identity.datasource_id if identity.HasField("datasource_id") else None


def _compute_worker_identity_build_id(identity: ComputeWorkerIdentity) -> str | None:
    return identity.build_id if identity.HasField("build_id") else None


def _engine_scope_value(identity: ComputeWorkerIdentity) -> str:
    if identity.scope == enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW:
        return "datasource_preview"
    if identity.scope == enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE:
        return "analysis_interactive"
    if identity.scope == enums_pb2.COMPUTE_WORKER_SCOPE_BUILD:
        return "build"
    raise ValueError("engine identity scope is unspecified")


def _engine_reuse_policy_value(identity: ComputeWorkerIdentity) -> str:
    if identity.reuse_policy == enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED:
        return "shared"
    if identity.reuse_policy == enums_pb2.COMPUTE_WORKER_REUSE_POLICY_EXCLUSIVE:
        return "exclusive"
    raise ValueError("engine identity reuse policy is unspecified")


def _log_engine_acquisition(
    identity: ComputeWorkerIdentity,
    *,
    namespace: str,
    source: str,
    acquisition_ms: float,
    warm_health_ms: float = 0.0,
    warm_candidate_shutdown_wait_ms: float = 0.0,
    warm_bind_ms: float = 0.0,
    cold_start_ms: float = 0.0,
    warm_candidate_rejected: bool = False,
    lifecycle_wait_ms: float = 0.0,
    prior_engine_shutdown_ms: float = 0.0,
    idle_eviction_shutdown_ms: float = 0.0,
    process_alive_check_ms: float = 0.0,
    snapshot_publication_ms: float = 0.0,
) -> None:
    try:
        scope = _engine_scope_value(identity)
    except ValueError:
        scope = str(identity.scope)
    log_acquisition = logger.warning if acquisition_ms >= _SLOW_ENGINE_ACQUISITION_SECONDS * 1000 else logger.info
    log_acquisition(
        "Engine acquisition request_id=%s namespace=%s engine_scope=%s resource_id=%s source=%s "
        "acquisition_ms=%.1f warm_health_ms=%.1f warm_candidate_shutdown_wait_ms=%.1f "
        "warm_bind_ms=%.1f "
        "cold_start_ms=%.1f warm_candidate_rejected=%s "
        "lifecycle_wait_ms=%.1f prior_engine_shutdown_ms=%.1f idle_eviction_shutdown_ms=%.1f "
        "process_alive_check_ms=%.1f snapshot_publication_ms=%.1f",
        get_compute_request_id() or "-",
        namespace,
        scope,
        identity.resource_id,
        source,
        acquisition_ms,
        warm_health_ms,
        warm_candidate_shutdown_wait_ms,
        warm_bind_ms,
        cold_start_ms,
        warm_candidate_rejected,
        lifecycle_wait_ms,
        prior_engine_shutdown_ms,
        idle_eviction_shutdown_ms,
        process_alive_check_ms,
        snapshot_publication_ms,
    )


class ComputeWorkerInfo:
    """Tracks engine metadata for reuse, status, and eviction decisions."""

    def __init__(self, engine: ComputeWorker):
        self.engine = engine
        self.last_activity = datetime.now(UTC)
        self._last_snapshot_at = time.monotonic()
        self.current_build_id: str | None = None
        self.current_compute_worker_run_id: str | None = None
        self.active_reservations = 0

    def touch(self) -> None:
        self.last_activity = datetime.now(UTC)

    def activity_snapshot_due(self) -> bool:
        now = time.monotonic()
        if now - self._last_snapshot_at < _COMPUTE_WORKER_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS:
            return False
        self._last_snapshot_at = now
        return True

    def mark_snapshot_published(self) -> None:
        self._last_snapshot_at = time.monotonic()


class ProcessManager:
    def __init__(
        self,
        engine_factory: ComputeWorkerFactory | None = None,
        on_snapshot: ComputeWorkerSnapshotListener | None = None,
        *,
        warm_worker_factory: Callable[[], ComputeWorker] | None = None,
        supervisor_id: str = "worker",
        warm_worker_target: int | None = None,
        coordinator_generation: int | None = None,
        coordinator_guard: Callable[[], None] | None = None,
        reconcile_docker_containers: bool = True,
    ) -> None:
        self._engines: dict[ComputeWorkerIdentityKey, ComputeWorkerInfo] = {}
        self._engine_identities: dict[ComputeWorkerIdentityKey, ComputeWorkerIdentity] = {}
        self._engines_lock = threading.Lock()
        # The shared compute budget also caps active engine identities. Running
        # identities + in-flight starts count; unassigned warm workers are
        # outside this cap until claimed and bound to an identity.
        # Waiters park asynchronously and never hold compute runners.
        self._capacity_changed = threading.Condition(self._engines_lock)
        self._capacity_starts = 0
        self._capacity_reserved_stops: set[int] = set()
        # Diagnostic only: counts process boots, including warm-reserve boots.
        # Admission is governed by _capacity_starts and the configured budgets.
        self._cold_starts = 0
        self._warm_worker_target = settings.compute_warm_workers if warm_worker_target is None else warm_worker_target
        # Generic change waiters and FIFO spawn admissions park outside the
        # compute thread pool. A spawn admission reserves capacity before its
        # request is allowed to take a runner.
        self._capacity_waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Future[bool]]] = []
        self._spawn_waiters: deque[_SpawnWaiter] = deque()
        self._next_spawn_priority = COMPUTE_WORKER_ADMISSION_PRIORITY_DATASOURCE
        self._spawn_admissions: dict[ComputeWorkerIdentityKey, deque[_CapacityAdmission]] = {}
        self._engine_events: dict[ComputeWorkerIdentityKey, threading.Event] = {}
        # A request can be admitted because an engine already exists, then
        # wait briefly for an engine executor thread. Keep that identity out of
        # the eviction candidates during the gap; otherwise another request
        # can evict it and the admitted request will recreate it later.
        self._request_reservations: dict[ComputeWorkerIdentityKey, int] = {}
        # A physical engine executes one command at a time. Keep same-RID
        # requests queued before they consume the application-wide work permit
        # or a compute executor thread.
        self._engine_job_slots: dict[ComputeWorkerIdentityKey, _EngineJobSlot] = {}
        # Engines are created outside the manager lock. Keep in-flight starts
        # visible to Docker reconciliation so it cannot remove a container in
        # the small window between ``start()`` and registration in _engines.
        self._starting_engines: dict[int, ComputeWorker] = {}
        # A shutdown removes an engine from the active map before Docker work
        # completes. Keep that container protected until stop/remove returns.
        self._stopping_engines: dict[int, ComputeWorker] = {}
        # Rejected unassigned workers are outside active compute capacity, but
        # remain protected from Docker reconciliation until serial cleanup ends.
        self._stopping_warm_workers: dict[int, ComputeWorker] = {}
        self._warm_worker_cleanups: deque[_WarmWorkerCleanup] = deque()
        self._closed = False
        self._supervisor_id = supervisor_id
        self._coordinator_generation = coordinator_generation
        self._coordinator_guard = coordinator_guard
        self._uses_docker_runtime = engine_factory is None
        # Only the application-wide manager reconciles the Docker deployment.
        # Build lanes share this manager, so deployment reconciliation stays
        # a single bounded sweep rather than multiplying with queue workers.
        self._reconcile_docker_containers = reconcile_docker_containers
        self._user_engine_factory = engine_factory or (
            lambda identity, resource_config: DockerComputeWorker(
                identity,
                resource_config=resource_config,
                supervisor_id=self._supervisor_id,
                coordinator_generation=self._coordinator_generation,
                coordinator_guard=self._coordinator_guard,
            )
        )
        self._on_snapshot = on_snapshot
        self._idle_ttl_seconds = settings.engine_idle_ttl_seconds
        self._idle_reap_interval_seconds = settings.engine_idle_reap_interval_seconds
        logger.info(
            "Compute workers active_capacity=%s warm_workers=%s",
            settings.compute_workers,
            self._warm_worker_target,
        )
        self._warm_workers: deque[ComputeWorker] = deque()
        self._warm_worker_claims = 0
        # Warm workers start outside the manager lock. Reserve their slot
        # before Docker work so concurrent claim/replenish wakeups cannot
        # exceed the configured target.
        self._warm_worker_starts = 0
        self._reaper_stop = threading.Event()
        self._reaper_thread: threading.Thread | None = None
        if self._idle_ttl_seconds > 0:
            self._reaper_thread = threading.Thread(target=self._reap_idle_engines_loop, name="engine-idle-reaper", daemon=True)
            self._reaper_thread.start()
        self._warm_worker_factory = warm_worker_factory or (
            (
                lambda: DockerComputeWorker(
                    supervisor_id=self._supervisor_id,
                    coordinator_generation=self._coordinator_generation,
                    coordinator_guard=self._coordinator_guard,
                )
            )
            if self._uses_docker_runtime
            else None
        )
        self._warm_worker_replenish_trigger = threading.Event()
        self._warm_worker_replenisher_thread: threading.Thread | None = None
        if self._warm_worker_factory is not None and self._warm_worker_target > 0:
            self._warm_worker_replenisher_thread = threading.Thread(
                target=self._replenish_warm_workers_loop,
                name="warm-compute-worker-replenisher",
                daemon=True,
            )
            self._warm_worker_replenisher_thread.start()
            self._warm_worker_replenish_trigger.set()

    def wait_for_warm_workers_ready(self, *, timeout_seconds: float) -> bool:
        """Wait until the configured warm-worker reserve is available.

        The runtime worker row is the readiness signal used by the API and the
        E2E stack.  Registering that row before the asynchronous prewarm batch
        completes makes the first requests race container startup and turns a
        healthy-but-not-ready worker into long queue waits or false 503s.
        Keep the timeout bounded so a failed engine runtime does not prevent the
        manager from coming up and reporting the actual failure through normal
        request execution.
        """
        target = max(self._warm_worker_target, 0)
        if target == 0:
            return True

        deadline = time.monotonic() + max(timeout_seconds, 0.0)
        with self._capacity_changed:
            while len(self._warm_workers) < target and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._capacity_changed.wait(timeout=remaining)
            return len(self._warm_workers) >= target

    @property
    def warm_worker_count(self) -> int:
        with self._capacity_changed:
            return len(self._warm_workers)

    def _engine_factory(self, identity: ComputeWorkerIdentity, resource_config: dict | None = None) -> ComputeWorker:
        """Create an engine and wire capacity wakeups when its job slot frees."""
        engine = self._user_engine_factory(identity, resource_config)
        bind = getattr(engine, "bind_capacity_notifier", None)
        if callable(bind):
            bind(self.notify_capacity_changed)
        return engine

    def _track_starting_engine(self, engine: ComputeWorker) -> None:
        with self._capacity_changed:
            self._starting_engines[id(engine)] = engine

    def _untrack_starting_engine(self, engine: ComputeWorker) -> None:
        with self._capacity_changed:
            self._starting_engines.pop(id(engine), None)

    def _untrack_stopping_engine(self, engine: ComputeWorker) -> None:
        with self._capacity_changed:
            self._stopping_engines.pop(id(engine), None)
            self._capacity_reserved_stops.discard(id(engine))

    def _queue_rejected_warm_worker(self, engine: ComputeWorker, identity: ComputeWorkerIdentityKey) -> float:
        """Transfer a rejected reserve worker to the bounded serial cleanup lane."""
        started = time.perf_counter()
        with self._capacity_changed:
            self._starting_engines.pop(id(engine), None)
            self._stopping_warm_workers[id(engine)] = engine
            self._warm_worker_cleanups.append(_WarmWorkerCleanup(engine=engine, identity=identity, request_id=get_compute_request_id() or "-"))
            self._warm_worker_replenish_trigger.set()
            self._capacity_changed.notify_all()
        return (time.perf_counter() - started) * 1000

    def _cleanup_rejected_warm_worker(self, cleanup: _WarmWorkerCleanup) -> float:
        """Stop one rejected candidate; return a bounded retry delay on failure."""
        started = time.perf_counter()
        try:
            cleanup.engine.shutdown()
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            with self._capacity_changed:
                shutting_down = self._closed or self._reaper_stop.is_set()
                next_attempt = cleanup.attempts + 1
                if shutting_down:
                    # Do not keep shutdown_all() alive in an unbounded retry
                    # loop. Startup reconciliation owns any remaining labeled
                    # container after this final best-effort attempt.
                    self._stopping_warm_workers.pop(id(cleanup.engine), None)
                    self._capacity_changed.notify_all()
                else:
                    self._warm_worker_cleanups.appendleft(
                        _WarmWorkerCleanup(
                            engine=cleanup.engine,
                            identity=cleanup.identity,
                            request_id=cleanup.request_id,
                            attempts=next_attempt,
                        )
                    )
            log_cleanup_failure = logger.error if shutting_down else (logger.warning if next_attempt == 1 else logger.debug)
            log_cleanup_failure(
                "Rejected warm worker cleanup failed request_id=%s namespace=%s engine_scope=%s resource_id=%s duration_ms=%.1f attempt=%s outcome=%s",
                cleanup.request_id,
                cleanup.identity.namespace,
                enums_pb2.ComputeWorkerScope.Name(cleanup.identity.scope).removeprefix("COMPUTE_WORKER_SCOPE_").lower(),
                cleanup.identity.resource_id,
                duration_ms,
                next_attempt,
                "handed_to_startup_reconciliation" if shutting_down else "retrying_with_backoff",
                exc_info=True,
            )
            if shutting_down:
                return 0.0
            return min(
                _WARM_WORKER_CLEANUP_RETRY_BASE_SECONDS * (2 ** min(next_attempt - 1, 4)),
                _WARM_WORKER_CLEANUP_RETRY_MAX_SECONDS,
            )

        duration_ms = (time.perf_counter() - started) * 1000
        with self._capacity_changed:
            self._stopping_warm_workers.pop(id(cleanup.engine), None)
            self._capacity_changed.notify_all()
        log_cleanup_complete = logger.warning if duration_ms >= _SLOW_ENGINE_ACQUISITION_SECONDS * 1000 else logger.info
        log_cleanup_complete(
            "Rejected warm worker cleanup complete request_id=%s namespace=%s engine_scope=%s resource_id=%s duration_ms=%.1f",
            cleanup.request_id,
            cleanup.identity.namespace,
            enums_pb2.ComputeWorkerScope.Name(cleanup.identity.scope).removeprefix("COMPUTE_WORKER_SCOPE_").lower(),
            cleanup.identity.resource_id,
            duration_ms,
        )
        return 0.0

    def _managed_container_ids(self) -> set[str]:
        """Return Docker containers that belong to this manager right now."""
        with self._capacity_changed:
            engines = [
                *(info.engine for info in self._engines.values()),
                *self._warm_workers,
                *self._starting_engines.values(),
                *self._stopping_engines.values(),
                *self._stopping_warm_workers.values(),
            ]
        return {container_id for engine in engines if (container_id := getattr(engine, "container_id", None)) is not None}

    def notify_capacity_changed(self) -> None:
        """Wake parked capacity waiters when a slot may free."""
        with self._capacity_changed:
            waiters = list(self._capacity_waiters)
            self._capacity_waiters.clear()
            self._admit_spawn_waiters_locked()
            self._capacity_changed.notify_all()
        for loop, future in waiters:
            if future.done():
                continue
            # Loop closed — waiter is gone.
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(self._resolve_capacity_waiter, future)

    @staticmethod
    def _resolve_capacity_waiter(future: asyncio.Future[bool]) -> None:
        if not future.done():
            future.set_result(True)

    def _identity_busy_locked(self, key: ComputeWorkerIdentityKey) -> bool:
        return key in self._engine_events or bool(self._spawn_admissions.get(key)) or any(waiter.key == key for waiter in self._spawn_waiters)

    async def _wait_for_identity_turn(
        self,
        key: ComputeWorkerIdentityKey,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Wait without a compute runner while this exact identity is starting."""
        while True:
            with self._capacity_changed:
                if self._closed:
                    raise RuntimeError("Process manager is shut down")
                if key in self._engine_events or self._spawn_admissions.get(key) or any(waiter.key == key for waiter in self._spawn_waiters):
                    future: asyncio.Future[bool] = loop.create_future()
                    self._capacity_waiters.append((loop, future))
                else:
                    return
            try:
                await future
            finally:
                with self._capacity_changed:
                    self._capacity_waiters[:] = [(waiting_loop, waiting) for waiting_loop, waiting in self._capacity_waiters if waiting is not future]
                if not future.done():
                    future.cancel()

    def _finish_engine_event(self, key: ComputeWorkerIdentityKey, event: threading.Event) -> None:
        """Release an identity lifecycle event after its Docker work is done."""
        with self._capacity_changed:
            if self._engine_events.get(key) is event:
                self._engine_events.pop(key, None)
                event.set()
            self._capacity_changed.notify_all()
        self.notify_capacity_changed()

    @staticmethod
    def _resolve_waiter(waiter: _SpawnWaiter, *, owns_admission: bool = False, error: RuntimeError | None = None) -> None:
        def resolve() -> None:
            if waiter.future.done():
                return
            logger.debug("Engine admission notification for %s (owns=%s)", waiter.key, owns_admission)
            if error is None:
                waiter.future.set_result(owns_admission)
            else:
                waiter.future.set_exception(error)

        with contextlib.suppress(RuntimeError):
            waiter.loop.call_soon_threadsafe(resolve)

    def _reserve_capacity_locked(self) -> _CapacityAdmission | None:
        active_capacity_available = self._capacity_used_locked() < settings.compute_workers
        if active_capacity_available:
            warm_claim = self._warm_worker_available_locked()
            cold_start = not warm_claim
            if cold_start:
                self._cold_starts += 1
            self._capacity_starts += 1
            if warm_claim:
                self._warm_worker_claims += 1
            return _CapacityAdmission(warm_claim=warm_claim, cold_start=cold_start)
        idle_key, idle_info = self._find_idle_engine_locked()
        if idle_key is None or idle_info is None:
            return None
        warm_claim = self._warm_worker_available_locked()
        cold_start = not warm_claim
        if cold_start:
            self._cold_starts += 1
        identity = self._engine_identities.pop(idle_key)
        del self._engines[idle_key]
        self._stopping_engines[id(idle_info.engine)] = idle_info.engine
        self._capacity_reserved_stops.add(id(idle_info.engine))
        eviction_event = threading.Event()
        self._engine_events[idle_key] = eviction_event
        self._capacity_starts += 1
        if warm_claim:
            self._warm_worker_claims += 1
        return _CapacityAdmission(
            evicted=(idle_key, idle_info, identity),
            eviction_event=eviction_event,
            warm_claim=warm_claim,
            cold_start=cold_start,
        )

    def _admit_spawn_waiters_locked(self) -> None:
        """Reserve available slots round-robin across classes, FIFO within each."""
        while self._spawn_waiters:
            if self._closed:
                waiters = self._spawn_waiters
                self._spawn_waiters = deque()
                for waiter in waiters:
                    self._resolve_waiter(waiter, error=RuntimeError("Process manager is shut down"))
                return
            eligible_waiters = (
                index
                for index, waiter in enumerate(self._spawn_waiters)
                if waiter.key not in self._engine_events and not self._spawn_admissions.get(waiter.key)
            )
            eligible = list(eligible_waiters)
            eligible_priorities = {self._spawn_waiters[index].priority for index in eligible}
            waiter_index = None
            next_priority = self._next_spawn_priority
            for offset in range(len(_COMPUTE_WORKER_ADMISSION_PRIORITIES)):
                priority_index = (_COMPUTE_WORKER_ADMISSION_PRIORITIES.index(self._next_spawn_priority) + offset) % len(_COMPUTE_WORKER_ADMISSION_PRIORITIES)
                priority = _COMPUTE_WORKER_ADMISSION_PRIORITIES[priority_index]
                if priority in eligible_priorities:
                    waiter_index = next(index for index in eligible if self._spawn_waiters[index].priority == priority)
                    next_priority = _COMPUTE_WORKER_ADMISSION_PRIORITIES[(priority_index + 1) % len(_COMPUTE_WORKER_ADMISSION_PRIORITIES)]
                    break
            if waiter_index is None:
                return
            waiter = self._spawn_waiters[waiter_index]
            if waiter.key in self._engines:
                del self._spawn_waiters[waiter_index]
                if waiter.reserve_existing_request:
                    self._request_reservations[waiter.key] = self._request_reservations.get(waiter.key, 0) + 1
                    self._engines[waiter.key].touch()
                    waiter.reserved_existing_request = True
                self._resolve_waiter(waiter)
                continue
            admission = self._reserve_capacity_locked()
            if admission is None:
                return
            self._next_spawn_priority = next_priority
            del self._spawn_waiters[waiter_index]
            self._spawn_admissions.setdefault(waiter.key, deque()).append(admission)
            waiter.owns_admission = True
            self._resolve_waiter(waiter, owns_admission=True)

    def release_spawn_admission(self, identity: ComputeWorkerIdentity | None, *, namespace: str | None = None, owned: bool) -> bool:
        """Return an unused admission, such as when an admitted task is cancelled."""
        if identity is None or not owned:
            return False
        key = self._key(identity, namespace=namespace)
        evicted: tuple[ComputeWorkerIdentityKey, ComputeWorkerInfo, ComputeWorkerIdentity] | None = None
        eviction_event: threading.Event | None = None
        with self._capacity_changed:
            admissions = self._spawn_admissions.get(key)
            if not admissions or admissions[0].claimed:
                return False
            admission = admissions.popleft()
            if not admissions:
                self._spawn_admissions.pop(key, None)
            # Every admission reserves one active-start ticket. A warm claim
            # reserves an additional warm worker, so releasing it must
            # return both counters. Leaving the start ticket behind makes a
            # canceled browser request permanently consume capacity.
            if admission.warm_claim:
                self._warm_worker_claims = max(0, self._warm_worker_claims - 1)
            if admission.cold_start:
                self._cold_starts = max(0, self._cold_starts - 1)
                self._warm_worker_replenish_trigger.set()
            admission.released = True
            evicted = admission.evicted
            eviction_event = admission.eviction_event
            if evicted is None:
                self._capacity_starts = max(0, self._capacity_starts - 1)
                self._admit_spawn_waiters_locked()
        # Liveness is an engine RPC/Docker call. Never perform it while the
        # capacity condition is held: a slow runtime probe would otherwise
        # block every claim, release, and reaper decision in this process.
        evicted_is_alive = False
        if evicted is not None:
            with contextlib.suppress(Exception):
                evicted_is_alive = evicted[1].engine.is_process_alive()

        restored_eviction = False
        if evicted is not None:
            with self._capacity_changed:
                if evicted_is_alive and not self._closed:
                    evicted_key, evicted_info, evicted_identity = evicted
                    self._stopping_engines.pop(id(evicted_info.engine), None)
                    self._capacity_reserved_stops.discard(id(evicted_info.engine))
                    self._engines[evicted_key] = evicted_info
                    self._engine_identities[evicted_key] = evicted_identity
                    self._capacity_starts = max(0, self._capacity_starts - 1)
                    restored_eviction = True
                    self._admit_spawn_waiters_locked()
            # Keep the active-start ticket while a dead/closing engine is
            # actually stopped. Otherwise a direct claimant can fill the
            # temporary gap and a later restore would exceed active capacity.
        if evicted is not None and not restored_eviction:
            try:
                with contextlib.suppress(Exception):
                    evicted[1].engine.shutdown()
            finally:
                with self._capacity_changed:
                    self._stopping_engines.pop(id(evicted[1].engine), None)
                    self._capacity_reserved_stops.discard(id(evicted[1].engine))
                    self._capacity_starts = max(0, self._capacity_starts - 1)
                    self._admit_spawn_waiters_locked()
                if eviction_event is not None:
                    self._finish_engine_event(evicted[0], eviction_event)
        elif eviction_event is not None and admission.evicted is not None:
            # The live eviction was restored above; only finish the identity event.
            with self._capacity_changed:
                self._stopping_engines.pop(id(admission.evicted[1].engine), None)
                self._capacity_reserved_stops.discard(id(admission.evicted[1].engine))
            self._finish_engine_event(admission.evicted[0], eviction_event)
        self.notify_capacity_changed()
        return True

    def cancel_engine_job(
        self,
        identity: ComputeWorkerIdentity,
        *,
        namespace: str | None = None,
        job_id: str,
    ) -> bool:
        """Cancel the exact job whose durable compute lease was lost.

        Shared preview workers outlive individual requests, but a worker that
        no longer owns a durable request must stop that request's stale job so
        a reclaimed request can make progress. This cancels only ``job_id``;
        it never shuts down the shared engine.
        """
        qualified_key = self._key(identity, namespace=namespace)
        if not job_id:
            return False
        with self._capacity_changed:
            info = self._engines.get(qualified_key)
            engine = info.engine if info is not None else None
        if engine is None:
            return False
        cancel = getattr(engine, "cancel_job", None)
        if not callable(cancel):
            return False
        try:
            accepted = bool(cancel(job_id))
        except Exception:
            logger.warning("Failed to cancel engine job %s for %s", job_id, qualified_key, exc_info=True)
            return False
        if accepted:
            logger.info("Cancelled engine job %s for %s", job_id, qualified_key)
        return accepted

    def reserve_engine_request(self, identity: ComputeWorkerIdentity, *, namespace: str | None = None) -> None:
        """Protect an admitted request until its execution has started.

        Capacity admission only guarantees a slot for a new identity. Reused
        engines need an explicit reservation because the actual executor may
        start a few milliseconds after admission returns.
        """
        key = self._key(identity, namespace=namespace)
        with self._capacity_changed:
            if self._closed:
                raise RuntimeError("Process manager is shut down")
            self._request_reservations[key] = self._request_reservations.get(key, 0) + 1
            info = self._engines.get(key)
            if info is not None:
                info.touch()

    def release_engine_request(self, identity: ComputeWorkerIdentity, *, namespace: str | None = None) -> None:
        """Release the reservation created by :meth:`reserve_engine_request`."""
        key = self._key(identity, namespace=namespace)
        with self._capacity_changed:
            reservations = self._request_reservations.get(key, 0)
            if reservations <= 1:
                self._request_reservations.pop(key, None)
            else:
                self._request_reservations[key] = reservations - 1
            self._capacity_changed.notify_all()
        self.notify_capacity_changed()

    def shutdown_compute_worker_after_request_lease_loss(
        self,
        identity: ComputeWorkerIdentity,
        *,
        namespace: str | None = None,
    ) -> bool:
        """Release an engine made useless by a disconnected request.

        Shared preview engines are owned by the identity, not by one HTTP
        request. A request can disconnect while other tabs are still queued
        for the same identity and therefore have no reservation yet. Keep
        shared engines in that case and let the idle reaper release them; an
        individual request must never tear down the worker used by its peers.
        Exclusive build engines can still be released immediately when their
        last request disappears.
        """
        qualified_key = self._key(identity, namespace=namespace)
        if identity.reuse_policy == enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED:
            logger.info("Keeping shared engine %s after a disconnected request", qualified_key)
            return False
        shutdown = False
        with self._capacity_changed:
            request_reservations = self._request_reservations.get(qualified_key, 0)
            info = self._engines.get(qualified_key)
            active_reservations = info.active_reservations if info is not None else 0
            pending_waiters = sum(waiter.key == qualified_key for waiter in self._spawn_waiters)
            pending_admissions = len(self._spawn_admissions.get(qualified_key, ()))
            active_job = bool(info is not None and info.engine.current_job_id)
            shutdown = (
                info is not None
                and request_reservations == 1
                and active_reservations <= 1
                and pending_waiters == 0
                and pending_admissions == 0
                and not active_job
            )
            logger.info(
                "%s engine %s after a disconnected request; "
                "%s request reservations, %s engine reservations, %s pending waiters, "
                "%s pending admissions, active_job=%s",
                "Stopping" if shutdown else "Keeping",
                qualified_key,
                request_reservations,
                active_reservations,
                pending_waiters,
                pending_admissions,
                active_job,
            )
        if shutdown:
            self.shutdown_compute_worker(identity, namespace=namespace)
        return shutdown

    def can_admit_spawn(self) -> bool:
        """True if an active engine slot can be claimed or an idle one evicted."""
        with self._capacity_changed:
            if self._closed:
                return False
            return self._capacity_used_locked() < settings.compute_workers or self._find_idle_engine_locked()[0] is not None

    async def wait_for_capacity(self, *, timeout_seconds: float | None = None) -> bool:
        """Park until local capacity may have freed.

        Callers that lose an admission race use a bounded timeout as a
        low-rate recovery poll instead of spinning in an executor lane.
        """
        loop = asyncio.get_running_loop()
        deadline = None if timeout_seconds is None else loop.time() + max(timeout_seconds, 0.0)
        while True:
            future: asyncio.Future[bool] = loop.create_future()
            with self._capacity_changed:
                if self._closed:
                    raise RuntimeError("Process manager is shut down")
                if self._capacity_used_locked() < settings.compute_workers or self._find_idle_engine_locked()[0] is not None:
                    return True
                self._capacity_waiters.append((loop, future))
            try:
                if deadline is None:
                    await future
                else:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        return False
                    try:
                        await asyncio.wait_for(asyncio.shield(future), timeout=remaining)
                    except TimeoutError:
                        return False
            finally:
                with self._capacity_changed:
                    self._capacity_waiters[:] = [(lp, fut) for lp, fut in self._capacity_waiters if fut is not future]
                if not future.done():
                    future.cancel()

    async def await_spawn_admission(
        self,
        identity: ComputeWorkerIdentity | None,
        *,
        namespace: str | None = None,
        priority: int = COMPUTE_WORKER_ADMISSION_PRIORITY_INTERACTIVE,
        reserve_existing_request: bool = False,
    ) -> bool:
        """Wait until this identity can run — without creating a compute runner.

        - ``None`` identity: no engine gate (request does not need a Polars engine).
        - Existing engine for identity: return immediately (reuse, no new slot).
          ``reserve_existing_request`` closes the gap before its caller starts.
        - Otherwise park until a free slot exists or an idle engine can be evicted.

        Only after this returns should the caller take a compute-pool thread.
        """
        if identity is None:
            return False
        key = self._key(identity, namespace=namespace)
        loop = asyncio.get_running_loop()
        while True:
            await self._wait_for_identity_turn(key, loop)

            waiter = _SpawnWaiter(
                key=key,
                loop=loop,
                future=loop.create_future(),
                priority=priority,
                reserve_existing_request=reserve_existing_request,
            )
            existing = False
            identity_busy = False
            with self._capacity_changed:
                if self._closed:
                    existing = False
                elif key in self._engines:
                    existing = True
                    if reserve_existing_request:
                        self._request_reservations[key] = self._request_reservations.get(key, 0) + 1
                        self._engines[key].touch()
                elif self._identity_busy_locked(key):
                    identity_busy = True
                else:
                    self._spawn_waiters.append(waiter)
                    self._admit_spawn_waiters_locked()
            if self._closed and not existing:
                raise RuntimeError("Process manager is shut down")
            if existing:
                return False
            if identity_busy:
                continue

            if not waiter.future.done() and not waiter.owns_admission:
                with self._capacity_changed:
                    active_engines = len(self._engines)
                    reserved_starts = self._capacity_starts
                    cold_starts = self._cold_starts
                    queued_spawns = len(self._spawn_waiters)
                logger.info(
                    "Engine admission queued (active_capacity=%s active=%s reserved=%s cold_starts=%s queued=%s); request for %s (priority=%s, no runner yet)",
                    settings.compute_workers,
                    active_engines,
                    reserved_starts,
                    cold_starts,
                    queued_spawns,
                    identity.resource_id,
                    priority,
                )
            try:
                owns_admission = await waiter.future
                logger.debug("Engine admission resumed for %s (owns=%s)", key, owns_admission)
                return owns_admission
            except BaseException:
                with self._capacity_changed:
                    with contextlib.suppress(ValueError):
                        self._spawn_waiters.remove(waiter)
                    self._admit_spawn_waiters_locked()
                await run_control_in_thread(
                    self.release_spawn_admission,
                    identity,
                    namespace=namespace,
                    owned=waiter.owns_admission,
                )
                if waiter.reserved_existing_request:
                    await run_control_in_thread(
                        self.release_engine_request,
                        identity,
                        namespace=namespace,
                    )
                self.notify_capacity_changed()
                raise

    async def await_engine_request_admission(
        self,
        identity: ComputeWorkerIdentity,
        *,
        namespace: str | None = None,
        priority: int = COMPUTE_WORKER_ADMISSION_PRIORITY_INTERACTIVE,
    ) -> bool:
        """Admit a request and atomically protect an already-running identity."""
        return await self.await_spawn_admission(
            identity,
            namespace=namespace,
            priority=priority,
            reserve_existing_request=True,
        )

    async def await_engine_job_slot(self, identity: ComputeWorkerIdentity, *, namespace: str | None = None) -> None:
        """Wait for this exact engine's single execution lane without a runner."""
        key = self._key(identity, namespace=namespace)
        loop = asyncio.get_running_loop()
        slot = self._engine_job_slots.get(key)
        if slot is None:
            slot = _EngineJobSlot(lock=asyncio.Lock(), loop=loop)
            self._engine_job_slots[key] = slot
        elif slot.loop is not loop:
            raise RuntimeError("Engine job admission must use the runtime coordinator event loop")
        slot.references += 1
        try:
            await slot.lock.acquire()
        except BaseException:
            self._release_engine_job_slot_reference(key, slot)
            raise

    def release_engine_job_slot(self, identity: ComputeWorkerIdentity, *, namespace: str | None = None) -> None:
        """Release one admitted command and discard an unused per-engine slot."""
        key = self._key(identity, namespace=namespace)
        slot = self._engine_job_slots.get(key)
        if slot is None or not slot.lock.locked():
            raise RuntimeError(f"Engine job slot is not held for {key}")
        slot.lock.release()
        self._release_engine_job_slot_reference(key, slot)

    def _release_engine_job_slot_reference(self, key: ComputeWorkerIdentityKey, slot: _EngineJobSlot) -> None:
        slot.references -= 1
        if slot.references == 0 and self._engine_job_slots.get(key) is slot:
            del self._engine_job_slots[key]

    def _key(self, identity: ComputeWorkerIdentity, namespace: str | None = None) -> ComputeWorkerIdentityKey:
        resource_id = identity.resource_id.strip()
        if not resource_id:
            raise ValueError("engine identity resource_id is required")
        return ComputeWorkerIdentityKey(
            namespace=namespace or get_namespace(),
            scope=identity.scope,
            reuse_policy=identity.reuse_policy,
            resource_id=resource_id,
        )

    def spawn_compute_worker(
        self,
        identity: ComputeWorkerIdentity,
        resource_config: dict | None = None,
        *,
        _reserve: bool = False,
    ) -> ComputeWorkerInfo:
        """Spawn a new compute engine or reuse an existing one for the same identity."""
        acquisition_started = time.perf_counter()
        normalized_config = self._normalize_config(resource_config)
        qualified_key = self._key(identity)
        namespace = qualified_key.namespace
        wait_event: threading.Event | None = None
        reused_info: ComputeWorkerInfo | None = None
        admission: _CapacityAdmission | None = None
        publish_activity_snapshot = False
        shutdown_target: ComputeWorker | None = None
        changed_namespaces: set[str] = {namespace}
        capacity_start_held = False
        warm_claim_held = False
        cold_start_held = False
        warm_health_ms = 0.0
        warm_candidate_shutdown_wait_ms = 0.0
        warm_bind_ms = 0.0
        cold_start_ms = 0.0
        warm_candidate_rejected = False
        lifecycle_wait_ms = 0.0
        prior_engine_shutdown_ms = 0.0
        idle_eviction_shutdown_ms = 0.0
        process_alive_check_ms = 0.0
        snapshot_publication_ms = 0.0

        while True:
            with self._engines_lock:
                if self._closed:
                    raise RuntimeError("Process manager is shut down")
                in_progress_event = self._engine_events.get(qualified_key)
                if in_progress_event is not None:
                    wait_event = in_progress_event
                else:
                    info = self._engines.get(qualified_key)
                    config_changed = info is not None and self._configs_differ(
                        self._normalize_config(info.engine.resource_config),
                        normalized_config,
                    )
                    if info is not None and not config_changed and info.engine.last_known_alive:
                        info.touch()
                        if _reserve:
                            info.active_reservations += 1
                        publish_activity_snapshot = self._on_snapshot is not None and info.activity_snapshot_due()
                        logger.debug("Reusing existing engine for %s", qualified_key)
                        reused_info = info
                        break

                    admissions = self._spawn_admissions.get(qualified_key)
                    admission = admissions[0] if admissions else None
                    if admission is not None:
                        admission.claimed = True
                    self._engine_events[qualified_key] = threading.Event()
                    if info is not None:
                        reason = "resource config changed" if config_changed else "engine is no longer alive"
                        logger.info("%s for engine %s, restarting", reason.capitalize(), qualified_key)
                        shutdown_target = info.engine
                        self._stopping_engines[id(shutdown_target)] = shutdown_target
                        if admission is None:
                            self._capacity_starts += 1
                            self._capacity_reserved_stops.add(id(shutdown_target))
                            capacity_start_held = True
                            warm_claim_held = self._warm_worker_available_locked()
                            if warm_claim_held:
                                self._warm_worker_claims += 1
                            else:
                                self._cold_starts += 1
                                cold_start_held = True
                        info.current_build_id = None
                        info.current_compute_worker_run_id = None
                        del self._engines[qualified_key]
                        self._engine_identities.pop(qualified_key, None)
                    break

            if wait_event is not None:
                wait_started = time.perf_counter()
                wait_event.wait()
                lifecycle_wait_ms += (time.perf_counter() - wait_started) * 1000
                wait_event = None

        if reused_info is not None:
            if admission is not None:
                self.release_spawn_admission(identity, namespace=namespace, owned=True)
            if publish_activity_snapshot:
                snapshot_started = time.perf_counter()
                try:
                    self._emit_snapshot_for_namespaces(changed_namespaces)
                finally:
                    snapshot_publication_ms = (time.perf_counter() - snapshot_started) * 1000
            _log_engine_acquisition(
                identity,
                namespace=namespace,
                source="existing",
                acquisition_ms=(time.perf_counter() - acquisition_started) * 1000,
                lifecycle_wait_ms=lifecycle_wait_ms,
                snapshot_publication_ms=snapshot_publication_ms,
            )
            return reused_info

        spawned_info: ComputeWorkerInfo | None = None
        engine: ComputeWorker | None = None
        registered = False
        admission_consumed = False
        try:
            if shutdown_target is not None:
                shutdown_started = time.perf_counter()
                try:
                    shutdown_target.shutdown()
                finally:
                    self._untrack_stopping_engine(shutdown_target)
                    prior_engine_shutdown_ms += (time.perf_counter() - shutdown_started) * 1000

            # Non-blocking admission: running engines only count. If full, raise
            # ComputeWorkerCapacityFull so the caller parks outside the runner pool.
            if admission is not None:
                # Every admitted identity owns one active-start ticket. It was
                # marked claimed before installing the lifecycle event, so
                # request cancellation cannot release it mid-start.
                capacity_start_held = True
                warm_claim_held = admission.warm_claim
                cold_start_held = admission.cold_start
                evict_info = admission.evicted
                eviction_event = admission.eviction_event
                with self._capacity_changed:
                    admissions = self._spawn_admissions.get(qualified_key)
                    if admissions and admissions[0] is admission:
                        admissions.popleft()
                        if not admissions:
                            self._spawn_admissions.pop(qualified_key, None)
                        admission_consumed = True
            elif shutdown_target is not None:
                # The dead/config-changed identity already holds a replacement
                # ticket. Reclaiming a second ticket here can reject the
                # restart at full capacity and leak the first reservation.
                evict_info = None
                eviction_event = None
            else:
                evict_info, capacity_start_held, eviction_event, warm_claim_held, cold_start_held = self._try_claim_capacity_slot(qualified_key)
            if not capacity_start_held:
                logger.info(
                    "Compute worker capacity (%s) in use; deferring spawn for %s (queue, not runner)",
                    settings.compute_workers,
                    qualified_key,
                )
                raise ComputeWorkerCapacityFull(f"Compute worker capacity ({settings.compute_workers}) is full")
            if evict_info is not None:
                _, idle_engine_info, _ = evict_info
                shutdown_started = time.perf_counter()
                try:
                    idle_engine_info.engine.shutdown()
                finally:
                    self._untrack_stopping_engine(idle_engine_info.engine)
                    if eviction_event is not None:
                        self._finish_engine_event(evict_info[0], eviction_event)
                    idle_eviction_shutdown_ms += (time.perf_counter() - shutdown_started) * 1000
                changed_namespaces.add(evict_info[0].namespace)

            # Health checks are engine RPCs: pop under the lock, probe outside it.
            warm_worker: ComputeWorker | None = None
            while warm_worker is None:
                with self._capacity_changed:
                    if warm_claim_held:
                        # The active-start ticket was reserved together with
                        # the warm claim. Keep it while health is checked
                        # outside the lock; an unhealthy warm candidate falls
                        # back to a cold start using the same active lease.
                        self._warm_worker_claims = max(0, self._warm_worker_claims - 1)
                        warm_claim_held = False
                    candidate = self._warm_workers.popleft() if self._warm_workers else None
                    if candidate is not None:
                        self._starting_engines[id(candidate)] = candidate
                        # A candidate has left the bounded warm-worker reserve even
                        # when its health check will force a cold start. Wake
                        # the single replenisher now so an unhealthy warm
                        # worker cannot permanently shrink the reserve.
                        self._warm_worker_replenish_trigger.set()
                if candidate is None:
                    break
                try:
                    health_started = time.perf_counter()
                    healthy = candidate.check_health()
                except Exception:
                    healthy = False
                finally:
                    warm_health_ms += (time.perf_counter() - health_started) * 1000
                if healthy:
                    warm_worker = candidate
                else:
                    warm_candidate_rejected = True
                    warm_candidate_shutdown_wait_ms += self._queue_rejected_warm_worker(candidate, qualified_key)

            if warm_worker is not None:
                engine = warm_worker
                bind_id = getattr(engine, "bind_identity", None)
                if callable(bind_id):
                    bind_started = time.perf_counter()
                    bind_id(identity, resource_config=normalized_config, namespace=namespace)
                    warm_bind_ms = (time.perf_counter() - bind_started) * 1000
                bind_cap = getattr(engine, "bind_capacity_notifier", None)
                if callable(bind_cap):
                    bind_cap(self.notify_capacity_changed)
            else:
                if not cold_start_held:
                    with self._capacity_changed:
                        self._cold_starts += 1
                        cold_start_held = True
                cold_start_started = time.perf_counter()
                try:
                    engine = self._engine_factory(identity, normalized_config)
                    self._track_starting_engine(engine)
                    engine.start()
                finally:
                    cold_start_ms = (time.perf_counter() - cold_start_started) * 1000
            process_check_started = time.perf_counter()
            process_alive = engine.is_process_alive()
            process_alive_check_ms = (time.perf_counter() - process_check_started) * 1000
            if not process_alive:
                engine.shutdown()
                raise RuntimeError(f"Failed to start engine for {qualified_key}")
            info = ComputeWorkerInfo(engine)
            if _reserve:
                info.active_reservations = 1
            with self._capacity_changed:
                self._starting_engines.pop(id(engine), None)
                self._engines[qualified_key] = info
                self._engine_identities[qualified_key] = identity
                # Ticket transfers from "starting" to a live engine slot.
                if capacity_start_held:
                    self._capacity_starts = max(self._capacity_starts - 1, 0)
                    capacity_start_held = False
                spawned_info = info
                registered = True
                logger.info("Engine spawned successfully for %s", qualified_key)
            self.notify_capacity_changed()
        except BaseException:
            if admission is not None and not admission_consumed:
                with self._capacity_changed:
                    admissions = self._spawn_admissions.get(qualified_key)
                    still_queued = bool(admissions and admissions[0] is admission)
                    if still_queued:
                        admission.claimed = False
                if still_queued:
                    self.release_spawn_admission(identity, namespace=namespace, owned=True)
                with self._capacity_changed:
                    admission_released = admission.released
                if admission_released:
                    capacity_start_held = False
                    warm_claim_held = False
                    cold_start_held = False
            # A failed bind, health check, or snapshot transition must not
            # leave a live Docker container after its identity event is
            # released. Reconciliation is a backstop, not the normal cleanup
            # path for an engine that never became manager-owned.
            if engine is not None and not registered:
                with contextlib.suppress(Exception):
                    engine.shutdown()
            raise
        finally:
            if engine is not None:
                self._untrack_starting_engine(engine)
            with self._capacity_changed:
                if warm_claim_held:
                    self._warm_worker_claims = max(0, self._warm_worker_claims - 1)
                    warm_claim_held = False
                if capacity_start_held:
                    self._capacity_starts = max(self._capacity_starts - 1, 0)
                    capacity_start_held = False
                if cold_start_held:
                    self._cold_starts = max(self._cold_starts - 1, 0)
                    self._warm_worker_replenish_trigger.set()
                    cold_start_held = False
                in_progress_event = self._engine_events.pop(qualified_key, None)
                if in_progress_event is not None:
                    in_progress_event.set()
            self.notify_capacity_changed()

        if spawned_info is None:
            raise RuntimeError(f"Failed to start engine for {qualified_key}")
        snapshot_started = time.perf_counter()
        try:
            self._emit_snapshot_for_namespaces(changed_namespaces)
        finally:
            snapshot_publication_ms = (time.perf_counter() - snapshot_started) * 1000
        _log_engine_acquisition(
            identity,
            namespace=namespace,
            source="warm" if warm_worker is not None else "cold",
            acquisition_ms=(time.perf_counter() - acquisition_started) * 1000,
            warm_health_ms=warm_health_ms,
            warm_candidate_shutdown_wait_ms=warm_candidate_shutdown_wait_ms,
            warm_bind_ms=warm_bind_ms,
            cold_start_ms=cold_start_ms,
            warm_candidate_rejected=warm_candidate_rejected,
            lifecycle_wait_ms=lifecycle_wait_ms,
            prior_engine_shutdown_ms=prior_engine_shutdown_ms,
            idle_eviction_shutdown_ms=idle_eviction_shutdown_ms,
            process_alive_check_ms=process_alive_check_ms,
            snapshot_publication_ms=snapshot_publication_ms,
        )
        return spawned_info

    def _configs_differ(self, old_config: dict, new_config: dict) -> bool:
        return any(old_config.get(k) != new_config.get(k) for k in _RESOURCE_KEYS)

    def _normalize_config(self, config: dict | None) -> dict:
        if not config:
            return {}
        defaults = self._get_defaults()
        return {k: v for k in _RESOURCE_KEYS if (v := config.get(k)) is not None and v != defaults.get(k)}

    def _find_idle_engine_locked(self) -> tuple[ComputeWorkerIdentityKey | None, ComputeWorkerInfo | None]:
        """Pick the least-recently-used engine with no reservation and no active job.

        Reads in-memory liveness only. This runs on every capacity decision
        while the engines lock is held, so it must never touch Docker.
        """
        idle_key: ComputeWorkerIdentityKey | None = None
        idle_info: ComputeWorkerInfo | None = None
        for active_key, info in self._engines.items():
            engine = info.engine
            # A heartbeat failure must not turn an engine with work in flight
            # into an eviction target. The job state is authoritative here;
            # liveness only tells us whether the work can still make progress.
            if info.active_reservations or self._request_reservations.get(active_key, 0) or engine.current_job_id:
                continue
            if idle_info is not None and info.last_activity >= idle_info.last_activity:
                continue
            idle_key = active_key
            idle_info = info
        return idle_key, idle_info

    def _capacity_used_locked(self) -> int:
        """Count active, stopping, and starting engines against one budget.

        Unassigned warm workers are a separate bounded reserve. They do not
        consume active capacity until assigned to an identity. A stop reserved
        for replacement is represented by its start ticket, not counted twice.
        """
        return len(self._engines) + len(self._stopping_engines) - len(self._capacity_reserved_stops) + self._capacity_starts

    def _warm_worker_available_locked(self) -> bool:
        return len(self._warm_workers) > self._warm_worker_claims

    def _try_claim_capacity_slot(
        self,
        qualified_key: ComputeWorkerIdentityKey,
    ) -> tuple[tuple[ComputeWorkerIdentityKey, ComputeWorkerInfo, ComputeWorkerIdentity] | None, bool, threading.Event | None, bool, bool]:
        """Non-blocking claim: eviction, ticket, event, warm claim, cold-start token.

        Does not park the caller. On failure returns (None, False, None) so runners
        can exit and the async queue can wait without holding a worker thread.
        """
        with self._capacity_changed:
            if self._closed:
                raise RuntimeError("Process manager is shut down")
            if self._spawn_waiters:
                return None, False, None, False, False
            used = self._capacity_used_locked()
            capacity = settings.compute_workers
            if used < capacity:
                warm_claim = self._warm_worker_available_locked()
                cold_start = not warm_claim
                if cold_start:
                    self._cold_starts += 1
                self._capacity_starts += 1
                if warm_claim:
                    self._warm_worker_claims += 1
                self._capacity_changed.notify_all()
                return None, True, None, warm_claim, cold_start
            idle_key, idle_info = self._find_idle_engine_locked()
            if idle_key is not None and idle_info is not None:
                warm_claim = self._warm_worker_available_locked()
                cold_start = not warm_claim
                if cold_start:
                    self._cold_starts += 1
                logger.info(
                    "Compute worker capacity reached (%s), evicting idle engine %s in namespace %s to spawn %s",
                    capacity,
                    idle_key.resource_id,
                    idle_key.namespace,
                    qualified_key,
                )
                del self._engines[idle_key]
                identity = self._engine_identities.pop(idle_key)
                eviction_event = threading.Event()
                self._engine_events[idle_key] = eviction_event
                self._stopping_engines[id(idle_info.engine)] = idle_info.engine
                self._capacity_reserved_stops.add(id(idle_info.engine))
                self._capacity_starts += 1
                if warm_claim:
                    self._warm_worker_claims += 1
                self._capacity_changed.notify_all()
                return (idle_key, idle_info, identity), True, eviction_event, warm_claim, cold_start
            return None, False, None, False, False

    def get_or_create_engine(self, identity: ComputeWorkerIdentity, resource_config: dict | None = None) -> ComputeWorker:
        info = self.spawn_compute_worker(identity, resource_config=resource_config)
        return info.engine

    @contextlib.contextmanager
    def acquire_engine(self, identity: ComputeWorkerIdentity, resource_config: dict | None = None) -> Iterator[ComputeWorker]:
        """Reserve an engine until its caller has submitted work to it."""
        qualified_key = self._key(identity)
        info = self.spawn_compute_worker(identity, resource_config=resource_config, _reserve=True)
        try:
            yield info.engine
        finally:
            with self._capacity_changed:
                current = self._engines.get(qualified_key)
                if current is info:
                    current.active_reservations = max(current.active_reservations - 1, 0)
            self.notify_capacity_changed()

    def restart_engine_with_config(self, identity: ComputeWorkerIdentity, resource_config: dict) -> ComputeWorkerInfo:
        identity_key = self._key(identity)
        logger.info("Restarting engine for %s with new config: %s", identity_key, resource_config)
        # Keep the old identity's capacity reserved until its replacement has
        # been installed. spawn_compute_worker owns that transfer atomically.
        return self.spawn_compute_worker(identity, resource_config=resource_config)

    def get_engine(self, identity: ComputeWorkerIdentity, *, namespace: str | None = None) -> ComputeWorker | None:
        qualified_key = self._key(identity, namespace=namespace)
        with self._engines_lock:
            info = self._engines.get(qualified_key)
            return info.engine if info else None

    def get_engine_info(self, identity: ComputeWorkerIdentity, *, namespace: str | None = None) -> ComputeWorkerInfo | None:
        qualified_key = self._key(identity, namespace=namespace)
        with self._engines_lock:
            return self._engines.get(qualified_key)

    def set_compute_worker_runtime_context(
        self, identity: ComputeWorkerIdentity, *, current_build_id: str | None, current_compute_worker_run_id: str | None
    ) -> None:
        qualified_key = self._key(identity)
        namespace = qualified_key.namespace
        changed = False
        with self._engines_lock:
            info = self._engines.get(qualified_key)
            if info is not None:
                if info.current_build_id != current_build_id:
                    info.current_build_id = current_build_id
                    changed = True
                if info.current_compute_worker_run_id != current_compute_worker_run_id:
                    info.current_compute_worker_run_id = current_compute_worker_run_id
                    changed = True
        if changed:
            self._emit_snapshot_for_namespaces({namespace})

    def _get_defaults(self) -> dict:
        return {
            "max_threads": settings.polars_cores_available,
            "max_memory_mb": settings.polars_max_memory_mb,
            "streaming_chunk_size": settings.polars_streaming_chunk_size,
        }

    def get_compute_worker_status(self, identity: ComputeWorkerIdentity, *, defaults: dict | None = None) -> ComputeWorkerStatusInfo:
        if defaults is None:
            defaults = self._get_defaults()

        qualified_key = self._key(identity)
        with self._engines_lock:
            info = self._engines.get(qualified_key)
            persisted_identity = self._engine_identities.get(qualified_key, identity)
            if info is None:
                return ComputeWorkerStatusInfo(
                    analysis_id=_compute_worker_identity_analysis_id(persisted_identity) or "",
                    resource_id=persisted_identity.resource_id,
                    status=ComputeWorkerStatus.TERMINATED,
                    container_id=None,
                    image_digest=None,
                    lifecycle_status="stopped",
                    termination_reason=None,
                    exit_code=None,
                    oom_killed=None,
                    supervisor_id=self._supervisor_id,
                    owner_id=None,
                    last_activity=None,
                    current_job_id=None,
                    resource_config=None,
                    effective_resources=None,
                    defaults=defaults,
                    scope=_engine_scope_value(persisted_identity),
                    reuse_policy=_engine_reuse_policy_value(persisted_identity),
                    datasource_id=_compute_worker_identity_datasource_id(persisted_identity),
                    build_id=_compute_worker_identity_build_id(persisted_identity),
                    current_build_id=_compute_worker_identity_build_id(persisted_identity),
                    current_compute_worker_run_id=None,
                )

            # Status is a read of tracked state, not a probe: snapshots cover
            # every engine in the namespace and run inline on engine lifecycle
            # changes. The heartbeat loop owns liveness and marks an engine dead
            # as soon as it stops answering.
            engine = info.engine
            is_alive = engine.last_known_alive
            resource_config = (self._normalize_config(engine.resource_config) or None) if engine.resource_config else None
            effective_resources = engine.effective_resources or None

            return ComputeWorkerStatusInfo(
                analysis_id=_compute_worker_identity_analysis_id(persisted_identity) or "",
                resource_id=persisted_identity.resource_id,
                status=ComputeWorkerStatus.HEALTHY if is_alive else ComputeWorkerStatus.TERMINATED,
                container_id=getattr(engine, "container_id", None),
                image_digest=getattr(engine, "image_digest", None),
                lifecycle_status=getattr(engine, "lifecycle_status", "running" if engine.current_job_id else "idle"),
                termination_reason=getattr(engine, "termination_reason", None),
                exit_code=getattr(engine, "exit_code", None),
                oom_killed=getattr(engine, "oom_killed", None),
                supervisor_id=self._supervisor_id,
                owner_id=_compute_worker_identity_build_id(persisted_identity) or self._supervisor_id,
                last_activity=info.last_activity.isoformat(),
                current_job_id=engine.current_job_id,
                resource_config=resource_config,
                effective_resources=effective_resources,
                defaults=defaults,
                scope=_engine_scope_value(persisted_identity),
                reuse_policy=_engine_reuse_policy_value(persisted_identity),
                datasource_id=_compute_worker_identity_datasource_id(persisted_identity),
                build_id=_compute_worker_identity_build_id(persisted_identity),
                current_build_id=info.current_build_id or _compute_worker_identity_build_id(persisted_identity),
                current_compute_worker_run_id=info.current_compute_worker_run_id,
                docker_host=getattr(engine, "docker_host", None),
            )

    def shutdown_compute_worker(self, identity: ComputeWorkerIdentity, *, namespace: str | None = None, emit_snapshot: bool = True) -> None:
        qualified_key = self._key(identity, namespace=namespace)
        resolved_namespace = qualified_key.namespace
        info: ComputeWorkerInfo | None = None
        shutdown_event: threading.Event | None = None
        while True:
            with self._capacity_changed:
                lifecycle_event = self._engine_events.get(qualified_key)
                if lifecycle_event is None:
                    shutdown_event = threading.Event()
                    self._engine_events[qualified_key] = shutdown_event
                    info = self._engines.pop(qualified_key, None)
                    self._engine_identities.pop(qualified_key, None)
                    if info is not None:
                        self._stopping_engines[id(info.engine)] = info.engine
                        self._capacity_changed.notify_all()
                    break
            lifecycle_event.wait()
        assert shutdown_event is not None
        try:
            if info is None:
                logger.debug("No engine found to shutdown for %s", qualified_key)
                return
            # Active jobs cannot outlive the engine: cancel/clear then stop container.
            active_job = getattr(info.engine, "current_job_id", None)
            if active_job and info.engine.is_process_alive():
                logger.info(
                    "Cancelling active job %s before shutting down engine %s",
                    active_job,
                    qualified_key,
                )
                cancel = getattr(info.engine, "cancel_current_job", None)
                if callable(cancel):
                    with contextlib.suppress(Exception):
                        cancel()
            logger.info("Shutting down engine for %s", qualified_key)
            info.engine.shutdown()
            logger.info("Engine shutdown complete for %s", qualified_key)
            if emit_snapshot:
                self._emit_snapshot_for_namespaces({resolved_namespace})
        finally:
            if info is not None:
                self._untrack_stopping_engine(info.engine)
            # A new spawn for this identity must not create a replacement until
            # Docker has finished stopping/removing the old container. Without
            # this event, same-identity teardown/start races can initialize a
            # new RPC client against the old container and report collisions.
            self._finish_engine_event(qualified_key, shutdown_event)

    def shutdown_compute_worker_if_idle(self, identity: ComputeWorkerIdentity, *, namespace: str | None = None) -> bool:
        """Stop an engine only after atomically fencing new RID work.

        Datasource deletion uses this instead of checking ``current_job_id``
        and then shutting down in separate operations. A claimed request may
        already hold a reservation while it waits for the per-RID job lane,
        before the engine reports a current job.
        """
        key = self._key(identity, namespace=namespace)
        while True:
            with self._capacity_changed:
                lifecycle_event = self._engine_events.get(key)
                if lifecycle_event is None:
                    info = self._engines.get(key)
                    if info is None:
                        return not (
                            self._request_reservations.get(key, 0)
                            or self._spawn_admissions.get(key)
                            or any(waiter.key == key for waiter in self._spawn_waiters)
                        )
                    if self._request_reservations.get(key, 0) or info.active_reservations or info.engine.current_job_id:
                        return False
                    shutdown_event = threading.Event()
                    self._engine_events[key] = shutdown_event
                    del self._engines[key]
                    self._engine_identities.pop(key, None)
                    self._stopping_engines[id(info.engine)] = info.engine
                    self._capacity_changed.notify_all()
                    break
            lifecycle_event.wait()

        try:
            logger.info("Shutting down idle engine for %s", key)
            info.engine.shutdown()
            logger.info("Idle engine shutdown complete for %s", key)
            self._emit_snapshot_for_namespaces({key.namespace})
            return True
        finally:
            self._untrack_stopping_engine(info.engine)
            self._finish_engine_event(key, shutdown_event)

    def shutdown_all(self) -> None:
        self._reaper_stop.set()
        self._warm_worker_replenish_trigger.set()
        with self._capacity_changed:
            self._closed = True
            self._capacity_changed.notify_all()
        if self._reaper_thread is not None and self._reaper_thread.is_alive():
            self._reaper_thread.join()
        if self._warm_worker_replenisher_thread is not None and self._warm_worker_replenisher_thread.is_alive():
            self._warm_worker_replenisher_thread.join()
        with self._capacity_changed:
            warm_workers_to_stop = list(self._warm_workers)
            self._warm_workers.clear()
            self._warm_worker_claims = 0
            for engine in warm_workers_to_stop:
                self._stopping_engines[id(engine)] = engine
            spawn_events = list(self._engine_events.values())
            capacity_waiters = list(self._capacity_waiters)
            self._capacity_waiters.clear()
            queued_waiters = list(self._spawn_waiters)
            self._spawn_waiters.clear()
            admissions = [admission for group in self._spawn_admissions.values() for admission in group]
            unclaimed_admissions = [admission for admission in admissions if not admission.claimed]
            admitted_evictions = [admission.evicted for admission in unclaimed_admissions if admission.evicted is not None]
            admitted_cold_starts = sum(admission.cold_start for admission in unclaimed_admissions)
            for admission in unclaimed_admissions:
                admission.released = True
            self._spawn_admissions.clear()
            self._request_reservations.clear()
            self._capacity_starts = 0
            self._cold_starts = max(0, self._cold_starts - admitted_cold_starts)
            self._capacity_changed.notify_all()
        for waiter in queued_waiters:
            self._resolve_waiter(waiter, error=RuntimeError("Process manager is shut down"))
        for loop, future in capacity_waiters:

            def reject(waiting: asyncio.Future[bool] = future) -> None:
                if not waiting.done():
                    waiting.set_exception(RuntimeError("Process manager is shut down"))

            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(reject)
        for spawn_event in spawn_events:
            spawn_event.wait()
        # A spawn already in progress may reject and enqueue a warm candidate
        # after the replenisher thread observed _closed and exited. Drain that
        # residual work once here so teardown remains deterministic.
        with self._capacity_changed:
            final_warm_cleanups = list(self._warm_worker_cleanups)
            self._warm_worker_cleanups.clear()
        for cleanup in final_warm_cleanups:
            self._cleanup_rejected_warm_worker(cleanup)
        with self._capacity_changed:
            shutdown_targets = list(self._engines.items())
            self._engines.clear()
            self._engine_identities.clear()
            for _key, info in shutdown_targets:
                self._stopping_engines[id(info.engine)] = info.engine
            self._capacity_changed.notify_all()
        changed_namespaces = {key.namespace for key, _ in shutdown_targets}
        for key, info in shutdown_targets:
            logger.info("Shutting down engine for %s", key)
            try:
                info.engine.shutdown()
            finally:
                self._untrack_stopping_engine(info.engine)
        for _key, info, _identity in admitted_evictions:
            try:
                info.engine.shutdown()
            finally:
                self._untrack_stopping_engine(info.engine)
        for warm_worker in warm_workers_to_stop:
            try:
                with contextlib.suppress(Exception):
                    warm_worker.shutdown()
            finally:
                self._untrack_stopping_engine(warm_worker)
        if changed_namespaces:
            self._emit_snapshot_for_namespaces(changed_namespaces)

    def list_engines(self) -> list[str]:
        namespace = get_namespace()
        with self._engines_lock:
            return [key.resource_id for key in self._engines if key.namespace == namespace]

    def list_all_compute_worker_statuses(self) -> list[ComputeWorkerStatusInfo]:
        return self._list_compute_worker_statuses_for_namespace(get_namespace())

    def resynchronize_snapshots(self) -> None:
        """Republish every durable engine projection after API reconnect."""
        with self._engines_lock:
            namespaces = {key.namespace for key in self._engines}
        self._emit_snapshot_for_namespaces(namespaces)

    def _list_compute_worker_statuses_for_namespace(self, namespace: str) -> list[ComputeWorkerStatusInfo]:
        defaults = self._get_defaults()
        with self._engines_lock:
            identities = [(self._engine_identities[key], info) for key, info in self._engines.items() if key.namespace == namespace]
            for _identity, info in identities:
                info.mark_snapshot_published()
        return [self.get_compute_worker_status(identity, defaults=defaults) for identity, _info in identities]

    def _emit_snapshot_for_namespaces(self, namespaces: set[str]) -> None:
        if self._on_snapshot is None:
            return
        for namespace in sorted(namespaces):
            token = set_namespace_context(namespace)
            try:
                self._on_snapshot(self._list_compute_worker_statuses_for_namespace(namespace))
            finally:
                reset_namespace(token)

    def _spawn_warm_worker(self, factory: Callable[[], ComputeWorker]) -> ComputeWorker | None:
        """Start one unassigned compute worker without consuming active capacity."""
        new_engine: ComputeWorker | None = None
        try:
            new_engine = factory()
            self._track_starting_engine(new_engine)
            new_engine.start()
            return new_engine
        except Exception:
            logger.warning("Failed to start warm compute worker", exc_info=True)
            if new_engine is not None:
                with contextlib.suppress(Exception):
                    new_engine.shutdown()
            if new_engine is not None:
                self._untrack_starting_engine(new_engine)
            return None

    def _replenish_warm_workers_loop(self) -> None:
        factory = self._warm_worker_factory
        while True:
            self._warm_worker_replenish_trigger.wait(timeout=1.0)
            self._warm_worker_replenish_trigger.clear()
            # Starts and rejected-worker shutdowns share this one serial
            # lifecycle lane. A rejected worker remains part of the warm
            # budget until Docker cleanup completes, bounding queued cleanup
            # by the configured reserve and preventing replacement overrun.
            while True:
                cleanup: _WarmWorkerCleanup | None = None
                with self._capacity_changed:
                    stopping = self._closed or self._reaper_stop.is_set()
                    target_warm = max(self._warm_worker_target, 0)
                    current_warm = len(self._warm_workers)
                    can_replenish = (
                        not stopping and factory is not None and current_warm + self._warm_worker_starts + len(self._stopping_warm_workers) < target_warm
                    )
                    if can_replenish:
                        self._cold_starts += 1
                        self._warm_worker_starts += 1
                    elif self._warm_worker_cleanups:
                        cleanup = self._warm_worker_cleanups.popleft()
                    elif stopping or factory is None:
                        if stopping and self._engine_events:
                            self._capacity_changed.wait(timeout=1.0)
                            continue
                        return
                    else:
                        break

                if cleanup is not None:
                    retry_delay = self._cleanup_rejected_warm_worker(cleanup)
                    if retry_delay > 0:
                        self._reaper_stop.wait(retry_delay)
                    continue

                engine: ComputeWorker | None = None
                discard_engine = False
                assert factory is not None
                try:
                    engine = self._spawn_warm_worker(factory)
                finally:
                    with self._capacity_changed:
                        self._warm_worker_starts = max(0, self._warm_worker_starts - 1)
                        self._cold_starts = max(0, self._cold_starts - 1)
                        self._warm_worker_replenish_trigger.set()
                        if engine is not None:
                            if self._closed or self._reaper_stop.is_set():
                                discard_engine = True
                            elif len(self._warm_workers) < target_warm:
                                self._starting_engines.pop(id(engine), None)
                                self._warm_workers.append(engine)
                            else:
                                # A concurrent claim/replenishment wakeup may
                                # have filled the target while this engine was
                                # booting. Do not let a late start exceed it.
                                discard_engine = True
                        self._capacity_changed.notify_all()
                self.notify_capacity_changed()
                if discard_engine and engine is not None:
                    with contextlib.suppress(Exception):
                        engine.shutdown()
                    self._untrack_starting_engine(engine)
                # Back off outside the lock: engine startup and the global
                # advisory-lock probe are both allowed to fail transiently.
                if engine is None:
                    time.sleep(1.0)

    def _reap_idle_engines_loop(self) -> None:
        reconciliation_interval = max(_DOCKER_RECONCILE_INTERVAL_SECONDS, self._idle_reap_interval_seconds)
        next_reconciliation = time.monotonic() + reconciliation_interval
        while not self._reaper_stop.wait(self._idle_reap_interval_seconds):
            self._reap_idle_engines_once()
            if self._uses_docker_runtime and self._reconcile_docker_containers and time.monotonic() >= next_reconciliation:
                next_reconciliation = time.monotonic() + reconciliation_interval
                try:
                    reconcile_deployment_containers(
                        supervisor_id=self._supervisor_id,
                        coordinator_generation=self._coordinator_generation,
                        coordinator_guard=self._coordinator_guard,
                        # Protect current and in-flight engines by ID. A
                        # running container not in this set is removable only
                        # after the startup grace period, which closes the
                        # snapshot/create race without leaking old containers.
                        remove_running=True,
                        running_grace_seconds=max(settings.engine_start_timeout_seconds, 30),
                        keep_container_ids=self._managed_container_ids(),
                    )
                except Exception:
                    logger.exception("Periodic engine container reconciliation failed for %s", self._supervisor_id)

    def _reap_idle_engines_once(self) -> None:
        now = datetime.now(UTC)
        stale: list[tuple[ComputeWorkerIdentityKey, ComputeWorkerInfo, threading.Event]] = []
        changed_namespaces: set[str] = set()
        with self._engines_lock:
            tracked = list(self._engines.items())
        # Refreshing liveness is Docker I/O, one round trip per engine. It runs
        # before the lock is taken so reaping never blocks claims.
        liveness = {key: info.engine.is_process_alive() for key, info in tracked}
        with self._capacity_changed:
            for key, info in tracked:
                if self._engines.get(key) is not info:
                    continue
                engine = info.engine
                is_alive = liveness[key]
                # Do not reap work in flight just because a heartbeat or
                # Docker probe briefly reported the container as unavailable.
                # The request watcher owns clearing current_job_id after it
                # publishes a terminal result.
                is_busy = bool(engine.current_job_id)
                request_reservations = self._request_reservations.get(key, 0)
                idle_seconds = (now - info.last_activity).total_seconds()
                if info.active_reservations or request_reservations or is_busy or (is_alive and idle_seconds < self._idle_ttl_seconds):
                    continue
                if key in self._engine_events:
                    continue
                lifecycle_event = threading.Event()
                self._engine_events[key] = lifecycle_event
                stale.append((key, info, lifecycle_event))
                del self._engines[key]
                self._engine_identities.pop(key, None)
                self._stopping_engines[id(engine)] = engine
                changed_namespaces.add(key.namespace)
            if stale:
                self._capacity_changed.notify_all()
        for key, info, lifecycle_event in stale:
            try:
                with contextlib.suppress(Exception):
                    logger.info("Reaping idle engine %s", key)
                    info.engine.shutdown()
            finally:
                self._untrack_stopping_engine(info.engine)
                self._finish_engine_event(key, lifecycle_event)
        if changed_namespaces:
            self._emit_snapshot_for_namespaces(changed_namespaces)
