from __future__ import annotations

import contextlib
import io
import json
import logging
import tarfile
import threading
import time
import uuid
from collections import deque
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast

import docker
import grpc
from google.protobuf import json_format

from dataforge_protocol import compute_pb2, engine_runtime_pb2, engine_runtime_pb2_grpc, enums_pb2
from runtime.config import settings
from runtime.domain.compute.base import ComputeEngine, EngineProgressEvent, EngineResult
from runtime.engine_server import ENGINE_PROTOCOL_VERSION
from runtime.json_values import dict_to_struct
from runtime.namespace import get_namespace

logger = logging.getLogger(__name__)

_ENGINE_TOKEN_METADATA_KEY = "x-engine-token"
_MIB = 1024 * 1024


def _identity_scope(identity: compute_pb2.EngineIdentity) -> str:
    return enums_pb2.EngineScope.Name(identity.scope).removeprefix("ENGINE_SCOPE_").lower()


def _safe_name(value: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
    return normalized[:40] or "engine"


def _container_name(*, identity: compute_pb2.EngineIdentity, namespace: str) -> str:
    payload = f"{namespace}:{identity.scope}:{identity.resource_id}:{uuid.uuid4()}".encode()
    suffix = sha256(payload).hexdigest()[:12]
    return f"dataforge-engine-{_safe_name(namespace)}-{_safe_name(identity.resource_id)}-{suffix}"


def _effective_resources(resource_config: dict[str, object]) -> dict[str, int]:
    max_threads = resource_config.get("max_threads", settings.polars_cores_available)
    max_memory_mb = resource_config.get("max_memory_mb", settings.polars_max_memory_mb)
    streaming_chunk_size = resource_config.get("streaming_chunk_size", settings.polars_streaming_chunk_size)
    values = {
        "max_threads": max_threads if isinstance(max_threads, int) and max_threads >= 0 else 0,
        "max_memory_mb": max_memory_mb if isinstance(max_memory_mb, int) and max_memory_mb >= 0 else 0,
        "streaming_chunk_size": streaming_chunk_size if isinstance(streaming_chunk_size, int) and streaming_chunk_size >= 0 else 0,
    }
    if settings.polars_cores_available > 0:
        values["max_threads"] = min(values["max_threads"] or settings.polars_cores_available, settings.polars_cores_available)
    return values


def _engine_object_store_endpoint() -> str:
    endpoint = settings.object_store_endpoint
    if settings.engine_connect_host and endpoint.startswith("http://127.0.0.1"):
        return endpoint.replace("http://127.0.0.1", "http://host.docker.internal", 1)
    if settings.engine_connect_host and endpoint.startswith("http://localhost"):
        return endpoint.replace("http://localhost", "http://host.docker.internal", 1)
    return endpoint


def _credential_archive(*, identity: compute_pb2.EngineIdentity, token: str, resources: dict[str, int]) -> bytes:
    payload = {
        "ENGINE_IDENTITY": identity.resource_id,
        "ENGINE_RPC_TOKEN": token,
        "OBJECT_STORE_ENDPOINT": _engine_object_store_endpoint(),
        "OBJECT_STORE_REGION": settings.object_store_region,
        "OBJECT_STORE_ACCESS_KEY": settings.object_store_access_key,
        "OBJECT_STORE_SECRET_KEY": settings.object_store_secret_key,
        "POLARS_MAX_THREADS": str(resources["max_threads"]),
        "POLARS_STREAMING_CHUNK_SIZE": str(resources["streaming_chunk_size"]),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo("engine.json")
        info.size = len(raw)
        info.mode = 0o400
        archive.addfile(info, io.BytesIO(raw))
    return buffer.getvalue()


class DockerComputeEngine(ComputeEngine):
    def __init__(self, identity: compute_pb2.EngineIdentity, resource_config: dict[str, object] | None = None, *, namespace: str | None = None) -> None:
        self.identity = identity
        self.analysis_id = identity.resource_id
        self.resource_config = resource_config or {}
        self.effective_resources: dict[str, object] = {}
        self.current_job_id: str | None = None
        self._namespace = namespace or get_namespace()
        self._client: Any | None = None  # docker-py does not publish Python 3.14 type stubs.
        self._container: Any | None = None
        self._channel: grpc.Channel | None = None
        self._stub: engine_runtime_pb2_grpc.PolarsEngineServiceStub | None = None
        self._token = ""
        self._alive = False
        self._lock = threading.RLock()
        self._pending_results: dict[str, EngineResult] = {}
        self._pending_progress: dict[str, deque[EngineProgressEvent]] = {}

    @property
    def process_id(self) -> int | None:
        return None

    @property
    def container_id(self) -> str | None:
        return str(self._container.id) if self._container is not None else None

    def start(self) -> None:
        with self._lock:
            if self._alive:
                return
            resources = _effective_resources(self.resource_config)
            self.effective_resources = cast(dict[str, object], resources)
            client: Any = docker.DockerClient(base_url=settings.engine_docker_host)  # type: ignore[attr-defined]  # docker-py has no Python 3.14 stubs.
            try:
                client.images.get(settings.engine_image)
                client.networks.get(settings.engine_docker_network)
            except Exception:
                client.close()
                raise

            self._token = uuid.uuid4().hex
            labels = {
                "io.dataforge.managed": "true",
                "io.dataforge.deployment": settings.deployment_id,
                "io.dataforge.namespace": self._namespace,
                "io.dataforge.scope": _identity_scope(self.identity),
                "io.dataforge.resource-id": self.identity.resource_id,
                "io.dataforge.protocol-version": str(ENGINE_PROTOCOL_VERSION),
                "io.dataforge.created-at": datetime.now(UTC).isoformat(),
            }
            create_kwargs: dict[str, object] = {
                "image": settings.engine_image,
                "name": _container_name(identity=self.identity, namespace=self._namespace),
                "command": ["python3", "engine_main.py"],
                "environment": {
                    "ENGINE_RPC_HOST": "0.0.0.0",
                    "ENGINE_RPC_PORT": str(settings.engine_rpc_port),
                    "ENGINE_BOOTSTRAP_PATH": "/run/dataforge-secrets/engine.json",
                    "ENGINE_BOOTSTRAP_TIMEOUT_SECONDS": str(settings.engine_start_timeout_seconds),
                    "APP_VERSION": "engine",
                },
                "labels": labels,
                "network": settings.engine_docker_network,
                "mem_limit": resources["max_memory_mb"] * _MIB if resources["max_memory_mb"] else None,
                "nano_cpus": resources["max_threads"] * 1_000_000_000 if resources["max_threads"] else None,
                "pids_limit": 256,
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
                "read_only": True,
                "tmpfs": {"/run/dataforge-secrets": "rw,noexec,nosuid,size=64k", "/tmp": "rw,noexec,nosuid,size=256m"},
                "restart_policy": {"Name": "no"},
            }
            if settings.engine_connect_host:
                create_kwargs["ports"] = {f"{settings.engine_rpc_port}/tcp": None}
                create_kwargs["extra_hosts"] = {"host.docker.internal": "host-gateway"}
            container = client.containers.create(**create_kwargs)
            try:
                container.start()
                if not container.put_archive("/run/dataforge-secrets", _credential_archive(identity=self.identity, token=self._token, resources=resources)):
                    raise RuntimeError("Docker rejected engine credential bootstrap")
                self._client = client
                self._container = container
                target = f"{container.name}:{settings.engine_rpc_port}"
                if settings.engine_connect_host:
                    container.reload()
                    bindings = container.attrs["NetworkSettings"]["Ports"].get(f"{settings.engine_rpc_port}/tcp") or []
                    if not bindings:
                        raise RuntimeError("Docker did not publish an engine RPC port")
                    target = f"{settings.engine_connect_host}:{bindings[0]['HostPort']}"
                self._channel = grpc.insecure_channel(
                    target,
                    options=(("grpc.max_send_message_length", 128 * 1024 * 1024), ("grpc.max_receive_message_length", 128 * 1024 * 1024)),
                )
                self._stub = engine_runtime_pb2_grpc.PolarsEngineServiceStub(self._channel)
                self._await_health()
                self._alive = True
            except Exception:
                with contextlib.suppress(Exception):
                    container.remove(force=True)
                client.close()
                raise

    def _metadata(self) -> tuple[tuple[str, str], ...]:
        return ((_ENGINE_TOKEN_METADATA_KEY, self._token),)

    def _await_health(self) -> None:
        assert self._stub is not None
        deadline = time.monotonic() + settings.engine_start_timeout_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                health = self._stub.Health(engine_runtime_pb2.EngineHealthRequest(), timeout=1, metadata=self._metadata())
                if health.ready and health.engine_identity == self.identity.resource_id and health.protocol_version == ENGINE_PROTOCOL_VERSION:
                    return
                last_error = RuntimeError("Engine health identity or protocol did not match launch specification")
            except grpc.RpcError as exc:
                last_error = exc
            time.sleep(0.1)
        raise RuntimeError(f"Timed out waiting for engine container health: {last_error}")

    def is_process_alive(self) -> bool:
        with self._lock:
            if not self._alive or self._container is None:
                return False
            try:
                self._container.reload()
                running = self._container.status == "running"
                if not running:
                    self._alive = False
                return running
            except Exception:
                self._alive = False
                return False

    def check_health(self) -> bool:
        return self.is_process_alive()

    def _submit(self, kind: str, payload: dict[str, object]) -> str:
        with self._lock:
            if not self.is_process_alive():
                self.start()
            assert self._stub is not None
            job_id = str(uuid.uuid4())
            self.current_job_id = job_id
            self._stub.SubmitJob(
                engine_runtime_pb2.EngineSubmitJobRequest(
                    protocol_version=ENGINE_PROTOCOL_VERSION,
                    job_id=job_id,
                    kind=kind,
                    payload=dict_to_struct(payload),
                ),
                timeout=settings.engine_start_timeout_seconds,
                metadata=self._metadata(),
            )
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
        return self._submit(
            "export",
            {
                "datasource_config": datasource_config,
                "steps": steps,
                "output_path": output_path,
                "export_format": export_format,
                "additional_datasources": additional_datasources or {},
            },
        )

    def get_schema(self, datasource_config: dict, steps: list[dict], additional_datasources: dict[str, dict] | None = None) -> str:
        return self._submit("schema", {"datasource_config": datasource_config, "steps": steps, "additional_datasources": additional_datasources or {}})

    def get_row_count(self, datasource_config: dict, steps: list[dict], additional_datasources: dict[str, dict] | None = None) -> str:
        return self._submit("row_count", {"datasource_config": datasource_config, "steps": steps, "additional_datasources": additional_datasources or {}})

    def _watch_job(self, job_id: str) -> None:
        try:
            assert self._stub is not None
            stream = self._stub.WatchJob(engine_runtime_pb2.EngineWatchJobRequest(job_id=job_id), metadata=self._metadata())
            for event in stream:
                which = event.WhichOneof("event")
                if which == "progress":
                    payload = json_format.MessageToDict(event.progress, preserving_proto_field_name=True)
                    with self._lock:
                        self._pending_progress.setdefault(job_id, deque()).append(EngineProgressEvent(job_id=job_id, event=payload))
                elif which == "result":
                    with self._lock:
                        self._pending_results[job_id] = _result_from_message(event.result)
                        if self.current_job_id == job_id:
                            self.current_job_id = None
                    return
        except Exception as exc:
            logger.warning("Engine job watcher failed for %s: %s", job_id, exc)
            with self._lock:
                self._pending_results[job_id] = EngineResult(job_id=job_id, data=None, error=str(exc), error_kind="engine_rpc_lost", error_details={})
                if self.current_job_id == job_id:
                    self.current_job_id = None

    def get_result(self, timeout: float = 1.0, job_id: str | None = None) -> EngineResult | None:
        expected = job_id or self.current_job_id
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                if expected and expected in self._pending_results:
                    return self._pending_results.pop(expected)
                if expected and not self.is_process_alive():
                    return EngineResult(
                        job_id=expected, data=None, error="Engine container died unexpectedly", error_kind="engine_container_died", error_details={}
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
            container = self._container
            stub = self._stub
            if container is None:
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
                    container.stop(timeout=settings.engine_shutdown_grace_seconds)
            with contextlib.suppress(Exception):
                container.remove(force=True)
            if self._channel is not None:
                self._channel.close()
            if self._client is not None:
                self._client.close()
            self._channel = None
            self._client = None
            self._container = None
            self._stub = None
            self._alive = False
            self.current_job_id = None


def _result_from_message(message: engine_runtime_pb2.EngineJobResult) -> EngineResult:
    data = json_format.MessageToDict(message.data, preserving_proto_field_name=True) if message.HasField("data") else None
    details = json_format.MessageToDict(message.error_details, preserving_proto_field_name=True) if message.HasField("error_details") else None
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
