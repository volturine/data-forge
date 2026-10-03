from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Collection
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import docker
import grpc
from google.protobuf import json_format

from dataforge_protocol import compute_pb2, engine_runtime_pb2, engine_runtime_pb2_grpc, enums_pb2
from runtime.compute_request_context import get_compute_request_id
from runtime.config import settings
from runtime.domain.compute.base import ComputeEngine, EngineProgressEvent, EngineResult
from runtime.engine_credentials import ObjectStoreCredentials, resolve_engine_credentials
from runtime.engine_server import ENGINE_PROTOCOL_VERSION
from runtime.export_formats import get_export_format
from runtime.json_values import encode_json_bytes
from runtime.namespace import get_namespace
from runtime.object_store import delete_object, download_file, object_store_url, presigned_put_url

logger = logging.getLogger(__name__)

_ENGINE_TOKEN_METADATA_KEY = "x-engine-token"
_ENGINE_APPLICATION_VERSION = "engine"
_COORDINATOR_GENERATION_LABEL = "io.dataforge.coordinator-generation"
_MIB = 1024 * 1024
_SLOW_ENGINE_START_SECONDS = 5.0
# Relative scheduling weight only (not a cap): one engine gets 1/16 the weight
# of an API, runtime, database, or worker-manager service under CPU contention.
_COMPUTE_ENGINE_CPU_SHARES = 128
_IMAGE_DIGEST_RE = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
_ENGINE_CHANNEL_OPTIONS = (
    ("grpc.max_send_message_length", 128 * 1024 * 1024),
    ("grpc.max_receive_message_length", 128 * 1024 * 1024),
    ("grpc.initial_reconnect_backoff_ms", 100),
    ("grpc.max_reconnect_backoff_ms", 1000),
)
_docker_runtime_lock = threading.Lock()
_cached_daemon_cpu_count: int | None = None
_validated_image_ref: str | None = None
_validated_image_id: str | None = None

# Docker inspections are the most frequent engine I/O in the runtime (capacity
# decisions, status snapshots, idle reaping). One second of staleness is
# invisible to those decisions and keeps the daemon off the hot path.
_LIVENESS_CACHE_SECONDS = 1.0
_validated_network: str | None = None


def _warn_unpinned_engine_image() -> None:
    """Report an unpinned engine image once, at worker startup.

    Digest pinning keeps every engine launch on a byte-identical image, but tag
    references (custom engine builds with extra libraries) remain supported: the
    resolved image id is recorded per engine either way. This is configuration,
    so it is checked when the runtime is validated, not on every launch — at
    engine-spawn rates the warning buries every other line in the log.
    """
    if settings.prod_mode_enabled and _IMAGE_DIGEST_RE.fullmatch(settings.engine_image) is None:
        logger.warning(
            "ENGINE_IMAGE %s is not digest-pinned; engines may drift across launches. Prefer a repository@sha256:<digest> reference.",
            settings.engine_image,
        )


def _resolve_launch_context(client: Any) -> tuple[int | None, str]:
    """Cache daemon/image/network lookups across engine starts on this worker.

    Each Docker API round-trip is cheap alone but multiplies across hundreds of
    e2e engine spawns. Image and network are immutable for a worker process.
    """
    global _cached_daemon_cpu_count, _validated_image_ref, _validated_image_id, _validated_network
    with _docker_runtime_lock:
        if _cached_daemon_cpu_count is None:
            ncpu = client.info().get("NCPU")
            _cached_daemon_cpu_count = ncpu if isinstance(ncpu, int) else 0
        if _validated_image_ref != settings.engine_image or not _validated_image_id:
            image = client.images.get(settings.engine_image)
            _validated_image_ref = settings.engine_image
            _validated_image_id = str(image.id)
        if _validated_network != settings.engine_docker_network:
            client.networks.get(settings.engine_docker_network)
            _validated_network = settings.engine_docker_network
        daemon_cpu = _cached_daemon_cpu_count if _cached_daemon_cpu_count and _cached_daemon_cpu_count > 0 else None
        assert _validated_image_id is not None
        return daemon_cpu, _validated_image_id


def validate_engine_runtime_readiness() -> None:
    """Fail before worker registration if Docker or launch inputs are unavailable."""
    _warn_unpinned_engine_image()
    client: Any = docker.DockerClient(base_url=settings.engine_docker_host)  # type: ignore[attr-defined]
    try:
        _resolve_launch_context(client)
    finally:
        client.close()


def reconcile_deployment_containers(
    *,
    supervisor_id: str | None = None,
    coordinator_generation: int | None = None,
    coordinator_guard: Callable[[], None] | None = None,
    remove_running: bool = True,
    keep_container_ids: Collection[str] = (),
    running_grace_seconds: float = 0,
) -> int:
    """Remove owned orphan or stopped containers within this deployment.

    Startup reconciliation may sweep all non-owned containers. A live worker
    passes the manager's current container IDs and a grace period for running
    containers. That protects a container created after the Docker snapshot
    but before it can be registered in the manager, while still retiring
    containers that the manager has lost.
    """
    client: Any = docker.DockerClient(base_url=settings.engine_docker_host)  # type: ignore[attr-defined]
    removed = 0
    try:
        if coordinator_guard is not None:
            coordinator_guard()
        labels = ["io.dataforge.managed=true", f"io.dataforge.deployment={settings.deployment_id}"]
        if supervisor_id is not None and coordinator_generation is None:
            labels.append(f"io.dataforge.supervisor={supervisor_id}")
        containers = client.api.containers(all=True, filters={"label": labels})
        for container in containers:
            container_id = str(container["Id"])
            if container_id in keep_container_ids:
                continue
            container_labels = container.get("Labels") or {}
            container_generation = container_labels.get(_COORDINATOR_GENERATION_LABEL) if isinstance(container_labels, dict) else None
            if coordinator_generation is not None and container_generation != str(coordinator_generation):
                if not remove_running and container.get("State") not in {"dead", "exited"}:
                    continue
                if coordinator_guard is not None:
                    coordinator_guard()
                try:
                    client.api.remove_container(container_id, force=True)
                    removed += 1
                except Exception:
                    logger.warning(
                        "Failed to remove stale-generation engine container %s (generation=%s current=%s)",
                        container_id[:12],
                        container_generation or "missing",
                        coordinator_generation,
                        exc_info=True,
                    )
                continue
            state = container.get("State")
            if not remove_running and state not in {"dead", "exited"}:
                continue
            if remove_running and state not in {"dead", "exited"} and running_grace_seconds > 0:
                created_at_raw = container_labels.get("io.dataforge.created-at") if isinstance(container_labels, dict) else None
                try:
                    created_at = datetime.fromisoformat(str(created_at_raw)) if created_at_raw else None
                except ValueError:
                    created_at = None
                if created_at is None or (datetime.now(UTC) - created_at).total_seconds() < running_grace_seconds:
                    continue
            if coordinator_guard is not None:
                coordinator_guard()
            try:
                client.api.remove_container(container_id, force=True)
                removed += 1
            except Exception:
                logger.warning(
                    "Failed to remove reconciled engine container %s (state=%s)",
                    container_id[:12],
                    state,
                    exc_info=True,
                )
    finally:
        client.close()
    return removed


def _identity_scope(identity: compute_pb2.EngineIdentity) -> str:
    return enums_pb2.EngineScope.Name(identity.scope).removeprefix("ENGINE_SCOPE_").lower()


def _safe_name(value: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
    return normalized or "engine"


def _container_name(*, identity: compute_pb2.EngineIdentity, namespace: str) -> str:
    payload = f"{namespace}:{identity.scope}:{identity.resource_id}:{uuid.uuid4()}".encode()
    suffix = sha256(payload).hexdigest()[:12]
    # Docker DNS resolves container names as DNS labels, capped at 63 chars.
    # The full-identity hash suffix keeps names unique when the namespace or
    # resource id parts are truncated.
    prefix = "dataforge-engine-"
    ns_part = _safe_name(namespace)[:15]
    resource_part = _safe_name(identity.resource_id)[:15]
    return f"{prefix}{ns_part}-{resource_part}-{suffix}"[:63]


def _effective_resources(resource_config: dict[str, object], *, runtime_cpu_count: int | None = None) -> dict[str, int]:
    available_threads = settings.polars_cores_available or runtime_cpu_count or os.cpu_count() or 1
    max_threads = resource_config.get("max_threads", available_threads)
    max_memory_mb = resource_config.get("max_memory_mb", settings.polars_max_memory_mb)
    streaming_chunk_size = resource_config.get("streaming_chunk_size", settings.polars_streaming_chunk_size)
    values = {
        "max_threads": max_threads if isinstance(max_threads, int) and max_threads > 0 else available_threads,
        "max_memory_mb": max_memory_mb if isinstance(max_memory_mb, int) and max_memory_mb >= 0 else 0,
        "streaming_chunk_size": streaming_chunk_size if isinstance(streaming_chunk_size, int) and streaming_chunk_size >= 0 else 0,
    }
    values["max_threads"] = min(values["max_threads"], available_threads)
    return values


def _container_nano_cpus(max_threads: int) -> int | None:
    """Translate thread budget into Docker CPU quota.

    Production compose workers run engines on a dedicated runtime network and
    enforce hard CPU limits. Host-connected topologies (local/e2e harnesses)
    share cores with the API, worker, and browser, so hard nano_cpu quotas are
    omitted there; Polars still honors POLARS_MAX_THREADS inside the container.
    """
    if max_threads <= 0:
        return None
    if settings.engine_connect_host:
        return None
    return max(100_000_000, max_threads * 1_000_000_000)


def _engine_object_store_endpoint() -> str:
    if settings.engine_object_store_endpoint:
        return settings.engine_object_store_endpoint
    endpoint = settings.object_store_endpoint
    if settings.engine_connect_host and endpoint.startswith("http://127.0.0.1"):
        return endpoint.replace("http://127.0.0.1", "http://host.docker.internal", 1)
    if settings.engine_connect_host and endpoint.startswith("http://localhost"):
        return endpoint.replace("http://localhost", "http://host.docker.internal", 1)
    return endpoint


def _container_rpc_target(container: Any) -> str:
    """Return the unique Docker-DNS address; gRPC readiness handles startup."""
    # Container names are unique per launch and Docker DNS resolves them. Do
    # not poll Docker's API here: channel readiness below already waits for the
    # listener, while repeated reloads multiply daemon traffic during bursts.
    name = str(getattr(container, "name", "")).lstrip("/")
    if not name:
        raise RuntimeError("Docker did not return a name for the engine container")
    return f"{name}:{settings.engine_rpc_port}"


# Credential bootstrap is passed in-memory via gRPC Initialize RPC, eliminating exec_run.


class DockerComputeEngine(ComputeEngine):
    def __init__(
        self,
        identity: compute_pb2.EngineIdentity | None = None,
        resource_config: dict[str, object] | None = None,
        *,
        namespace: str | None = None,
        supervisor_id: str = "worker",
        coordinator_generation: int | None = None,
        coordinator_guard: Callable[[], None] | None = None,
    ) -> None:
        self.identity = identity if identity is not None else compute_pb2.EngineIdentity(resource_id="")
        self.analysis_id = self.identity.resource_id
        self.resource_config = resource_config or {}
        self.effective_resources: dict[str, object] = {}
        self.current_job_id: str | None = None
        self._namespace = namespace or get_namespace()
        self._supervisor_id = supervisor_id
        self._coordinator_generation = coordinator_generation
        self._coordinator_guard = coordinator_guard
        self._client: Any | None = None  # docker-py does not publish Python 3.14 type stubs.
        self._container: Any | None = None
        self._container_id: str | None = None
        self._channel: grpc.Channel | None = None
        self._stub: engine_runtime_pb2_grpc.PolarsEngineServiceStub | None = None
        self._rpc_target: str | None = None
        self._token = ""
        self._alive = False
        self._shutdown_requested = False
        self._is_warm_worker = identity is None
        self.image_digest: str | None = None
        self.exit_code: int | None = None
        self.oom_killed: bool | None = None
        self.termination_reason: str | None = None
        self._lock = threading.RLock()
        # Liveness is tracked separately from the lifecycle lock: start(),
        # bind_identity() and shutdown() hold _lock for as long as a container
        # boot takes, and no status or capacity decision may queue behind that.
        self._liveness_lock = threading.Lock()
        self._liveness_checked_at = 0.0
        self._pending_results: dict[str, EngineResult] = {}
        self._pending_progress: dict[str, deque[EngineProgressEvent]] = {}
        self._active_job_ids: set[str] = set()
        self._artifact_transfers: dict[str, tuple[Path, str]] = {}
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._capacity_notifier: Callable[[], None] | None = None

    def bind_capacity_notifier(self, notifier: Callable[[], None]) -> None:
        """ProcessManager wakes capacity waiters when this engine becomes idle."""
        self._capacity_notifier = notifier

    def _assert_coordinator_current(self) -> None:
        if self._coordinator_guard is not None:
            self._coordinator_guard()

    def _coordinator_can_mutate(self, operation: str) -> bool:
        try:
            self._assert_coordinator_current()
        except Exception:
            logger.warning(
                "Coordinator ownership lost; skipping engine mutation operation=%s generation=%s container_id=%s",
                operation,
                self._coordinator_generation,
                self._container_id,
                exc_info=True,
            )
            return False
        return True

    def _detach_local_handles(self) -> None:
        """Forget local handles without changing the externally owned container."""
        if self._channel is not None:
            with contextlib.suppress(Exception):
                self._channel.close()
        if self._client is not None:
            with contextlib.suppress(Exception):
                self._client.close()
        self._channel = None
        self._client = None
        self._container = None
        self._container_id = None
        self._stub = None
        self._rpc_target = None
        self._alive = False
        self._active_job_ids.clear()
        self._artifact_transfers.clear()
        self._publish_current_job_id(None)

    def _cleanup_failed_start(self, container: Any, client: Any) -> None:
        """Remove a partially started container only while this generation owns it."""
        if self._coordinator_can_mutate("failed-start-container-remove"):
            with contextlib.suppress(Exception):
                container.remove(force=True)
        else:
            logger.warning(
                "Leaving failed-start container for active coordinator reconciliation container_id=%s generation=%s",
                self._container_id,
                self._coordinator_generation,
            )
        self._detach_local_handles()
        with contextlib.suppress(Exception):
            client.close()

    def _publish_current_job_id(self, job_id: str | None) -> None:
        """Update current_job_id and notify capacity waiters when work drains."""
        with self._lock:
            was_busy = bool(self.current_job_id)
            self.current_job_id = job_id
            now_busy = bool(self.current_job_id)
        if was_busy and not now_busy and self._capacity_notifier is not None:
            with contextlib.suppress(Exception):
                self._capacity_notifier()

    @property
    def process_id(self) -> int | None:
        return None

    @property
    def container_id(self) -> str | None:
        return self._container_id

    @property
    def is_warm_worker(self) -> bool:
        with self._lock:
            return self._is_warm_worker and self._alive

    @property
    def lifecycle_status(self) -> str:
        if self._shutdown_requested and self._alive:
            return "stopping"
        if not self._alive:
            return "failed" if self.termination_reason and self.termination_reason != "shutdown" else "stopped"
        return "running" if self.current_job_id else "idle"

    def _capture_termination(self, container: Any) -> None:
        state = container.attrs.get("State", {}) if isinstance(container.attrs, dict) else {}
        raw_exit_code = state.get("ExitCode")
        self.exit_code = raw_exit_code if isinstance(raw_exit_code, int) else None
        raw_oom = state.get("OOMKilled")
        self.oom_killed = raw_oom if isinstance(raw_oom, bool) else None
        if self._shutdown_requested:
            self.termination_reason = "shutdown"
        elif self.oom_killed:
            self.termination_reason = "oom_killed"
        elif self.exit_code not in (None, 0):
            self.termination_reason = "container_exit"
        else:
            self.termination_reason = "container_stopped"
        if self.termination_reason == "shutdown":
            logger.info(
                "Engine container stopped resource_id=%s container_id=%s reason=%s exit_code=%s oom_killed=%s",
                self.identity.resource_id,
                self._container_id,
                self.termination_reason,
                self.exit_code,
                self.oom_killed,
            )
        else:
            logger.error(
                "Engine container terminated resource_id=%s container_id=%s reason=%s exit_code=%s oom_killed=%s status=%s",
                self.identity.resource_id,
                self._container_id,
                self.termination_reason,
                self.exit_code,
                self.oom_killed,
                getattr(container, "status", "unknown"),
            )

    def start(self) -> None:
        if self._is_warm_worker:
            self.start_warm_worker()
            return
        self._assert_coordinator_current()
        start_started = time.perf_counter()
        startup_phases: dict[str, float] = {}
        with self._lock:
            if self._alive:
                return
            self._shutdown_requested = False
            phase_started = time.perf_counter()
            credentials = resolve_engine_credentials(self._namespace, self.identity)
            client: Any = docker.DockerClient(base_url=settings.engine_docker_host)  # type: ignore[attr-defined]  # docker-py has no Python 3.14 stubs.
            try:
                daemon_cpu_count, image_id = _resolve_launch_context(client)
                resources = _effective_resources(self.resource_config, runtime_cpu_count=daemon_cpu_count)
            except Exception:
                client.close()
                raise
            startup_phases["credentials_and_docker_context_ms"] = (time.perf_counter() - phase_started) * 1000
            self.effective_resources = cast(dict[str, object], resources)
            self.image_digest = settings.engine_image.split("@", 1)[1] if "@" in settings.engine_image else image_id

            self._token = uuid.uuid4().hex
            labels = {
                "io.dataforge.managed": "true",
                "io.dataforge.deployment": settings.deployment_id,
                "io.dataforge.namespace": self._namespace,
                "io.dataforge.scope": _identity_scope(self.identity),
                "io.dataforge.reuse-policy": enums_pb2.EngineReusePolicy.Name(self.identity.reuse_policy).removeprefix("ENGINE_REUSE_POLICY_").lower(),
                "io.dataforge.resource-id": self.identity.resource_id,
                "io.dataforge.supervisor": self._supervisor_id,
                "io.dataforge.owner": self.identity.build_id if self.identity.HasField("build_id") else self._supervisor_id,
                "io.dataforge.protocol-version": str(ENGINE_PROTOCOL_VERSION),
                "io.dataforge.image-digest": self.image_digest,
                "io.dataforge.created-at": datetime.now(UTC).isoformat(),
            }
            if self._coordinator_generation is not None:
                labels[_COORDINATOR_GENERATION_LABEL] = str(self._coordinator_generation)
            create_kwargs: dict[str, object] = {
                "image": settings.engine_image,
                "name": _container_name(identity=self.identity, namespace=self._namespace),
                "command": ["python3", "engine_main.py"],
                "environment": {
                    "ENGINE_RPC_HOST": "0.0.0.0",
                    "ENGINE_RPC_PORT": str(settings.engine_rpc_port),
                    "ENGINE_HEARTBEAT_TIMEOUT_SECONDS": str(settings.engine_heartbeat_interval_seconds * 6),
                    # Orphan guard: if the worker dies between container start and
                    # initialization, the engine stops itself instead of leaking.
                    "ENGINE_INIT_TIMEOUT_SECONDS": str(max(120, settings.engine_start_timeout_seconds * 2)),
                    "APP_VERSION": _ENGINE_APPLICATION_VERSION,
                },
                "labels": labels,
                "network": settings.engine_docker_network,
                "cpu_shares": _COMPUTE_ENGINE_CPU_SHARES,
                "mem_limit": resources["max_memory_mb"] * _MIB if resources["max_memory_mb"] else None,
                "pids_limit": 256,
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
                "read_only": True,
                "tmpfs": {"/tmp": "rw,noexec,nosuid,size=256m"},
                "restart_policy": {"Name": "no"},
                "auto_remove": False,
            }
            nano_cpus = _container_nano_cpus(resources["max_threads"])
            if nano_cpus is not None:
                create_kwargs["nano_cpus"] = nano_cpus
            if settings.engine_connect_host:
                create_kwargs["ports"] = {f"{settings.engine_rpc_port}/tcp": None}
                create_kwargs["extra_hosts"] = {"host.docker.internal": "host-gateway"}
            phase_started = time.perf_counter()
            try:
                self._assert_coordinator_current()
                container = client.containers.create(**create_kwargs)
            except Exception:
                client.close()
                raise
            startup_phases["container_create_ms"] = (time.perf_counter() - phase_started) * 1000
            self._container_id = str(container.id)
            try:
                phase_started = time.perf_counter()
                self._assert_coordinator_current()
                container.start()
                startup_phases["container_start_ms"] = (time.perf_counter() - phase_started) * 1000
                self._client = client
                self._container = container
                phase_started = time.perf_counter()
                if settings.engine_connect_host:
                    container.reload()
                    bindings = container.attrs["NetworkSettings"]["Ports"].get(f"{settings.engine_rpc_port}/tcp") or []
                    if not bindings:
                        raise RuntimeError("Docker did not publish an engine RPC port")
                    target = f"{settings.engine_connect_host}:{bindings[0]['HostPort']}"
                else:
                    target = _container_rpc_target(container)
                startup_phases["rpc_target_ms"] = (time.perf_counter() - phase_started) * 1000
                self._rpc_target = target
                self._channel = grpc.insecure_channel(
                    target,
                    options=_ENGINE_CHANNEL_OPTIONS,
                )
                self._stub = engine_runtime_pb2_grpc.PolarsEngineServiceStub(self._channel)
                phase_started = time.perf_counter()
                self._await_listening()
                startup_phases["listener_ready_ms"] = (time.perf_counter() - phase_started) * 1000
                phase_started = time.perf_counter()
                self._initialize(resources=resources, credentials=credentials)
                startup_phases["initialize_ms"] = (time.perf_counter() - phase_started) * 1000
                self._alive = True
                self._heartbeat_stop.clear()
                self._heartbeat_thread = threading.Thread(
                    target=self._heartbeat_loop,
                    name=f"engine-heartbeat-{self.identity.resource_id}",
                    daemon=True,
                )
                self._heartbeat_thread.start()
                startup_duration_ms = (time.perf_counter() - start_started) * 1000
                if startup_duration_ms >= _SLOW_ENGINE_START_SECONDS * 1000:
                    phase_timings = " ".join(f"{name}={duration:.1f}" for name, duration in startup_phases.items())
                    logger.warning(
                        "Slow engine startup request_id=%s namespace=%s engine_scope=%s resource_id=%s duration_ms=%.1f %s",
                        get_compute_request_id() or "-",
                        self._namespace,
                        _identity_scope(self.identity),
                        self.identity.resource_id,
                        startup_duration_ms,
                        phase_timings,
                    )
            except Exception:
                self._cleanup_failed_start(container, client)
                raise

    def _metadata(self) -> tuple[tuple[str, str], ...]:
        return ((_ENGINE_TOKEN_METADATA_KEY, self._token),)

    def _initialize(self, *, resources: dict[str, int], credentials: ObjectStoreCredentials) -> None:
        assert self._stub is not None
        req = engine_runtime_pb2.EngineInitializeRequest(
            protocol_version=ENGINE_PROTOCOL_VERSION,
            engine_identity=self.identity.resource_id,
            token=self._token,
            object_store_endpoint=_engine_object_store_endpoint(),
            object_store_region=settings.object_store_region,
            object_store_access_key=credentials.access_key,
            object_store_secret_key=credentials.secret_key,
            object_store_session_token=credentials.session_token or "",
            polars_max_threads=resources["max_threads"],
            polars_streaming_chunk_size=resources["streaming_chunk_size"],
        )
        try:
            resp = self._stub.Initialize(req, timeout=2.0)
        except grpc.RpcError as exc:
            if exc.code() == grpc.StatusCode.FAILED_PRECONDITION and str(exc.details()).startswith("Engine already initialized"):
                raise RuntimeError(
                    f"Engine identity collision for {self.identity.resource_id} at {self._rpc_target} (container {self._container_id}): {exc.details()}"
                ) from exc
            raise RuntimeError(f"Engine initialization failed for {self.identity.resource_id}: {exc}") from exc
        if not resp.ready or resp.engine_identity != self.identity.resource_id:
            raise RuntimeError("Engine initialization did not return the expected ready identity")

    def _await_listening(self) -> None:
        assert self._channel is not None
        assert self._stub is not None
        deadline = time.monotonic() + settings.engine_start_timeout_seconds
        try:
            grpc.channel_ready_future(self._channel).result(timeout=max(0.0, deadline - time.monotonic()))
        except grpc.FutureTimeoutError as exc:
            status = self._container_status_after_start_failure()
            raise RuntimeError(f"Timed out waiting for engine listener; container status={status}") from exc

        retry_delay = 0.1
        last_error: grpc.RpcError | None = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status = self._container_status_after_start_failure()
                raise RuntimeError(f"Timed out waiting for engine health check; container status={status}: {last_error}") from last_error
            try:
                self._stub.Health(
                    engine_runtime_pb2.EngineHealthRequest(),
                    timeout=min(2.0, remaining),
                )
                return
            except grpc.RpcError as exc:
                if exc.code() not in {grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED}:
                    status = self._container_status_after_start_failure()
                    raise RuntimeError(f"Engine listener failed its health check (container status={status}): {exc}") from exc
                last_error = exc
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    continue
                time.sleep(min(retry_delay, remaining))
                retry_delay = min(retry_delay * 2, 1.0)

    def _container_status_after_start_failure(self) -> str:
        """Inspect Docker once, only when readiness has already failed."""
        container = self._container
        if container is None:
            return "unknown"
        with contextlib.suppress(Exception):
            container.reload()
        return str(getattr(container, "status", "unknown"))

    def start_warm_worker(self) -> None:
        self._assert_coordinator_current()
        with self._lock:
            if self._alive:
                return
            self._shutdown_requested = False
            client: Any = docker.DockerClient(base_url=settings.engine_docker_host)  # type: ignore[attr-defined]
            try:
                daemon_cpu_count, image_id = _resolve_launch_context(client)
                resources = _effective_resources(self.resource_config, runtime_cpu_count=daemon_cpu_count)
            except Exception:
                client.close()
                raise
            self.effective_resources = cast(dict[str, object], resources)
            self.image_digest = settings.engine_image.split("@", 1)[1] if "@" in settings.engine_image else image_id

            worker_id = uuid.uuid4().hex[:12]
            labels = {
                "io.dataforge.managed": "true",
                "io.dataforge.deployment": settings.deployment_id,
                "io.dataforge.scope": "warm-worker",
                "io.dataforge.supervisor": self._supervisor_id,
                "io.dataforge.owner": self._supervisor_id,
                "io.dataforge.protocol-version": str(ENGINE_PROTOCOL_VERSION),
                "io.dataforge.image-digest": self.image_digest,
                "io.dataforge.created-at": datetime.now(UTC).isoformat(),
            }
            if self._coordinator_generation is not None:
                labels[_COORDINATOR_GENERATION_LABEL] = str(self._coordinator_generation)
            create_kwargs: dict[str, object] = {
                "image": settings.engine_image,
                "name": f"dataforge-compute-worker-warm-{worker_id}",
                "command": ["python3", "engine_main.py"],
                "environment": {
                    "ENGINE_RPC_HOST": "0.0.0.0",
                    "ENGINE_RPC_PORT": str(settings.engine_rpc_port),
                    "ENGINE_HEARTBEAT_TIMEOUT_SECONDS": str(settings.engine_heartbeat_interval_seconds * 6),
                    # Warm workers stay uninitialized until assigned; no deadline.
                    "ENGINE_INIT_TIMEOUT_SECONDS": "0",
                    "APP_VERSION": _ENGINE_APPLICATION_VERSION,
                },
                "labels": labels,
                "network": settings.engine_docker_network,
                "cpu_shares": _COMPUTE_ENGINE_CPU_SHARES,
                "mem_limit": resources["max_memory_mb"] * _MIB if resources["max_memory_mb"] else None,
                "pids_limit": 256,
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
                "read_only": True,
                "tmpfs": {"/tmp": "rw,noexec,nosuid,size=256m"},
                "restart_policy": {"Name": "no"},
                "auto_remove": False,
            }
            nano_cpus = _container_nano_cpus(resources["max_threads"])
            if nano_cpus is not None:
                create_kwargs["nano_cpus"] = nano_cpus
            if settings.engine_connect_host:
                create_kwargs["ports"] = {f"{settings.engine_rpc_port}/tcp": None}
                create_kwargs["extra_hosts"] = {"host.docker.internal": "host-gateway"}
            self._assert_coordinator_current()
            container = client.containers.create(**create_kwargs)
            self._container_id = str(container.id)
            try:
                self._assert_coordinator_current()
                container.start()
                self._client = client
                self._container = container
                if settings.engine_connect_host:
                    container.reload()
                    bindings = container.attrs["NetworkSettings"]["Ports"].get(f"{settings.engine_rpc_port}/tcp") or []
                    if not bindings:
                        raise RuntimeError("Docker did not publish an engine RPC port")
                    target = f"{settings.engine_connect_host}:{bindings[0]['HostPort']}"
                else:
                    target = _container_rpc_target(container)
                self._rpc_target = target
                self._channel = grpc.insecure_channel(
                    target,
                    options=_ENGINE_CHANNEL_OPTIONS,
                )
                self._stub = engine_runtime_pb2_grpc.PolarsEngineServiceStub(self._channel)
                self._await_listening()
                self._alive = True
            except Exception:
                self._cleanup_failed_start(container, client)
                raise

    def bind_identity(
        self,
        identity: compute_pb2.EngineIdentity,
        *,
        resource_config: dict[str, object] | None = None,
        namespace: str | None = None,
    ) -> None:
        self._assert_coordinator_current()
        with self._lock:
            if not self._alive or self._stub is None:
                raise RuntimeError("Cannot bind identity to an unstarted engine")
            self.identity = identity
            self.analysis_id = identity.resource_id
            self._namespace = namespace or get_namespace()
            if resource_config is not None:
                self.resource_config = resource_config
            credentials = resolve_engine_credentials(self._namespace, self.identity)
            resources = _effective_resources(self.resource_config)
            self.effective_resources = cast(dict[str, object], resources)
            self._token = uuid.uuid4().hex
            self._assert_coordinator_current()
            self._initialize(resources=resources, credentials=credentials)
            self._is_warm_worker = False
            self._heartbeat_stop.clear()
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                name=f"engine-heartbeat-{self.identity.resource_id}",
                daemon=True,
            )
            self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        consecutive_failures = 0
        while not self._heartbeat_stop.wait(settings.engine_heartbeat_interval_seconds):
            try:
                stub = self._stub
                if stub is None:
                    return
                stub.Health(engine_runtime_pb2.EngineHealthRequest(), timeout=2, metadata=self._metadata())
                consecutive_failures = 0
            except Exception as exc:
                consecutive_failures += 1
                logger.warning(
                    "Engine heartbeat failed for %s (%s consecutive): %s",
                    self.identity.resource_id,
                    consecutive_failures,
                    exc,
                )
                # A missed gRPC health RPC is not proof that the container
                # exited: the engine can be busy initializing its compute
                # runtime or briefly starved while many identities start.
                # Docker liveness is authoritative for manager eviction.
                if not self.is_process_alive():
                    self._alive = False
                    if self._capacity_notifier is not None:
                        with contextlib.suppress(Exception):
                            self._capacity_notifier()
                    return
                if consecutive_failures >= 3:
                    logger.warning(
                        "Engine gRPC health is unavailable but its container is still running; "
                        "continuing heartbeats resource_id=%s container_id=%s failures=%s",
                        self.identity.resource_id,
                        self._container_id,
                        consecutive_failures,
                    )
                    consecutive_failures = 0

    @property
    def last_known_alive(self) -> bool:
        """Liveness from in-memory state; no Docker or RPC round trip."""
        return self._alive

    def is_process_alive(self) -> bool:
        """Liveness backed by Docker, rate-limited and never lock-blocked.

        The daemon round trip is cached for _LIVENESS_CACHE_SECONDS and skipped
        entirely while another thread is already probing, so a caller can never
        stall on one slow container inspection. The heartbeat loop keeps
        ``_alive`` current between probes.
        """
        container = self._container
        if not self._alive or container is None:
            return False
        if time.monotonic() - self._liveness_checked_at < _LIVENESS_CACHE_SECONDS:
            return self._alive
        if not self._liveness_lock.acquire(blocking=False):
            return self._alive
        try:
            container.reload()
            running = container.status == "running"
            self._liveness_checked_at = time.monotonic()
            if not running:
                self._alive = False
                self._capture_termination(container)
            return running
        except Exception:
            self._alive = False
            return False
        finally:
            self._liveness_lock.release()

    def check_health(self) -> bool:
        if not self.is_process_alive():
            return False
        with self._lock:
            if self._stub is None:
                return False
            stub = self._stub
            is_warm_worker = self._is_warm_worker
            metadata = () if is_warm_worker else self._metadata()
        try:
            health = stub.Health(engine_runtime_pb2.EngineHealthRequest(), timeout=1, metadata=metadata)
            return True if is_warm_worker else bool(health.ready)
        except grpc.RpcError:
            return False

    def _submit(self, kind: str, payload: dict[str, object], *, job_id: str | None = None) -> str:
        with self._lock:
            self._assert_coordinator_current()
            # Check, restart and job registration stay atomic: an engine that is
            # shut down (idle reaping, a crash) between the check and the
            # registration has to be restarted, not reported as broken.
            if not self.is_process_alive():
                self.start()
            assert self._stub is not None
            stub = self._stub
            metadata = self._metadata()
            job_id = job_id or get_compute_request_id() or str(uuid.uuid4())
            self._active_job_ids.add(job_id)
            self._publish_current_job_id(job_id)
        # The submit RPC runs unlocked: it waits for the engine to accept the
        # job, and holding the lifecycle lock across it blocks shutdown, status
        # and every other caller of this engine for the full submit timeout.
        try:
            self._assert_coordinator_current()
            stub.SubmitJob(
                engine_runtime_pb2.EngineSubmitJobRequest(
                    protocol_version=ENGINE_PROTOCOL_VERSION,
                    job_id=job_id,
                    kind=kind,
                    payload_json=encode_json_bytes(payload),
                ),
                timeout=settings.engine_start_timeout_seconds,
                metadata=metadata,
            )
        except Exception:
            with self._lock:
                self._active_job_ids.discard(job_id)
                self._publish_current_job_id(next(iter(self._active_job_ids), None))
            raise
        threading.Thread(target=self._watch_job, args=(job_id,), name=f"engine-watch-{job_id}", daemon=True).start()
        return job_id

    def preview(
        self, datasource_config: dict, steps: list[dict], row_limit: int = 1000, offset: int = 0, additional_datasources: dict[str, dict] | None = None
    ) -> str:
        return self._submit(
            "preview",
            {
                "datasource_config": datasource_config,
                "steps": steps,
                "row_limit": row_limit,
                "offset": offset,
                "additional_datasources": additional_datasources or {},
            },
        )

    def export(
        self, datasource_config: dict, steps: list[dict], output_path: str, export_format: str = "csv", additional_datasources: dict[str, dict] | None = None
    ) -> str:
        job_id = str(uuid.uuid4())
        artifact_url = object_store_url(
            "runtime-staging",
            _safe_name(self.identity.resource_id),
            job_id,
            f"output.{_safe_name(export_format)}",
            namespace=self._namespace,
        )
        with self._lock:
            self._artifact_transfers[job_id] = (Path(output_path), artifact_url)
        try:
            export = get_export_format(export_format)
            upload_url = presigned_put_url(
                artifact_url,
                expires_seconds=max(settings.engine_start_timeout_seconds * 10, 3600),
                endpoint_url=_engine_object_store_endpoint(),
                content_type=export.content_type,
            )
            return self._submit(
                "export",
                {
                    "datasource_config": datasource_config,
                    "steps": steps,
                    "artifact_url": artifact_url,
                    "artifact_upload_url": upload_url,
                    "export_format": export_format,
                    "additional_datasources": additional_datasources or {},
                },
                job_id=job_id,
            )
        except Exception:
            with self._lock:
                self._artifact_transfers.pop(job_id, None)
            with contextlib.suppress(Exception):
                delete_object(artifact_url)
            raise

    def get_schema(self, datasource_config: dict, steps: list[dict], additional_datasources: dict[str, dict] | None = None) -> str:
        return self._submit("schema", {"datasource_config": datasource_config, "steps": steps, "additional_datasources": additional_datasources or {}})

    def get_row_count(self, datasource_config: dict, steps: list[dict], additional_datasources: dict[str, dict] | None = None) -> str:
        return self._submit("row_count", {"datasource_config": datasource_config, "steps": steps, "additional_datasources": additional_datasources or {}})

    def datasource_job(self, kind: str, payload: dict[str, object]) -> str:
        return self._submit(kind, {**payload, "resource_id": self.identity.resource_id})

    def cancel_job(self, job_id: str | None = None) -> bool:
        expected = job_id or self.current_job_id
        if not expected:
            return False
        with self._lock:
            stub = self._stub
            if stub is None or not self._alive:
                return False
            metadata = self._metadata()
        cancel = getattr(stub, "CancelJob", None)
        if not callable(cancel):
            return False
        try:
            response = cancel(
                engine_runtime_pb2.EngineCancelJobRequest(job_id=expected),
                timeout=settings.engine_shutdown_grace_seconds,
                metadata=metadata,
            )
        except grpc.RpcError as exc:
            logger.warning("Failed to cancel engine job %s: %s", expected, exc)
            return False
        return bool(response.accepted)

    def _publish_job_result(self, job_id: str, result: EngineResult) -> None:
        with self._lock:
            transfer = self._artifact_transfers.pop(job_id, None)
        if transfer is not None:
            local_path, artifact_url = transfer
            try:
                if result.error is None:
                    download_file(artifact_url, local_path)
                    if result.data is not None:
                        result.data["output_path"] = str(local_path)
            except Exception as exc:
                result = EngineResult(
                    job_id=job_id,
                    data=None,
                    error=f"Failed to retrieve staged engine artifact: {exc}",
                    error_kind="engine_artifact_transfer_failed",
                    error_details={},
                )
            finally:
                with contextlib.suppress(Exception):
                    delete_object(artifact_url)
        with self._lock:
            self._pending_results[job_id] = result
            while len(self._pending_results) > 100:
                self._pending_results.pop(next(iter(self._pending_results)))
            self._active_job_ids.discard(job_id)
            next_job = next(iter(self._active_job_ids), None)
        self._publish_current_job_id(next_job)

    def _watch_job(self, job_id: str) -> None:
        try:
            assert self._stub is not None
            sequence = 0
            while True:
                try:
                    stream = self._stub.WatchJob(
                        engine_runtime_pb2.EngineWatchJobRequest(job_id=job_id, after_sequence=sequence),
                        metadata=self._metadata(),
                    )
                    for event in stream:
                        sequence = max(sequence, event.sequence)
                        which = event.WhichOneof("event")
                        if which == "progress_json":
                            payload = json.loads(event.progress_json)
                            if not isinstance(payload, dict):
                                raise RuntimeError("Engine progress payload must be an object")
                            with self._lock:
                                self._pending_progress.setdefault(job_id, deque(maxlen=1000)).append(EngineProgressEvent(job_id=job_id, event=payload))
                                while len(self._pending_progress) > 100:
                                    self._pending_progress.pop(next(iter(self._pending_progress)))
                        elif which == "result":
                            result = _result_from_message(event.result)
                            with contextlib.suppress(Exception):
                                self._stub.GetJobResult(
                                    engine_runtime_pb2.EngineGetJobResultRequest(job_id=job_id),
                                    timeout=2,
                                    metadata=self._metadata(),
                                )
                            self._publish_job_result(job_id, result)
                            return
                except grpc.RpcError:
                    # The terminal result is retained independently from the
                    # bounded progress stream. Recover it before treating a
                    # cursor eviction or transport interruption as job loss.
                    try:
                        message = self._stub.GetJobResult(
                            engine_runtime_pb2.EngineGetJobResultRequest(job_id=job_id),
                            timeout=2,
                            metadata=self._metadata(),
                        )
                    except grpc.RpcError as result_error:
                        if result_error.code() not in {grpc.StatusCode.FAILED_PRECONDITION, grpc.StatusCode.UNAVAILABLE} or not self.is_process_alive():
                            raise
                    else:
                        self._publish_job_result(job_id, _result_from_message(message))
                        return

                # A healthy watch is open until a terminal result. If the
                # transport closes cleanly first, resume from the last durable
                # sequence instead of abandoning the active job forever.
                if self._shutdown_requested:
                    raise RuntimeError("Engine shutdown requested")
                logger.info("Engine job watch ended before result for %s; resuming after sequence %s", job_id, sequence)
                if self._heartbeat_stop.wait(0.05):
                    raise RuntimeError("Engine shutdown requested")
        except Exception as exc:
            with self._lock:
                intentional_shutdown = self._shutdown_requested
                transfer = self._artifact_transfers.pop(job_id, None)
                self._pending_results[job_id] = EngineResult(
                    job_id=job_id,
                    data=None,
                    error="Engine shutdown requested" if intentional_shutdown else str(exc),
                    error_kind="engine_shutdown" if intentional_shutdown else "engine_rpc_lost",
                    error_details={},
                )
                self._active_job_ids.discard(job_id)
                next_job = next(iter(self._active_job_ids), None)
            self._publish_current_job_id(next_job)
            if intentional_shutdown:
                logger.info("Engine job %s stopped during engine shutdown", job_id)
            else:
                logger.warning("Engine job watcher failed for %s: %s", job_id, exc)
            if transfer is not None:
                with contextlib.suppress(Exception):
                    delete_object(transfer[1])

    def get_result(self, timeout: float = 1.0, job_id: str | None = None) -> EngineResult | None:
        expected = job_id or self.current_job_id
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                if expected and expected in self._pending_results:
                    return self._pending_results.pop(expected)
            if expected and not self.is_process_alive():
                intentional_shutdown = self._shutdown_requested
                error_kind = "engine_shutdown" if intentional_shutdown else "engine_oom_killed" if self.oom_killed else "engine_container_exited"
                reason = self.termination_reason or "unknown"
                return EngineResult(
                    job_id=expected,
                    data=None,
                    error=(
                        "Engine shutdown requested"
                        if intentional_shutdown
                        else f"Engine container terminated (reason={reason}, exit_code={self.exit_code}, oom_killed={self.oom_killed})"
                    ),
                    error_kind=error_kind,
                    error_details={
                        "container_id": self.container_id,
                        "exit_code": self.exit_code,
                        "oom_killed": self.oom_killed,
                        "termination_reason": self.termination_reason,
                    },
                )
            if time.monotonic() >= deadline:
                return None
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    def get_progress_event(self, timeout: float = 1.0, job_id: str | None = None) -> EngineProgressEvent | None:
        expected = job_id or self.current_job_id
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                if expected:
                    events = self._pending_progress.get(expected)
                    if events:
                        return events.popleft()
            if time.monotonic() >= deadline:
                return None
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    def shutdown(self) -> None:
        with self._lock:
            self._shutdown_requested = True
            self._heartbeat_stop.set()
            container = self._container
            stub = self._stub
            transfers = list(self._artifact_transfers.values()) if container is None else []
            if container is None:
                if not self._coordinator_can_mutate("artifact-transfer-cleanup"):
                    self._detach_local_handles()
                    return
                self._artifact_transfers.clear()
                self._active_job_ids.clear()
                self._publish_current_job_id(None)
                for _local_path, artifact_url in transfers:
                    with contextlib.suppress(Exception):
                        delete_object(artifact_url)
                return
            if not self._coordinator_can_mutate("engine-shutdown-rpc"):
                self._detach_local_handles()
                return
            if stub is not None:
                with contextlib.suppress(Exception):
                    stub.Shutdown(engine_runtime_pb2.EngineShutdownRequest(), timeout=settings.engine_shutdown_grace_seconds, metadata=self._metadata())
            deadline = time.monotonic() + settings.engine_shutdown_grace_seconds
            while time.monotonic() < deadline:
                with contextlib.suppress(Exception):
                    container.reload()
                    if container.status != "running":
                        break
                time.sleep(0.1)
            with contextlib.suppress(Exception):
                container.reload()
                if container.status == "running":
                    if not self._coordinator_can_mutate("engine-container-stop"):
                        self._detach_local_handles()
                        return
                    container.stop(timeout=settings.engine_shutdown_grace_seconds)
                    container.reload()
                self._capture_termination(container)
            if not self._coordinator_can_mutate("engine-container-remove"):
                self._detach_local_handles()
                return
            try:
                container.remove(force=True)
            except Exception:
                logger.warning("Failed to remove engine container during shutdown container_id=%s", self._container_id, exc_info=True)
                self._detach_local_handles()
                return
            if self._channel is not None:
                self._channel.close()
            if self._client is not None:
                self._client.close()
            self._channel = None
            self._client = None
            self._container = None
            self._stub = None
            self._rpc_target = None
            self._alive = False
            self._active_job_ids.clear()
            transfers = list(self._artifact_transfers.values())
            self._artifact_transfers.clear()
            # Drop job pointer after clearing active set so waiters can reclaim capacity.
            self._publish_current_job_id(None)
        for _local_path, artifact_url in transfers:
            with contextlib.suppress(Exception):
                delete_object(artifact_url)


def _result_from_message(message: engine_runtime_pb2.EngineJobResult) -> EngineResult:
    data = json.loads(message.data_json) if message.HasField("data_json") else None
    details = json.loads(message.error_details_json) if message.HasField("error_details_json") else None
    timings = json_format.MessageToDict(message.step_timings, preserving_proto_field_name=True)
    return EngineResult(
        job_id=message.job_id,
        data=data,
        error=message.error if message.HasField("error") else None,
        error_kind=message.error_kind if message.HasField("error_kind") else None,
        error_details=details,
        step_timings={str(key): float(value) for key, value in timings.items() if isinstance(value, int | float)},
        query_plan=message.query_plan if message.HasField("query_plan") else None,
        read_duration_ms=message.read_duration_ms if message.HasField("read_duration_ms") else None,
        write_duration_ms=message.write_duration_ms if message.HasField("write_duration_ms") else None,
        collect_duration_ms=message.collect_duration_ms if message.HasField("collect_duration_ms") else None,
    )
