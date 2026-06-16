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
    polars_max_threads: int
    polars_max_memory_mb: int
    polars_streaming_chunk_size: int
    normalize_tz: bool
    timezone: str
    persist_preview_runs: bool
    database_url: str
    object_store_endpoint: str
    object_store_region: str
    object_store_access_key: str
    object_store_secret_key: str
    object_store_bucket: str
    object_store_prefix: str
    internal_api_token: str
    data_plane_grpc_host: str
    data_plane_grpc_port: int


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
    polars_max_threads=_read_int("POLARS_MAX_THREADS", 0, min_value=0),
    polars_max_memory_mb=_read_int("POLARS_MAX_MEMORY_MB", 0, min_value=0),
    polars_streaming_chunk_size=_read_int("POLARS_STREAMING_CHUNK_SIZE", 0, min_value=0),
    normalize_tz=_read_bool("NORMALIZE_TZ", False),
    timezone=os.environ.get("TIMEZONE", "UTC").strip() or "UTC",
    persist_preview_runs=_read_bool("PERSIST_PREVIEW_RUNS", True),
    database_url=os.environ.get("DATABASE_URL", ""),
    object_store_endpoint=os.environ.get("OBJECT_STORE_ENDPOINT", "http://127.0.0.1:9000"),
    object_store_region=os.environ.get("OBJECT_STORE_REGION", "us-east-1"),
    object_store_access_key=os.environ.get("OBJECT_STORE_ACCESS_KEY", "rustfsadmin"),
    object_store_secret_key=os.environ.get("OBJECT_STORE_SECRET_KEY", "rustfsadmin"),
    object_store_bucket=os.environ.get("OBJECT_STORE_BUCKET", "dataforge"),
    object_store_prefix=os.environ.get("OBJECT_STORE_PREFIX", "dataforge"),
    internal_api_token=os.environ.get("INTERNAL_API_TOKEN", ""),
    data_plane_grpc_host=os.environ.get("WORKER_DATA_PLANE_GRPC_HOST", "127.0.0.1").strip() or "127.0.0.1",
    data_plane_grpc_port=_read_int("WORKER_DATA_PLANE_GRPC_PORT", 50052, min_value=1, max_value=65535),
)
