import contextlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from dataforge_protocol import compute_pb2, enums_pb2
from runtime.compute_engine import PolarsComputeEngine
from runtime.config import settings
from runtime.models.compute.base import ComputeEngine, EngineStatusInfo
from runtime.models.compute.schemas import EngineStatus
from runtime.namespace import get_namespace, reset_namespace, set_namespace_context

logger = logging.getLogger(__name__)

_RESOURCE_KEYS = frozenset({"max_threads", "max_memory_mb", "streaming_chunk_size"})

EngineFactory = Callable[[str, dict | None], ComputeEngine]
EngineSnapshotListener = Callable[[list[EngineStatusInfo]], None]
EngineIdentity = compute_pb2.EngineIdentity
EngineIdentityInput = EngineIdentity | str


@dataclass(frozen=True, slots=True)
class EngineIdentityKey:
    namespace: str
    scope: int
    reuse_policy: int
    resource_id: str


def _default_engine_factory(resource_id: str, resource_config: dict | None = None) -> ComputeEngine:
    return PolarsComputeEngine(resource_id, resource_config=resource_config)


def _required_identity_id(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def analysis_interactive_engine_identity(analysis_id: str) -> EngineIdentity:
    return compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        analysis_id=_required_identity_id(analysis_id, "analysis_id"),
    )


def datasource_preview_engine_identity(datasource_id: str) -> EngineIdentity:
    return compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        datasource_id=_required_identity_id(datasource_id, "datasource_id"),
    )


def build_engine_identity(build_id: str) -> EngineIdentity:
    return compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_BUILD,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_EXCLUSIVE,
        build_id=_required_identity_id(build_id, "build_id"),
    )


def engine_identity_resource_id(identity: EngineIdentity) -> str:
    if identity.scope == enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE and identity.HasField("analysis_id"):
        return identity.analysis_id
    if identity.scope == enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW and identity.HasField("datasource_id"):
        return identity.datasource_id
    if identity.scope == enums_pb2.ENGINE_SCOPE_BUILD and identity.HasField("build_id"):
        return identity.build_id
    raise ValueError("engine identity is missing the resource id required by its scope")


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

    def touch(self) -> None:
        self.last_activity = datetime.now(UTC)


class ProcessManager:
    def __init__(
        self,
        engine_factory: EngineFactory = _default_engine_factory,
        on_snapshot: EngineSnapshotListener | None = None,
    ) -> None:
        self._engines: dict[EngineIdentityKey, EngineInfo] = {}
        self._engine_identities: dict[EngineIdentityKey, EngineIdentity] = {}
        self._engines_lock = threading.Lock()
        self._engine_events: dict[EngineIdentityKey, threading.Event] = {}
        self._engine_factory = engine_factory
        self._on_snapshot = on_snapshot
        self._idle_ttl_seconds = settings.engine_idle_ttl_seconds
        self._idle_reap_interval_seconds = settings.engine_idle_reap_interval_seconds
        self._reaper_stop = threading.Event()
        self._reaper_thread: threading.Thread | None = None
        if self._idle_ttl_seconds > 0:
            self._reaper_thread = threading.Thread(target=self._reap_idle_engines_loop, name="engine-idle-reaper", daemon=True)
            self._reaper_thread.start()

    def _resolve_identity(self, identity: EngineIdentityInput) -> EngineIdentity:
        if isinstance(identity, EngineIdentity):
            return identity
        return analysis_interactive_engine_identity(identity)

    def _key(self, identity: EngineIdentityInput, namespace: str | None = None) -> EngineIdentityKey:
        resolved = self._resolve_identity(identity)
        return EngineIdentityKey(
            namespace=namespace or get_namespace(),
            scope=resolved.scope,
            reuse_policy=resolved.reuse_policy,
            resource_id=engine_identity_resource_id(resolved),
        )

    def spawn_engine(self, identity: EngineIdentityInput, resource_config: dict | None = None) -> EngineInfo:
        """Spawn a new compute engine or reuse an existing one for the same identity."""
        engine_identity = self._resolve_identity(identity)
        resource_id = engine_identity_resource_id(engine_identity)
        normalized_config = self._normalize_config(resource_config)
        qualified_key = self._key(engine_identity)
        namespace = qualified_key.namespace
        wait_event: threading.Event | None = None
        reused_info: EngineInfo | None = None
        shutdown_target: ComputeEngine | None = None
        changed_namespaces: set[str] = {namespace}

        while True:
            with self._engines_lock:
                in_progress_event = self._engine_events.get(qualified_key)
                if in_progress_event is not None:
                    wait_event = in_progress_event
                else:
                    info = self._engines.get(qualified_key)
                    if info and not self._configs_differ(
                        self._normalize_config(info.engine.resource_config),
                        normalized_config,
                    ):
                        info.touch()
                        logger.debug("Reusing existing engine for %s", qualified_key)
                        reused_info = info
                        break

                    self._engine_events[qualified_key] = threading.Event()
                    if info is not None:
                        logger.info("Resource config changed for engine %s, restarting", qualified_key)
                        shutdown_target = info.engine
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
        try:
            if shutdown_target is not None:
                shutdown_target.shutdown()

            evict_target: tuple[EngineIdentityKey, EngineInfo] | None = None
            with self._engines_lock:
                if len(self._engines) >= settings.max_concurrent_engines:
                    idle_key: EngineIdentityKey | None = None
                    idle_info: EngineInfo | None = None
                    for active_key, info in self._engines.items():
                        engine = info.engine
                        if engine.current_job_id and engine.is_process_alive():
                            continue
                        if idle_info is not None and info.last_activity >= idle_info.last_activity:
                            continue
                        idle_key = active_key
                        idle_info = info
                    if idle_key is not None and idle_info is not None:
                        logger.info(
                            "Max concurrent engines limit reached (%s), evicting idle engine %s in namespace %s to spawn %s",
                            settings.max_concurrent_engines,
                            idle_key.resource_id,
                            idle_key.namespace,
                            qualified_key,
                        )
                        evict_target = idle_key, idle_info
                        del self._engines[idle_key]
                        self._engine_identities.pop(idle_key, None)
                        changed_namespaces.add(idle_key.namespace)
                    else:
                        logger.warning(
                            "Max concurrent engines limit reached (%s), cannot spawn engine for %s",
                            settings.max_concurrent_engines,
                            qualified_key,
                        )
                        raise RuntimeError(
                            f"Maximum concurrent engines limit ({settings.max_concurrent_engines}) reached. "
                            "Please wait for existing analyses to complete or increase MAX_CONCURRENT_ENGINES.",
                        )

            if evict_target is not None:
                _, evicted_info = evict_target
                evicted_info.engine.shutdown()

            with self._engines_lock:
                logger.info(
                    "Spawning new engine for key %s (%s/%s)",
                    qualified_key,
                    len(self._engines) + 1,
                    settings.max_concurrent_engines,
                )
                engine = self._engine_factory(resource_id, normalized_config)
                engine.start()
                if not engine.is_process_alive():
                    engine.shutdown()
                    raise RuntimeError(f"Failed to start engine for {qualified_key}")
                info = EngineInfo(engine)
                self._engines[qualified_key] = info
                self._engine_identities[qualified_key] = engine_identity
                spawned_info = info
                logger.info("Engine spawned successfully for %s", qualified_key)
        finally:
            with self._engines_lock:
                in_progress_event = self._engine_events.pop(qualified_key, None)
                if in_progress_event is not None:
                    in_progress_event.set()

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

    def get_or_create_engine(self, identity: EngineIdentityInput, resource_config: dict | None = None) -> ComputeEngine:
        info = self.spawn_engine(identity, resource_config=resource_config)
        return info.engine

    def restart_engine_with_config(self, identity: EngineIdentityInput, resource_config: dict) -> EngineInfo:
        identity_key = self._key(identity)
        logger.info("Restarting engine for %s with new config: %s", identity_key, resource_config)
        self.shutdown_engine(identity, emit_snapshot=False)
        return self.spawn_engine(identity, resource_config=resource_config)

    def get_engine(self, identity: EngineIdentityInput, *, namespace: str | None = None) -> ComputeEngine | None:
        qualified_key = self._key(identity, namespace=namespace)
        with self._engines_lock:
            info = self._engines.get(qualified_key)
            return info.engine if info else None

    def get_engine_info(self, identity: EngineIdentityInput, *, namespace: str | None = None) -> EngineInfo | None:
        qualified_key = self._key(identity, namespace=namespace)
        with self._engines_lock:
            return self._engines.get(qualified_key)

    def set_engine_runtime_context(self, identity: EngineIdentityInput, *, current_build_id: str | None, current_engine_run_id: str | None) -> None:
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
            "max_threads": settings.polars_max_threads,
            "max_memory_mb": settings.polars_max_memory_mb,
            "streaming_chunk_size": settings.polars_streaming_chunk_size,
        }

    def get_engine_status(self, identity: EngineIdentityInput, *, defaults: dict | None = None) -> EngineStatusInfo:
        if defaults is None:
            defaults = self._get_defaults()

        engine_identity = self._resolve_identity(identity)
        qualified_key = self._key(engine_identity)
        with self._engines_lock:
            info = self._engines.get(qualified_key)
            persisted_identity = self._engine_identities.get(qualified_key, engine_identity)
            if info is None:
                return EngineStatusInfo(
                    analysis_id=_engine_identity_analysis_id(persisted_identity) or "",
                    resource_id=engine_identity_resource_id(persisted_identity),
                    status=EngineStatus.TERMINATED,
                    process_id=None,
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

            engine = info.engine
            engine.check_health()
            is_alive = engine.is_process_alive()
            resource_config = (self._normalize_config(engine.resource_config) or None) if engine.resource_config else None
            effective_resources = engine.effective_resources or None

            return EngineStatusInfo(
                analysis_id=_engine_identity_analysis_id(persisted_identity) or "",
                resource_id=engine_identity_resource_id(persisted_identity),
                status=EngineStatus.HEALTHY if is_alive else EngineStatus.TERMINATED,
                process_id=engine.process_id,
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

    def shutdown_engine(self, identity: EngineIdentityInput, *, namespace: str | None = None, emit_snapshot: bool = True) -> None:
        qualified_key = self._key(identity, namespace=namespace)
        resolved_namespace = qualified_key.namespace
        info: EngineInfo | None = None
        with self._engines_lock:
            info = self._engines.pop(qualified_key, None)
            self._engine_identities.pop(qualified_key, None)
        if info is None:
            logger.debug("No engine found to shutdown for %s", qualified_key)
            return
        logger.info("Shutting down engine for %s", qualified_key)
        info.engine.shutdown()
        logger.info("Engine shutdown complete for %s", qualified_key)
        if emit_snapshot:
            self._emit_snapshot_for_namespaces({resolved_namespace})

    def shutdown_all(self) -> None:
        self._reaper_stop.set()
        if self._reaper_thread is not None and self._reaper_thread.is_alive():
            self._reaper_thread.join(timeout=1.0)
        with self._engines_lock:
            shutdown_targets = list(self._engines.items())
            self._engines.clear()
            self._engine_identities.clear()
        changed_namespaces = {key.namespace for key, _ in shutdown_targets}
        for key, info in shutdown_targets:
            logger.info("Shutting down engine for %s", key)
            info.engine.shutdown()
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

    def _reap_idle_engines_loop(self) -> None:
        while not self._reaper_stop.wait(self._idle_reap_interval_seconds):
            self._reap_idle_engines_once()

    def _reap_idle_engines_once(self) -> None:
        now = datetime.now(UTC)
        stale: list[tuple[EngineIdentityKey, EngineInfo]] = []
        changed_namespaces: set[str] = set()
        with self._engines_lock:
            for key, info in list(self._engines.items()):
                engine = info.engine
                is_alive = engine.is_process_alive()
                is_busy = bool(engine.current_job_id and is_alive)
                idle_seconds = (now - info.last_activity).total_seconds()
                if is_alive and (is_busy or idle_seconds < self._idle_ttl_seconds):
                    continue
                stale.append((key, info))
                del self._engines[key]
                self._engine_identities.pop(key, None)
                changed_namespaces.add(key.namespace)
        for key, info in stale:
            with contextlib.suppress(Exception):
                logger.info("Reaping idle engine %s", key)
                info.engine.shutdown()
        if changed_namespaces:
            self._emit_snapshot_for_namespaces(changed_namespaces)
