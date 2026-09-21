from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime

from dataforge_protocol import compute_pb2, enums_pb2
from runtime.config import settings
from runtime.docker_engine import DockerComputeEngine, reconcile_deployment_containers
from runtime.domain.compute.base import ComputeEngine, EngineStatusInfo
from runtime.domain.compute.schemas import EngineStatus
from runtime.global_engine_capacity import GlobalEngineCapacity, GlobalEngineSlot
from runtime.namespace import get_namespace, reset_namespace, set_namespace_context

logger = logging.getLogger(__name__)

_RESOURCE_KEYS = frozenset({"max_threads", "max_memory_mb", "streaming_chunk_size"})

# Lower values are admitted first. Interactive work must be able to bypass
# best-effort lifecycle/prewarm work that is waiting for a full engine pool.
ENGINE_ADMISSION_PRIORITY_INTERACTIVE = 0
ENGINE_ADMISSION_PRIORITY_LIFECYCLE = 1

EngineIdentity = compute_pb2.EngineIdentity
EngineFactory = Callable[[EngineIdentity, dict | None], ComputeEngine]
EngineSnapshotListener = Callable[[list[EngineStatusInfo]], None]


class EngineCapacityFull(Exception):
    """No free engine slot at the moment of claim (lost race after admission).

    Callers must not hold a compute runner while waiting. Prefer
    :meth:`ProcessManager.await_spawn_admission` *before* taking a runner so
    capacity wait happens with zero runner threads.
    """


@dataclass(frozen=True, slots=True)
class EngineIdentityKey:
    namespace: str
    scope: int
    reuse_policy: int
    resource_id: str


@dataclass(slots=True)
class _CapacityAdmission:
    evicted: tuple[EngineIdentityKey, EngineInfo, EngineIdentity] | None = None
    eviction_event: threading.Event | None = None
    # A warm engine is already part of the capacity count. Reserve one
    # explicitly so a burst cannot all observe the same non-empty pool and
    # then start more engines than the global limit while they race to pop it.
    warm_claim: bool = False
    # A slot reserved from the cross-process capacity pool before this
    # admission is handed to the compute runner.
    global_slot: GlobalEngineSlot | None = None


@dataclass(slots=True)
class _SpawnWaiter:
    key: EngineIdentityKey
    loop: asyncio.AbstractEventLoop
    future: asyncio.Future[bool]
    priority: int
    owns_admission: bool = False
    global_slot: GlobalEngineSlot | None = None


def _engine_identity_analysis_id(identity: EngineIdentity) -> str | None:
    return identity.analysis_id if identity.HasField("analysis_id") else None


def _engine_identity_datasource_id(identity: EngineIdentity) -> str | None:
    return identity.datasource_id if identity.HasField("datasource_id") else None


def _engine_identity_build_id(identity: EngineIdentity) -> str | None:
    return identity.build_id if identity.HasField("build_id") else None


def _engine_scope_value(identity: EngineIdentity) -> str:
    if identity.scope == enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW:
        return "datasource_preview"
    if identity.scope == enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE:
        return "analysis_interactive"
    if identity.scope == enums_pb2.ENGINE_SCOPE_BUILD:
        return "build"
    raise ValueError("engine identity scope is unspecified")


def _engine_reuse_policy_value(identity: EngineIdentity) -> str:
    if identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_SHARED:
        return "shared"
    if identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_EXCLUSIVE:
        return "exclusive"
    raise ValueError("engine identity reuse policy is unspecified")


class EngineInfo:
    """Tracks engine metadata for reuse, status, and eviction decisions."""

    def __init__(self, engine: ComputeEngine):
        self.engine = engine
        self.last_activity = datetime.now(UTC)
        self.current_build_id: str | None = None
        self.current_engine_run_id: str | None = None
        self.active_reservations = 0

    def touch(self) -> None:
        self.last_activity = datetime.now(UTC)


class ProcessManager:
    def __init__(
        self,
        engine_factory: EngineFactory | None = None,
        on_snapshot: EngineSnapshotListener | None = None,
        *,
        warm_engine_factory: Callable[[], ComputeEngine] | None = None,
        supervisor_id: str = "worker",
        warm_pool_size: int | None = None,
        global_reserved_slots: int = 0,
    ) -> None:
        self._engines: dict[EngineIdentityKey, EngineInfo] = {}
        self._engine_identities: dict[EngineIdentityKey, EngineIdentity] = {}
        self._engines_lock = threading.Lock()
        # Capacity admission only. Running engines + in-flight starts count.
        # Waiters park via wait_for_capacity() (async) and must not hold runners.
        self._capacity_changed = threading.Condition(self._engines_lock)
        self._capacity_starts = 0
        # Generic change waiters and FIFO spawn admissions park outside the
        # compute thread pool. A spawn admission reserves capacity before its
        # request is allowed to take a runner.
        self._capacity_waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Future[None]]] = []
        self._spawn_waiters: deque[_SpawnWaiter] = deque()
        self._spawn_admissions: dict[EngineIdentityKey, deque[_CapacityAdmission]] = {}
        self._engine_events: dict[EngineIdentityKey, threading.Event] = {}
        # A request can be admitted because an engine already exists, then
        # wait briefly for an engine executor thread. Keep that identity out of
        # the eviction candidates during the gap; otherwise another request
        # can evict it and the admitted request will recreate it later.
        self._request_reservations: dict[EngineIdentityKey, int] = {}
        # Engines are created outside the manager lock. Keep in-flight starts
        # visible to Docker reconciliation so it cannot remove a container in
        # the small window between ``start()`` and registration in _engines.
        self._starting_engines: dict[int, ComputeEngine] = {}
        # A shutdown removes an engine from the active map before Docker work
        # completes. Keep that container protected until stop/remove returns.
        self._stopping_engines: dict[int, ComputeEngine] = {}
        # Every Docker engine owns one advisory-lock lease. The lease is
        # transferred when a warm engine becomes an identity engine and when an
        # idle engine is evicted, so child build processes cannot exceed the
        # application-wide cap owned by this manager.
        self._global_engine_slots: dict[int, GlobalEngineSlot] = {}
        self._closed = False
        self._supervisor_id = supervisor_id
        self._uses_docker_runtime = engine_factory is None
        self._user_engine_factory = engine_factory or (
            lambda identity, resource_config: DockerComputeEngine(
                identity,
                resource_config=resource_config,
                supervisor_id=self._supervisor_id,
            )
        )
        self._on_snapshot = on_snapshot
        self._global_capacity = (
            GlobalEngineCapacity(
                deployment_id=settings.deployment_id,
                max_slots=settings.max_concurrent_engines,
                database_url=settings.database_url,
                reserved_slots=global_reserved_slots,
            )
            if self._uses_docker_runtime
            else None
        )
        self._idle_ttl_seconds = settings.engine_idle_ttl_seconds
        self._idle_reap_interval_seconds = settings.engine_idle_reap_interval_seconds
        self._warm_pool_size = settings.engine_warm_pool_size if warm_pool_size is None else warm_pool_size
        self._warm_pool: deque[ComputeEngine] = deque()
        self._warm_pool_claims = 0
        self._reaper_stop = threading.Event()
        self._reaper_thread: threading.Thread | None = None
        if self._idle_ttl_seconds > 0:
            self._reaper_thread = threading.Thread(target=self._reap_idle_engines_loop, name="engine-idle-reaper", daemon=True)
            self._reaper_thread.start()
        self._warm_engine_factory = warm_engine_factory or (
            (lambda: DockerComputeEngine(supervisor_id=self._supervisor_id)) if self._uses_docker_runtime else None
        )
        self._warm_replenish_trigger = threading.Event()
        self._warm_replenish_thread: threading.Thread | None = None
        if self._warm_engine_factory is not None and self._warm_pool_size > 0:
            self._warm_replenish_thread = threading.Thread(
                target=self._replenish_warm_pool_loop,
                name="engine-warm-pool-replenisher",
                daemon=True,
            )
            self._warm_replenish_thread.start()
            self._warm_replenish_trigger.set()

    def wait_for_warm_pool_ready(self, *, timeout_seconds: float) -> bool:
        """Wait until the configured initial warm-pool target is available.

        The runtime worker row is the readiness signal used by the API and the
        E2E stack.  Registering that row before the asynchronous prewarm batch
        completes makes the first requests race container startup and turns a
        healthy-but-not-ready worker into long queue waits or false 503s.
        Keep the timeout bounded so a failed engine runtime does not prevent the
        manager from coming up and reporting the actual failure through normal
        request execution.
        """
        target = min(max(self._warm_pool_size, 0), max(settings.max_concurrent_engines, 0))
        if target == 0:
            return True

        deadline = time.monotonic() + max(timeout_seconds, 0.0)
        with self._capacity_changed:
            while len(self._warm_pool) < target and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._capacity_changed.wait(timeout=remaining)
            return len(self._warm_pool) >= target

    @property
    def warm_pool_count(self) -> int:
        with self._capacity_changed:
            return len(self._warm_pool)

    def _engine_factory(self, identity: EngineIdentity, resource_config: dict | None = None) -> ComputeEngine:
        """Create an engine and wire capacity wakeups when its job slot frees."""
        engine = self._user_engine_factory(identity, resource_config)
        bind = getattr(engine, "bind_capacity_notifier", None)
        if callable(bind):
            bind(self.notify_capacity_changed)
        return engine

    @property
    def _global_capacity_enabled(self) -> bool:
        return self._global_capacity is not None and self._global_capacity.enabled

    def _try_acquire_global_slot(self) -> GlobalEngineSlot | None:
        if not self._global_capacity_enabled:
            return None
        assert self._global_capacity is not None
        return self._global_capacity.try_acquire()

    def _track_global_slot(self, engine: ComputeEngine, slot: GlobalEngineSlot) -> None:
        with self._capacity_changed:
            self._global_engine_slots[id(engine)] = slot

    def _take_global_slot(self, engine: ComputeEngine) -> GlobalEngineSlot | None:
        with self._capacity_changed:
            return self._global_engine_slots.pop(id(engine), None)

    def _release_global_slot(self, slot: GlobalEngineSlot | None) -> None:
        if slot is None:
            return
        slot.release()
        self.notify_capacity_changed()

    def _release_engine_slot(self, engine: ComputeEngine) -> None:
        self._release_global_slot(self._take_global_slot(engine))

    async def _acquire_global_slot_async(self) -> GlobalEngineSlot | None:
        """Acquire a slot without blocking the event loop or a compute runner."""
        if not self._global_capacity_enabled:
            return None
        task = asyncio.create_task(asyncio.to_thread(self._try_acquire_global_slot))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:

            async def release_late() -> None:
                with contextlib.suppress(Exception):
                    self._release_global_slot(await task)

            asyncio.create_task(release_late())
            raise

    def _track_starting_engine(self, engine: ComputeEngine) -> None:
        with self._capacity_changed:
            self._starting_engines[id(engine)] = engine

    def _untrack_starting_engine(self, engine: ComputeEngine) -> None:
        with self._capacity_changed:
            self._starting_engines.pop(id(engine), None)

    def _untrack_stopping_engine(self, engine: ComputeEngine) -> None:
        with self._capacity_changed:
            self._stopping_engines.pop(id(engine), None)

    def _managed_container_ids(self) -> set[str]:
        """Return Docker containers that belong to this manager right now."""
        with self._capacity_changed:
            engines = [
                *(info.engine for info in self._engines.values()),
                *self._warm_pool,
                *self._starting_engines.values(),
                *self._stopping_engines.values(),
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
                loop.call_soon_threadsafe(future.set_result, None)

    def _finish_engine_event(self, key: EngineIdentityKey, event: threading.Event) -> None:
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
            if error is None:
                waiter.future.set_result(owns_admission)
            else:
                waiter.future.set_exception(error)

        with contextlib.suppress(RuntimeError):
            waiter.loop.call_soon_threadsafe(resolve)

    def _reserve_capacity_locked(self) -> _CapacityAdmission | None:
        if self._warm_pool_available_locked():
            self._warm_pool_claims += 1
            return _CapacityAdmission(warm_claim=True)
        if self._capacity_used_locked() < settings.max_concurrent_engines:
            self._capacity_starts += 1
            return _CapacityAdmission()
        idle_key, idle_info = self._find_idle_engine_locked()
        if idle_key is None or idle_info is None:
            return None
        identity = self._engine_identities.pop(idle_key)
        del self._engines[idle_key]
        self._stopping_engines[id(idle_info.engine)] = idle_info.engine
        eviction_event = threading.Event()
        self._engine_events[idle_key] = eviction_event
        self._capacity_starts += 1
        return _CapacityAdmission(evicted=(idle_key, idle_info, identity), eviction_event=eviction_event)

    def _admit_spawn_waiters_locked(self) -> None:
        """Reserve available slots for queued spawns by priority, then arrival order."""
        while self._spawn_waiters:
            waiter_index = min(
                range(len(self._spawn_waiters)),
                key=lambda index: (self._spawn_waiters[index].priority, index),
            )
            waiter = self._spawn_waiters[waiter_index]
            if self._closed:
                del self._spawn_waiters[waiter_index]
                self._resolve_waiter(waiter, error=RuntimeError("Process manager is shut down"))
                continue
            if waiter.key in self._engines or waiter.key in self._engine_events:
                del self._spawn_waiters[waiter_index]
                self._resolve_waiter(waiter)
                continue
            # Same-identity work may proceed behind the same pending start. The
            # engine event serializes creation and all later callers reuse it.
            if self._spawn_admissions.get(waiter.key):
                del self._spawn_waiters[waiter_index]
                self._resolve_waiter(waiter)
                continue
            admission = self._reserve_capacity_locked()
            if admission is None:
                return
            admission.global_slot = waiter.global_slot
            waiter.global_slot = None
            del self._spawn_waiters[waiter_index]
            self._spawn_admissions.setdefault(waiter.key, deque()).append(admission)
            waiter.owns_admission = True
            self._resolve_waiter(waiter, owns_admission=True)

    def release_spawn_admission(self, identity: EngineIdentity | None, *, namespace: str | None = None, owned: bool) -> None:
        """Return an unused admission, such as when an admitted task is cancelled."""
        if identity is None or not owned:
            return
        key = self._key(identity, namespace=namespace)
        evicted: tuple[EngineIdentityKey, EngineInfo, EngineIdentity] | None = None
        eviction_event: threading.Event | None = None
        global_slot: GlobalEngineSlot | None = None
        with self._capacity_changed:
            admissions = self._spawn_admissions.get(key)
            if not admissions:
                return
            admission = admissions.popleft()
            if not admissions:
                self._spawn_admissions.pop(key, None)
            if admission.warm_claim:
                self._warm_pool_claims = max(0, self._warm_pool_claims - 1)
            else:
                self._capacity_starts = max(0, self._capacity_starts - 1)
            global_slot = admission.global_slot
            evicted = admission.evicted
            eviction_event = admission.eviction_event
            if evicted is not None and evicted[1].engine.is_process_alive():
                evicted_key, evicted_info, evicted_identity = evicted
                self._stopping_engines.pop(id(evicted_info.engine), None)
                self._engines[evicted_key] = evicted_info
                self._engine_identities[evicted_key] = evicted_identity
                evicted = None
            self._admit_spawn_waiters_locked()
        self._release_global_slot(global_slot)
        if evicted is not None:
            try:
                with contextlib.suppress(Exception):
                    evicted[1].engine.shutdown()
            finally:
                self._release_engine_slot(evicted[1].engine)
                self._untrack_stopping_engine(evicted[1].engine)
                if eviction_event is not None:
                    self._finish_engine_event(evicted[0], eviction_event)
        elif eviction_event is not None and admission.evicted is not None:
            self._release_engine_slot(admission.evicted[1].engine)
            self._untrack_stopping_engine(admission.evicted[1].engine)
            self._finish_engine_event(admission.evicted[0], eviction_event)

    def cancel_engine_job(
        self,
        identity: EngineIdentity,
        *,
        namespace: str | None = None,
        job_id: str | None = None,
    ) -> bool:
        """Cancel one request's job while leaving the shared engine running."""
        qualified_key = self._key(identity, namespace=namespace)
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

    def reserve_engine_request(self, identity: EngineIdentity, *, namespace: str | None = None) -> None:
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

    def release_engine_request(self, identity: EngineIdentity, *, namespace: str | None = None) -> None:
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

    def shutdown_engine_after_request_lease_loss(
        self,
        identity: EngineIdentity,
        *,
        namespace: str | None = None,
    ) -> bool:
        """Release an engine made useless by a disconnected request.

        A datasource-preview engine is shared, so keep it when another
        admitted request still owns it. If the disconnected request is the
        only request reservation, however, retaining the engine until the idle
        reaper leaves a dead identity occupying the local capacity budget.
        """
        qualified_key = self._key(identity, namespace=namespace)
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
            self.shutdown_engine(identity, namespace=namespace)
        return shutdown

    def can_admit_spawn(self) -> bool:
        """True if a new engine can start now (free slot, warm pool, or idle eviction)."""
        with self._capacity_changed:
            if self._closed:
                return False
            return (
                self._capacity_used_locked() < settings.max_concurrent_engines
                or self._warm_pool_available_locked()
                or self._find_idle_engine_locked()[0] is not None
            )

    async def wait_for_capacity(self) -> None:
        """Park until capacity may have freed. No compute runner involved."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        with self._capacity_changed:
            if self._closed:
                raise RuntimeError("Process manager is shut down")
            if (
                self._capacity_used_locked() < settings.max_concurrent_engines
                or self._warm_pool_available_locked()
                or self._find_idle_engine_locked()[0] is not None
            ):
                return
            self._capacity_waiters.append((loop, future))
        try:
            await future
        finally:
            with self._capacity_changed:
                self._capacity_waiters[:] = [(lp, fut) for lp, fut in self._capacity_waiters if fut is not future]

    async def await_spawn_admission(
        self,
        identity: EngineIdentity | None,
        *,
        namespace: str | None = None,
        priority: int = ENGINE_ADMISSION_PRIORITY_INTERACTIVE,
    ) -> bool:
        """Wait until this identity can run — without creating a compute runner.

        - ``None`` identity: no engine gate (request does not need a Polars engine).
        - Existing engine for identity: return immediately (reuse, no new slot).
        - Otherwise park until a free slot exists or an idle engine can be evicted.

        Only after this returns should the caller take a compute-pool thread.
        """
        if identity is None:
            return False
        key = self._key(identity, namespace=namespace)
        loop = asyncio.get_running_loop()
        while True:
            # A warm engine or a locally idle engine already owns a global
            # slot. The former is claimed directly; the latter's slot is
            # transferred during eviction. Otherwise reserve a PostgreSQL
            # slot before putting the waiter in the local admission queue.
            with self._capacity_changed:
                if self._closed:
                    raise RuntimeError("Process manager is shut down")
                if key in self._engines or key in self._engine_events:
                    return False
                warm_available = self._warm_pool_available_locked()
                idle_available = self._find_idle_engine_locked()[0] is not None

            global_slot = None
            if self._global_capacity_enabled and not warm_available and not idle_available:
                global_slot = await self._acquire_global_slot_async()
                if global_slot is None:
                    # Another manager owns every application-wide slot. Poll
                    # outside the event loop until one is released; no compute
                    # runner or database claim is held during this wait.
                    await asyncio.sleep(0.1)
                    continue

            waiter = _SpawnWaiter(
                key=key,
                loop=loop,
                future=loop.create_future(),
                priority=priority,
                global_slot=global_slot,
            )
            existing = False
            with self._capacity_changed:
                if self._closed:
                    existing = False
                elif key in self._engines or key in self._engine_events:
                    existing = True
                else:
                    self._spawn_waiters.append(waiter)
                    self._admit_spawn_waiters_locked()
            if self._closed and not existing:
                self._release_global_slot(waiter.global_slot)
                raise RuntimeError("Process manager is shut down")
            if existing:
                self._release_global_slot(waiter.global_slot)
                return False

            if not waiter.future.done():
                logger.info(
                    "Engine capacity full (%s); request priority-queued for %s (priority=%s, no runner yet)",
                    settings.max_concurrent_engines,
                    identity.resource_id,
                    priority,
                )
            try:
                owns_admission = await waiter.future
                if not owns_admission:
                    self._release_global_slot(waiter.global_slot)
                return owns_admission
            except BaseException:
                with self._capacity_changed:
                    with contextlib.suppress(ValueError):
                        self._spawn_waiters.remove(waiter)
                    self._admit_spawn_waiters_locked()
                self.release_spawn_admission(identity, namespace=namespace, owned=waiter.owns_admission)
                self._release_global_slot(waiter.global_slot)
                raise

    def _key(self, identity: EngineIdentity, namespace: str | None = None) -> EngineIdentityKey:
        resource_id = identity.resource_id.strip()
        if not resource_id:
            raise ValueError("engine identity resource_id is required")
        return EngineIdentityKey(
            namespace=namespace or get_namespace(),
            scope=identity.scope,
            reuse_policy=identity.reuse_policy,
            resource_id=resource_id,
        )

    def spawn_engine(
        self,
        identity: EngineIdentity,
        resource_config: dict | None = None,
        *,
        _reserve: bool = False,
    ) -> EngineInfo:
        """Spawn a new compute engine or reuse an existing one for the same identity."""
        normalized_config = self._normalize_config(resource_config)
        qualified_key = self._key(identity)
        namespace = qualified_key.namespace
        wait_event: threading.Event | None = None
        reused_info: EngineInfo | None = None
        shutdown_target: ComputeEngine | None = None
        changed_namespaces: set[str] = {namespace}

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
                        logger.debug("Reusing existing engine for %s", qualified_key)
                        reused_info = info
                        break

                    self._engine_events[qualified_key] = threading.Event()
                    if info is not None:
                        reason = "resource config changed" if config_changed else "engine is no longer alive"
                        logger.info("%s for engine %s, restarting", reason.capitalize(), qualified_key)
                        shutdown_target = info.engine
                        self._stopping_engines[id(shutdown_target)] = shutdown_target
                        info.current_build_id = None
                        info.current_engine_run_id = None
                        del self._engines[qualified_key]
                        self._engine_identities.pop(qualified_key, None)
                    break

            if wait_event is not None:
                wait_event.wait()
                wait_event = None

        if reused_info is not None:
            self._emit_snapshot_for_namespaces(changed_namespaces)
            return reused_info

        spawned_info: EngineInfo | None = None
        capacity_start_held = False
        warm_claim_held = False
        engine: ComputeEngine | None = None
        global_slot: GlobalEngineSlot | None = None
        extra_global_slots: list[GlobalEngineSlot] = []
        registered = False
        try:
            if shutdown_target is not None:
                try:
                    shutdown_target.shutdown()
                finally:
                    self._release_engine_slot(shutdown_target)
                    self._untrack_stopping_engine(shutdown_target)

            # Non-blocking admission: running engines only count. If full, raise
            # EngineCapacityFull so the caller parks outside the runner pool.
            with self._capacity_changed:
                admissions = self._spawn_admissions.get(qualified_key)
                admission = admissions[0] if admissions else None
            if admission is not None:
                capacity_start_held = not admission.warm_claim
                warm_claim_held = admission.warm_claim
                evict_info = admission.evicted
                eviction_event = admission.eviction_event
                global_slot = admission.global_slot
                if warm_claim_held and global_slot is not None:
                    # A warm claim already owns the candidate engine's slot;
                    # an extra slot can only come from a warm-pool/queue race.
                    extra_global_slots.append(global_slot)
                    global_slot = None
                if not warm_claim_held and self._global_capacity_enabled and global_slot is None:
                    if evict_info is not None:
                        with self._capacity_changed:
                            global_slot = self._global_engine_slots.get(id(evict_info[1].engine))
                    if global_slot is None:
                        global_slot = self._try_acquire_global_slot()
                    if global_slot is None:
                        raise EngineCapacityFull("No application-wide engine slot is available")
                with self._capacity_changed:
                    admissions = self._spawn_admissions.get(qualified_key)
                    if admissions:
                        admissions.popleft()
                        if not admissions:
                            self._spawn_admissions.pop(qualified_key, None)
            else:
                evict_info, capacity_start_held, eviction_event, warm_claim_held = self._try_claim_capacity_slot(qualified_key)
                if evict_info is not None:
                    with self._capacity_changed:
                        global_slot = self._global_engine_slots.get(id(evict_info[1].engine))
                if capacity_start_held and not warm_claim_held and global_slot is None:
                    global_slot = self._try_acquire_global_slot()
                    if self._global_capacity_enabled and global_slot is None:
                        with self._capacity_changed:
                            self._capacity_starts = max(0, self._capacity_starts - 1)
                            if evict_info is not None:
                                evicted_key, evicted_info, evicted_identity = evict_info
                                self._engines[evicted_key] = evicted_info
                                self._engine_identities[evicted_key] = evicted_identity
                                self._stopping_engines.pop(id(evicted_info.engine), None)
                        raise EngineCapacityFull("No application-wide engine slot is available")
            if evict_info is not None:
                old_slot = self._take_global_slot(evict_info[1].engine)
                if global_slot is None:
                    global_slot = old_slot
                elif old_slot is not None and old_slot is not global_slot:
                    extra_global_slots.append(old_slot)
            if not capacity_start_held and not warm_claim_held:
                logger.info(
                    "Max concurrent engines (%s) in use; deferring spawn for %s (queue, not runner)",
                    settings.max_concurrent_engines,
                    qualified_key,
                )
                raise EngineCapacityFull(f"Maximum concurrent engines limit ({settings.max_concurrent_engines}) reached")
            if evict_info is not None:
                _, idle_engine_info, _ = evict_info
                try:
                    idle_engine_info.engine.shutdown()
                finally:
                    self._release_engine_slot(idle_engine_info.engine)
                    self._untrack_stopping_engine(idle_engine_info.engine)
                    if eviction_event is not None:
                        self._finish_engine_event(evict_info[0], eviction_event)
                changed_namespaces.add(evict_info[0].namespace)

            for slot in extra_global_slots:
                self._release_global_slot(slot)
            extra_global_slots.clear()

            # Health checks are engine RPCs: pop under the lock, probe outside it.
            warm_engine: ComputeEngine | None = None
            while warm_engine is None:
                with self._capacity_changed:
                    if warm_claim_held:
                        # Transfer the warm-pool claim into a normal start
                        # ticket while health is checked outside the lock. If
                        # the warm engine is unhealthy, its replacement still
                        # owns the same global capacity slot.
                        self._warm_pool_claims = max(0, self._warm_pool_claims - 1)
                        warm_claim_held = False
                        self._capacity_starts += 1
                        capacity_start_held = True
                    candidate = self._warm_pool.popleft() if self._warm_pool else None
                    if candidate is not None:
                        self._starting_engines[id(candidate)] = candidate
                if candidate is None:
                    break
                try:
                    healthy = candidate.check_health()
                except Exception:
                    healthy = False
                if healthy:
                    warm_engine = candidate
                else:
                    candidate_slot = self._take_global_slot(candidate)
                    if global_slot is None:
                        global_slot = candidate_slot
                    elif candidate_slot is not None:
                        extra_global_slots.append(candidate_slot)
                    self._untrack_starting_engine(candidate)
                    with contextlib.suppress(Exception):
                        candidate.shutdown()

            if warm_engine is not None:
                logger.info("Claiming warm engine from pool for key %s", qualified_key)
                engine = warm_engine
                bind_id = getattr(engine, "bind_identity", None)
                if callable(bind_id):
                    bind_id(identity, resource_config=normalized_config, namespace=namespace)
                bind_cap = getattr(engine, "bind_capacity_notifier", None)
                if callable(bind_cap):
                    bind_cap(self.notify_capacity_changed)
                self._warm_replenish_trigger.set()
            else:
                logger.info("Spawning new engine for key %s", qualified_key)
                if self._global_capacity_enabled and global_slot is None:
                    global_slot = self._try_acquire_global_slot()
                    if global_slot is None:
                        raise EngineCapacityFull("No application-wide engine slot is available")
                engine = self._engine_factory(identity, normalized_config)
                self._track_starting_engine(engine)
                engine.start()
            if not engine.is_process_alive():
                engine.shutdown()
                raise RuntimeError(f"Failed to start engine for {qualified_key}")
            info = EngineInfo(engine)
            if _reserve:
                info.active_reservations = 1
            with self._capacity_changed:
                self._starting_engines.pop(id(engine), None)
                if global_slot is not None:
                    self._global_engine_slots[id(engine)] = global_slot
                    global_slot = None
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
            # A failed bind, health check, or snapshot transition must not
            # leave a live Docker container after its identity event is
            # released. Reconciliation is a backstop, not the normal cleanup
            # path for an engine that never became manager-owned.
            if engine is not None and not registered:
                with contextlib.suppress(Exception):
                    engine.shutdown()
                self._release_engine_slot(engine)
            self._release_global_slot(global_slot)
            for slot in extra_global_slots:
                self._release_global_slot(slot)
            extra_global_slots.clear()
            raise
        finally:
            if engine is not None:
                self._untrack_starting_engine(engine)
            with self._capacity_changed:
                if capacity_start_held:
                    self._capacity_starts = max(self._capacity_starts - 1, 0)
                    capacity_start_held = False
                if warm_claim_held:
                    self._warm_pool_claims = max(0, self._warm_pool_claims - 1)
                    warm_claim_held = False
                in_progress_event = self._engine_events.pop(qualified_key, None)
                if in_progress_event is not None:
                    in_progress_event.set()
            self.notify_capacity_changed()

        if spawned_info is None:
            raise RuntimeError(f"Failed to start engine for {qualified_key}")
        self._emit_snapshot_for_namespaces(changed_namespaces)
        return spawned_info

    def _configs_differ(self, old_config: dict, new_config: dict) -> bool:
        return any(old_config.get(k) != new_config.get(k) for k in _RESOURCE_KEYS)

    def _normalize_config(self, config: dict | None) -> dict:
        if not config:
            return {}
        defaults = self._get_defaults()
        return {k: v for k in _RESOURCE_KEYS if (v := config.get(k)) is not None and v != defaults.get(k)}

    def _find_idle_engine_locked(self) -> tuple[EngineIdentityKey | None, EngineInfo | None]:
        """Pick the least-recently-used engine with no reservation and no active job.

        Reads in-memory liveness only. This runs on every capacity decision
        while the engines lock is held, so it must never touch Docker.
        """
        idle_key: EngineIdentityKey | None = None
        idle_info: EngineInfo | None = None
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
        """Live engines, warm standby engines, plus in-flight starts that already hold a ticket."""
        return len(self._engines) + len(self._warm_pool) + self._capacity_starts

    def _warm_pool_available_locked(self) -> bool:
        return len(self._warm_pool) > self._warm_pool_claims

    def _try_claim_capacity_slot(
        self,
        qualified_key: EngineIdentityKey,
    ) -> tuple[tuple[EngineIdentityKey, EngineInfo, EngineIdentity] | None, bool, threading.Event | None, bool]:
        """Non-blocking capacity claim. Returns (evict_target, ticket_held, eviction_event).

        Does not park the caller. On failure returns (None, False, None) so runners
        can exit and the async queue can wait without holding a worker thread.
        """
        with self._capacity_changed:
            if self._closed:
                raise RuntimeError("Process manager is shut down")
            if self._spawn_waiters:
                return None, False, None, False
            if self._warm_pool_available_locked():
                self._warm_pool_claims += 1
                self._capacity_changed.notify_all()
                return None, True, None, True
            used = self._capacity_used_locked()
            max_engines = settings.max_concurrent_engines
            if used < max_engines:
                self._capacity_starts += 1
                self._capacity_changed.notify_all()
                return None, True, None, False
            idle_key, idle_info = self._find_idle_engine_locked()
            if idle_key is not None and idle_info is not None:
                logger.info(
                    "Max concurrent engines limit reached (%s), evicting idle engine %s in namespace %s to spawn %s",
                    max_engines,
                    idle_key.resource_id,
                    idle_key.namespace,
                    qualified_key,
                )
                del self._engines[idle_key]
                identity = self._engine_identities.pop(idle_key)
                eviction_event = threading.Event()
                self._engine_events[idle_key] = eviction_event
                self._capacity_starts += 1
                self._capacity_changed.notify_all()
                return (idle_key, idle_info, identity), True, eviction_event, False
            return None, False, None, False

    def get_or_create_engine(self, identity: EngineIdentity, resource_config: dict | None = None) -> ComputeEngine:
        info = self.spawn_engine(identity, resource_config=resource_config)
        return info.engine

    @contextlib.contextmanager
    def acquire_engine(self, identity: EngineIdentity, resource_config: dict | None = None) -> Iterator[ComputeEngine]:
        """Reserve an engine until its caller has submitted work to it."""
        qualified_key = self._key(identity)
        info = self.spawn_engine(identity, resource_config=resource_config, _reserve=True)
        try:
            yield info.engine
        finally:
            with self._capacity_changed:
                current = self._engines.get(qualified_key)
                if current is info:
                    current.active_reservations = max(current.active_reservations - 1, 0)
            self.notify_capacity_changed()

    def restart_engine_with_config(self, identity: EngineIdentity, resource_config: dict) -> EngineInfo:
        identity_key = self._key(identity)
        logger.info("Restarting engine for %s with new config: %s", identity_key, resource_config)
        self.shutdown_engine(identity, emit_snapshot=False)
        return self.spawn_engine(identity, resource_config=resource_config)

    def get_engine(self, identity: EngineIdentity, *, namespace: str | None = None) -> ComputeEngine | None:
        qualified_key = self._key(identity, namespace=namespace)
        with self._engines_lock:
            info = self._engines.get(qualified_key)
            return info.engine if info else None

    def get_engine_info(self, identity: EngineIdentity, *, namespace: str | None = None) -> EngineInfo | None:
        qualified_key = self._key(identity, namespace=namespace)
        with self._engines_lock:
            return self._engines.get(qualified_key)

    def set_engine_runtime_context(self, identity: EngineIdentity, *, current_build_id: str | None, current_engine_run_id: str | None) -> None:
        qualified_key = self._key(identity)
        namespace = qualified_key.namespace
        changed = False
        with self._engines_lock:
            info = self._engines.get(qualified_key)
            if info is not None:
                if info.current_build_id != current_build_id:
                    info.current_build_id = current_build_id
                    changed = True
                if info.current_engine_run_id != current_engine_run_id:
                    info.current_engine_run_id = current_engine_run_id
                    changed = True
        if changed:
            self._emit_snapshot_for_namespaces({namespace})

    def _get_defaults(self) -> dict:
        return {
            "max_threads": settings.polars_cores_available,
            "max_memory_mb": settings.polars_max_memory_mb,
            "streaming_chunk_size": settings.polars_streaming_chunk_size,
        }

    def get_engine_status(self, identity: EngineIdentity, *, defaults: dict | None = None) -> EngineStatusInfo:
        if defaults is None:
            defaults = self._get_defaults()

        qualified_key = self._key(identity)
        with self._engines_lock:
            info = self._engines.get(qualified_key)
            persisted_identity = self._engine_identities.get(qualified_key, identity)
            if info is None:
                return EngineStatusInfo(
                    analysis_id=_engine_identity_analysis_id(persisted_identity) or "",
                    resource_id=persisted_identity.resource_id,
                    status=EngineStatus.TERMINATED,
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
                    datasource_id=_engine_identity_datasource_id(persisted_identity),
                    build_id=_engine_identity_build_id(persisted_identity),
                    current_build_id=_engine_identity_build_id(persisted_identity),
                    current_engine_run_id=None,
                )

            # Status is a read of tracked state, not a probe: snapshots cover
            # every engine in the namespace and run inline on engine lifecycle
            # changes. The heartbeat loop owns liveness and marks an engine dead
            # as soon as it stops answering.
            engine = info.engine
            is_alive = engine.last_known_alive
            resource_config = (self._normalize_config(engine.resource_config) or None) if engine.resource_config else None
            effective_resources = engine.effective_resources or None

            return EngineStatusInfo(
                analysis_id=_engine_identity_analysis_id(persisted_identity) or "",
                resource_id=persisted_identity.resource_id,
                status=EngineStatus.HEALTHY if is_alive else EngineStatus.TERMINATED,
                container_id=getattr(engine, "container_id", None),
                image_digest=getattr(engine, "image_digest", None),
                lifecycle_status=getattr(engine, "lifecycle_status", "running" if engine.current_job_id else "idle"),
                termination_reason=getattr(engine, "termination_reason", None),
                exit_code=getattr(engine, "exit_code", None),
                oom_killed=getattr(engine, "oom_killed", None),
                supervisor_id=self._supervisor_id,
                owner_id=_engine_identity_build_id(persisted_identity) or self._supervisor_id,
                last_activity=info.last_activity.isoformat(),
                current_job_id=engine.current_job_id,
                resource_config=resource_config,
                effective_resources=effective_resources,
                defaults=defaults,
                scope=_engine_scope_value(persisted_identity),
                reuse_policy=_engine_reuse_policy_value(persisted_identity),
                datasource_id=_engine_identity_datasource_id(persisted_identity),
                build_id=_engine_identity_build_id(persisted_identity),
                current_build_id=info.current_build_id or _engine_identity_build_id(persisted_identity),
                current_engine_run_id=info.current_engine_run_id,
            )

    def shutdown_engine(self, identity: EngineIdentity, *, namespace: str | None = None, emit_snapshot: bool = True) -> None:
        qualified_key = self._key(identity, namespace=namespace)
        resolved_namespace = qualified_key.namespace
        info: EngineInfo | None = None
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
            self._release_engine_slot(info.engine)
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

    def shutdown_all(self) -> None:
        self._reaper_stop.set()
        self._warm_replenish_trigger.set()
        if self._reaper_thread is not None and self._reaper_thread.is_alive():
            self._reaper_thread.join(timeout=1.0)
        if self._warm_replenish_thread is not None and self._warm_replenish_thread.is_alive():
            self._warm_replenish_thread.join(timeout=1.0)
        with self._capacity_changed:
            self._closed = True
            warm_to_stop = list(self._warm_pool)
            self._warm_pool.clear()
            self._warm_pool_claims = 0
            for engine in warm_to_stop:
                self._stopping_engines[id(engine)] = engine
            spawn_events = list(self._engine_events.values())
            capacity_waiters = list(self._capacity_waiters)
            self._capacity_waiters.clear()
            queued_waiters = list(self._spawn_waiters)
            self._spawn_waiters.clear()
            queued_global_slots = [waiter.global_slot for waiter in queued_waiters if waiter.global_slot is not None]
            admitted_evictions = [
                admission.evicted for admissions in self._spawn_admissions.values() for admission in admissions if admission.evicted is not None
            ]
            admitted_global_slots = [
                admission.global_slot for admissions in self._spawn_admissions.values() for admission in admissions if admission.global_slot is not None
            ]
            self._spawn_admissions.clear()
            self._request_reservations.clear()
            self._capacity_starts = 0
            self._capacity_changed.notify_all()
        for waiter in queued_waiters:
            self._resolve_waiter(waiter, error=RuntimeError("Process manager is shut down"))
        for slot in [*queued_global_slots, *admitted_global_slots]:
            self._release_global_slot(slot)
        for loop, future in capacity_waiters:

            def reject(waiting: asyncio.Future[None] = future) -> None:
                if not waiting.done():
                    waiting.set_exception(RuntimeError("Process manager is shut down"))

            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(reject)
        for spawn_event in spawn_events:
            spawn_event.wait()
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
                self._release_engine_slot(info.engine)
                self._untrack_stopping_engine(info.engine)
        for _key, info, _identity in admitted_evictions:
            try:
                info.engine.shutdown()
            finally:
                self._release_engine_slot(info.engine)
                self._untrack_stopping_engine(info.engine)
        for warm_eng in warm_to_stop:
            try:
                with contextlib.suppress(Exception):
                    warm_eng.shutdown()
            finally:
                self._release_engine_slot(warm_eng)
                self._untrack_stopping_engine(warm_eng)
        if self._global_capacity is not None:
            self._global_capacity.close()
        if changed_namespaces:
            self._emit_snapshot_for_namespaces(changed_namespaces)

    def list_engines(self) -> list[str]:
        namespace = get_namespace()
        with self._engines_lock:
            return [key.resource_id for key in self._engines if key.namespace == namespace]

    def list_all_engine_statuses(self) -> list[EngineStatusInfo]:
        return self._list_engine_statuses_for_namespace(get_namespace())

    def _list_engine_statuses_for_namespace(self, namespace: str) -> list[EngineStatusInfo]:
        defaults = self._get_defaults()
        with self._engines_lock:
            identities = [self._engine_identities[key] for key in self._engines if key.namespace == namespace]
        return [self.get_engine_status(identity, defaults=defaults) for identity in identities]

    def _emit_snapshot_for_namespaces(self, namespaces: set[str]) -> None:
        if self._on_snapshot is None:
            return
        for namespace in sorted(namespaces):
            token = set_namespace_context(namespace)
            try:
                self._on_snapshot(self._list_engine_statuses_for_namespace(namespace))
            finally:
                reset_namespace(token)

    def _spawn_warm_engine(self, factory: Callable[[], ComputeEngine]) -> ComputeEngine | None:
        """Start one warm engine, reserving capacity. Returns None on failure."""
        new_engine: ComputeEngine | None = None
        global_slot = self._try_acquire_global_slot()
        if self._global_capacity_enabled and global_slot is None:
            return None
        try:
            new_engine = factory()
            self._track_starting_engine(new_engine)
            new_engine.start()
            if global_slot is not None:
                self._track_global_slot(new_engine, global_slot)
                global_slot = None
            return new_engine
        except Exception:
            logger.warning("Failed to start warm engine for pool", exc_info=True)
            if new_engine is not None:
                with contextlib.suppress(Exception):
                    new_engine.shutdown()
                self._release_engine_slot(new_engine)
            self._release_global_slot(global_slot)
            if new_engine is not None:
                self._untrack_starting_engine(new_engine)
            return None

    def _replenish_warm_pool_loop(self) -> None:
        while not self._closed and not self._reaper_stop.is_set():
            self._warm_replenish_trigger.wait(timeout=1.0)
            self._warm_replenish_trigger.clear()
            if self._closed or self._reaper_stop.is_set() or self._warm_engine_factory is None:
                break
            factory = self._warm_engine_factory
            # Refill the whole deficit concurrently: a burst of claims drains the
            # pool faster than sequential spawns can refill it, and every wait
            # for a fresh spawn is a preview/build paying full container boot.
            while not self._closed and not self._reaper_stop.is_set():
                with self._capacity_changed:
                    # Warm replacement is best-effort. It must not consume the
                    # last available capacity while an interactive request is
                    # already waiting for a new identity. The request will
                    # trigger replenishment again after it claims a slot.
                    if any(waiter.priority == ENGINE_ADMISSION_PRIORITY_INTERACTIVE for waiter in self._spawn_waiters):
                        break
                    target_warm = min(
                        self._warm_pool_size,
                        max(0, settings.max_concurrent_engines),
                    )
                    current_warm = len(self._warm_pool)
                    used = self._capacity_used_locked()
                    headroom = settings.max_concurrent_engines - used
                    # Never reserve past max_concurrent_engines: the spawns below
                    # are all started at once, so the whole batch has to fit.
                    batch_size = min(target_warm - current_warm, headroom)
                    if batch_size <= 0:
                        break
                    self._capacity_starts += batch_size

                with ThreadPoolExecutor(max_workers=batch_size) as pool:
                    engines = [future.result() for future in [pool.submit(self._spawn_warm_engine, factory) for _ in range(batch_size)]]

                with self._capacity_changed:
                    self._capacity_starts = max(0, self._capacity_starts - batch_size)
                    for engine in engines:
                        if engine is None:
                            continue
                        if self._closed or self._reaper_stop.is_set():
                            with contextlib.suppress(Exception):
                                engine.shutdown()
                            self._release_engine_slot(engine)
                            self._starting_engines.pop(id(engine), None)
                            continue
                        self._starting_engines.pop(id(engine), None)
                        self._warm_pool.append(engine)
                    self._capacity_changed.notify_all()
                if any(engine is None for engine in engines):
                    # Back off outside the lock: engines lock is the runtime's
                    # hot path and holding it here stalls every claim.
                    time.sleep(1.0)

    def _reap_idle_engines_loop(self) -> None:
        while not self._reaper_stop.wait(self._idle_reap_interval_seconds):
            self._reap_idle_engines_once()
            if self._uses_docker_runtime:
                try:
                    reconcile_deployment_containers(
                        supervisor_id=self._supervisor_id,
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
        stale: list[tuple[EngineIdentityKey, EngineInfo, threading.Event]] = []
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
                self._release_engine_slot(info.engine)
                self._untrack_stopping_engine(info.engine)
                self._finish_engine_event(key, lifecycle_event)
        if changed_namespaces:
            self._emit_snapshot_for_namespaces(changed_namespaces)
