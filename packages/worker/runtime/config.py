from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class WorkerSettings:
    data_dir: Path
    default_namespace: str
    compute_request_concurrency: int
    runtime_reconciliation_poll_interval_seconds: int
    build_worker_min_processes: int
    build_worker_max_processes: int
    build_worker_idle_exit_seconds: int
    engine_idle_ttl_seconds: int
    engine_idle_reap_interval_seconds: int
    max_concurrent_engines: int
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
    engine_docker_host: str
    engine_docker_network: str
    engine_object_store_endpoint: str
    engine_image: str
    engine_connect_host: str
    engine_rpc_port: int
    engine_start_timeout_seconds: int
    engine_shutdown_grace_seconds: int
    engine_heartbeat_interval_seconds: int
    engine_object_store_credentials_json: str
    engine_allow_global_object_store_credentials: bool
    deployment_id: str


def _read_int(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    raw = os.environ.get(name)
    value = default if raw is None or raw == "" else int(raw)
    if min_value is not None and value < min_value:
        raise RuntimeError(f"{name} must be at least {min_value}, got {value}")
    if max_value is not None and value > max_value:
        raise RuntimeError(f"{name} must be at most {max_value}, got {value}")
    return value


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


settings = WorkerSettings(
    data_dir=Path(os.environ.get("DATA_DIR", str(Path(tempfile.gettempdir()) / "data-forge"))),
    default_namespace=os.environ.get("DEFAULT_NAMESPACE", "default").strip() or "default",
    compute_request_concurrency=_read_int("COMPUTE_REQUEST_CONCURRENCY", 4, min_value=1, max_value=100),
    runtime_reconciliation_poll_interval_seconds=_read_int("RUNTIME_RECONCILIATION_POLL_INTERVAL_SECONDS", 1, min_value=1),
    build_worker_min_processes=_read_int("BUILD_WORKER_MIN_PROCESSES", 0, min_value=0, max_value=100),
    build_worker_max_processes=_read_int("BUILD_WORKER_MAX_PROCESSES", 10, min_value=0, max_value=100),
    build_worker_idle_exit_seconds=_read_int("BUILD_WORKER_IDLE_EXIT_SECONDS", 30, min_value=1),
    engine_idle_ttl_seconds=_read_int("ENGINE_IDLE_TTL_SECONDS", 300, min_value=1),
    engine_idle_reap_interval_seconds=_read_int("ENGINE_IDLE_REAP_INTERVAL_SECONDS", 30, min_value=1),
    max_concurrent_engines=_read_int("MAX_CONCURRENT_ENGINES", 10, min_value=1, max_value=100),
    # Total cores available for engines (0 = all logical CPUs). Not Polars' native env.
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
    engine_docker_host=os.environ.get("ENGINE_DOCKER_HOST", "unix:///var/run/docker.sock").strip() or "unix:///var/run/docker.sock",
    engine_docker_network=os.environ.get("ENGINE_DOCKER_NETWORK", "dataforge-engine-runtime").strip() or "dataforge-engine-runtime",
    engine_object_store_endpoint=os.environ.get("ENGINE_OBJECT_STORE_ENDPOINT", "").strip(),
    engine_image=os.environ.get("ENGINE_IMAGE", "data-forge-polars-engine:latest").strip() or "data-forge-polars-engine:latest",
    # Empty keeps engine RPC private on the Docker network. Test harnesses that
    # run the worker on the host can opt in to an ephemeral host port.
    engine_connect_host=os.environ.get("ENGINE_CONNECT_HOST", "").strip(),
    engine_rpc_port=_read_int("ENGINE_RPC_PORT", 50053, min_value=1, max_value=65535),
    engine_start_timeout_seconds=_read_int("ENGINE_START_TIMEOUT_SECONDS", 30, min_value=1),
    engine_shutdown_grace_seconds=_read_int("ENGINE_SHUTDOWN_GRACE_SECONDS", 10, min_value=1),
    engine_heartbeat_interval_seconds=_read_int("ENGINE_HEARTBEAT_INTERVAL_SECONDS", 5, min_value=1),
    engine_object_store_credentials_json=os.environ.get("ENGINE_OBJECT_STORE_CREDENTIALS_JSON", ""),
    engine_allow_global_object_store_credentials=_read_bool("ENGINE_ALLOW_GLOBAL_OBJECT_STORE_CREDENTIALS", False),
    deployment_id=os.environ.get("DATAFORGE_DEPLOYMENT_ID", "dataforge").strip() or "dataforge",
)
