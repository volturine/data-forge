from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from runtime.environment import read_env, read_int


@dataclass(slots=True)
class WorkerSettings:
    data_dir: Path
    default_namespace: str
    # Global job budget; also caps active compute-worker identities.
    compute_workers: int
    runtime_reconciliation_poll_interval_seconds: int
    compute_worker_idle_ttl_seconds: int
    compute_worker_idle_reap_interval_seconds: int
    polars_cores_available: int
    polars_max_memory_mb: int
    polars_streaming_chunk_size: int
    normalize_tz: bool
    timezone: str
    persist_preview_runs: bool
    prod_mode_enabled: bool
    database_url: str
    object_store_endpoint: str
    object_store_region: str
    object_store_access_key: str
    object_store_secret_key: str
    object_store_session_token: str
    internal_api_token: str
    data_plane_grpc_host: str
    data_plane_grpc_port: int
    compute_worker_docker_host: str
    # JSON list of Docker hosts; empty means the single compute-worker host.
    compute_worker_docker_hosts: str
    compute_worker_docker_host_health_interval_seconds: int
    compute_worker_docker_network: str
    compute_worker_object_store_endpoint: str
    compute_worker_image: str
    compute_worker_connect_host: str
    compute_worker_rpc_port: int
    compute_worker_start_timeout_seconds: int
    compute_worker_shutdown_grace_seconds: int
    compute_worker_heartbeat_interval_seconds: int
    compute_warm_workers: int
    deployment_id: str


def _read_int(
    name: str,
    default: int,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
    legacy_names: tuple[str, ...] = (),
) -> int:
    return read_int(name, default, min_value=min_value, max_value=max_value, legacy_names=legacy_names)


def _read_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean value")


_COMPUTE_WORKERS = _read_int("COMPUTE_WORKERS", 14, min_value=1, max_value=100)


settings = WorkerSettings(
    data_dir=Path(os.environ.get("DATA_DIR", str(Path(tempfile.gettempdir()) / "data-forge"))),
    default_namespace=os.environ.get("DEFAULT_NAMESPACE", "default").strip() or "default",
    compute_workers=_COMPUTE_WORKERS,
    runtime_reconciliation_poll_interval_seconds=_read_int("RUNTIME_RECONCILIATION_POLL_INTERVAL_SECONDS", 1, min_value=1),
    compute_worker_idle_ttl_seconds=_read_int("COMPUTE_WORKER_IDLE_TTL_SECONDS", 300, min_value=1, legacy_names=("ENGINE_IDLE_TTL_SECONDS",)),
    compute_worker_idle_reap_interval_seconds=_read_int(
        "COMPUTE_WORKER_IDLE_REAP_INTERVAL_SECONDS", 30, min_value=1, legacy_names=("ENGINE_IDLE_REAP_INTERVAL_SECONDS",)
    ),
    # Total cores available for compute workers (0 = all logical CPUs). Not Polars' native env.
    polars_cores_available=_read_int("POLARS_CORES_AVAILABLE", 0, min_value=0),
    polars_max_memory_mb=_read_int("POLARS_MAX_MEMORY_MB", 0, min_value=0),
    polars_streaming_chunk_size=_read_int("POLARS_STREAMING_CHUNK_SIZE", 0, min_value=0),
    normalize_tz=_read_bool("NORMALIZE_TZ", False),
    timezone=os.environ.get("TIMEZONE", "UTC").strip() or "UTC",
    persist_preview_runs=_read_bool("PERSIST_PREVIEW_RUNS", True),
    prod_mode_enabled=_read_bool("PROD_MODE_ENABLED", False),
    database_url=os.environ.get("DATABASE_URL", ""),
    object_store_endpoint=os.environ.get("OBJECT_STORE_ENDPOINT", "http://127.0.0.1:9000"),
    object_store_region=os.environ.get("OBJECT_STORE_REGION", "us-east-1"),
    object_store_access_key=os.environ.get("OBJECT_STORE_ACCESS_KEY", "rustfsadmin"),
    object_store_secret_key=os.environ.get("OBJECT_STORE_SECRET_KEY", "rustfsadmin"),
    object_store_session_token=os.environ.get("OBJECT_STORE_SESSION_TOKEN", ""),
    internal_api_token=os.environ.get("INTERNAL_API_TOKEN", ""),
    data_plane_grpc_host=os.environ.get("WORKER_DATA_PLANE_GRPC_HOST", "127.0.0.1").strip() or "127.0.0.1",
    data_plane_grpc_port=_read_int("WORKER_DATA_PLANE_GRPC_PORT", 50052, min_value=1, max_value=65535),
    compute_worker_docker_host=read_env(
        "COMPUTE_WORKER_DOCKER_HOST",
        "unix:///var/run/docker.sock",
        legacy_names=("DF_ENGINE_DOCKER_HOST", "ENGINE_DOCKER_HOST"),
    ).strip()
    or "unix:///var/run/docker.sock",
    compute_worker_docker_hosts=read_env("COMPUTE_WORKER_DOCKER_HOSTS", legacy_names=("DF_ENGINE_DOCKER_HOSTS", "ENGINE_DOCKER_HOSTS")).strip(),
    compute_worker_docker_host_health_interval_seconds=_read_int(
        "COMPUTE_WORKER_DOCKER_HOST_HEALTH_INTERVAL_SECONDS",
        15,
        min_value=1,
        legacy_names=("DF_ENGINE_DOCKER_HOST_HEALTH_INTERVAL_SECONDS", "ENGINE_DOCKER_HOST_HEALTH_INTERVAL_SECONDS"),
    ),
    compute_worker_docker_network=read_env(
        "COMPUTE_WORKER_DOCKER_NETWORK",
        "dataforge-compute-worker-runtime",
        legacy_names=("DF_ENGINE_DOCKER_NETWORK", "ENGINE_DOCKER_NETWORK"),
    ).strip()
    or "dataforge-compute-worker-runtime",
    compute_worker_object_store_endpoint=read_env(
        "COMPUTE_WORKER_OBJECT_STORE_ENDPOINT",
        legacy_names=("DF_ENGINE_OBJECT_STORE_ENDPOINT", "ENGINE_OBJECT_STORE_ENDPOINT"),
    ).strip(),
    compute_worker_image=read_env(
        "COMPUTE_WORKER_IMAGE",
        "data-forge-compute-worker:latest",
        legacy_names=("DF_ENGINE_IMAGE", "ENGINE_IMAGE"),
    ).strip()
    or "data-forge-compute-worker:latest",
    # Empty keeps compute-worker RPC private on the Docker network. Test harnesses that
    # run the worker on the host can opt in to an ephemeral host port.
    compute_worker_connect_host=read_env(
        "COMPUTE_WORKER_CONNECT_HOST",
        legacy_names=("DF_ENGINE_CONNECT_HOST", "ENGINE_CONNECT_HOST"),
    ).strip(),
    compute_worker_rpc_port=_read_int("COMPUTE_WORKER_RPC_PORT", 50053, min_value=1, max_value=65535, legacy_names=("DF_ENGINE_RPC_PORT", "ENGINE_RPC_PORT")),
    compute_worker_start_timeout_seconds=_read_int(
        "COMPUTE_WORKER_START_TIMEOUT_SECONDS", 30, min_value=1, legacy_names=("DF_ENGINE_START_TIMEOUT_SECONDS", "ENGINE_START_TIMEOUT_SECONDS")
    ),
    compute_worker_shutdown_grace_seconds=_read_int(
        "COMPUTE_WORKER_SHUTDOWN_GRACE_SECONDS", 10, min_value=1, legacy_names=("DF_ENGINE_SHUTDOWN_GRACE_SECONDS", "ENGINE_SHUTDOWN_GRACE_SECONDS")
    ),
    compute_worker_heartbeat_interval_seconds=_read_int(
        "COMPUTE_WORKER_HEARTBEAT_INTERVAL_SECONDS",
        5,
        min_value=1,
        legacy_names=("DF_ENGINE_HEARTBEAT_INTERVAL_SECONDS", "ENGINE_HEARTBEAT_INTERVAL_SECONDS"),
    ),
    # Ready, unassigned compute workers kept as a latency reserve. A worker
    # receives an application-wide lease only when bound to a compute-worker identity.
    compute_warm_workers=_read_int("COMPUTE_WARM_WORKERS", 0, min_value=0, max_value=100),
    deployment_id=os.environ.get("DATAFORGE_DEPLOYMENT_ID", "dataforge").strip() or "dataforge",
)
