from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import grpc
import pytest

from dataforge_protocol import compute_pb2, compute_worker_runtime_pb2, enums_pb2, worker_runtime_pb2
from runtime.compute_worker_credentials import ObjectStoreCredentials, resolve_compute_worker_credentials
from runtime.config import settings
from runtime.docker_compute_worker import (
    DockerComputeWorker,
    _compute_worker_object_store_endpoint,
    _container_name,
    _container_rpc_target,
    _effective_resources,
    docker_host_registry,
    reconcile_deployment_containers,
    validate_compute_worker_runtime_readiness,
)
from runtime.docker_hosts import DockerHostRegistry, DockerHostSpec

_LOCAL_HOST = DockerHostSpec(name="local", docker_host="unix:///var/run/docker.sock", engine_network="net-test")
_HOST_CONNECTED_LOCAL = DockerHostSpec(name="local", docker_host="unix:///var/run/docker.sock", connect_host="127.0.0.1", engine_network="net-test")
_REMOTE_HOST = DockerHostSpec(name="node-b", docker_host="tcp://10.0.0.5:2375", connect_host="10.0.0.5", engine_network="net-test")


class _ProbeClient:
    """Minimal daemon answering a host probe."""

    def __init__(self, *, cpus: int = 4, image_id: str = "sha256:abc") -> None:
        self.images = type("Images", (), {"get": staticmethod(lambda _name: type("Image", (), {"id": image_id})())})()
        self.networks = type("Networks", (), {"get": staticmethod(lambda _name: object())})()
        self._cpus = cpus

    def ping(self) -> bool:
        return True

    def info(self) -> dict[str, object]:
        return {"NCPU": self._cpus}

    def close(self) -> None:
        return None


def _ready_registry(monkeypatch, *, cpus: int = 4) -> DockerHostRegistry:
    """Mark every configured host healthy without touching Docker."""
    monkeypatch.setattr("runtime.docker_hosts.open_docker_client", lambda _spec, **_kwargs: _ProbeClient(cpus=cpus))
    registry = docker_host_registry()
    assert all(registry.probe_all().values())
    return registry


def test_effective_resources_resolves_zero_threads_to_logical_cpu_count(monkeypatch) -> None:
    monkeypatch.setattr(settings, "polars_cores_available", 0)

    resources = _effective_resources({"max_threads": 0})

    assert resources["max_threads"] == (os.cpu_count() or 1)
    assert resources["max_threads"] > 0


def test_effective_resources_caps_requested_threads_to_global_limit(monkeypatch) -> None:
    monkeypatch.setattr(settings, "polars_cores_available", 4)

    assert _effective_resources({"max_threads": 8})["max_threads"] == 4


def test_effective_resources_uses_docker_cpu_count_for_auto(monkeypatch) -> None:
    monkeypatch.setattr(settings, "polars_cores_available", 0)

    assert _effective_resources({}, runtime_cpu_count=5)["max_threads"] == 5


def _identity(scope: int = enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE) -> compute_pb2.ComputeWorkerIdentity:
    return compute_pb2.ComputeWorkerIdentity(
        scope=scope,
        reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
        resource_id="analysis-1",
        analysis_id="analysis-1",
    )


def test_engine_credentials_fetch_namespace_scoped_identity_from_backend(monkeypatch) -> None:
    requests: list[tuple[str, str]] = []

    class FakeClient:
        def engine_credentials(self, *, namespace: str, role: str):
            requests.append((namespace, role))
            return worker_runtime_pb2.WorkerComputeWorkerCredentialsResponse(
                access_key="ns-reader",
                secret_key="ns-secret",
            )

    monkeypatch.setattr("runtime.compute_worker_credentials.client_from_env", lambda: FakeClient())

    credentials = resolve_compute_worker_credentials("tenant-a", _identity())

    assert requests == [("tenant-a", "reader")]
    assert credentials.access_key == "ns-reader"
    assert credentials.secret_key == "ns-secret"

    resolve_compute_worker_credentials("tenant-b", _identity(enums_pb2.COMPUTE_WORKER_SCOPE_BUILD))
    assert requests[-1] == ("tenant-b", "builder")


def test_unpinned_engine_image_warns_in_prod_but_is_allowed(monkeypatch, caplog) -> None:
    from runtime.docker_compute_worker import _warn_unpinned_compute_worker_image

    monkeypatch.setattr(settings, "prod_mode_enabled", True)
    monkeypatch.setattr(settings, "engine_image", "registry.example/dataforge-engine:latest")

    with caplog.at_level(logging.WARNING):
        _warn_unpinned_compute_worker_image()

    assert "not digest-pinned" in caplog.text

    monkeypatch.setattr(settings, "engine_image", f"registry.example/dataforge-engine@sha256:{'a' * 64}")
    _warn_unpinned_compute_worker_image()
    assert caplog.text.count("not digest-pinned") == 1


def test_container_name_is_dns_safe_and_bounded(monkeypatch) -> None:
    monkeypatch.setattr(settings, "engine_connect_host", "")
    identity = compute_pb2.ComputeWorkerIdentity(
        scope=enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE,
        reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
        resource_id="4675dc19-dced-4163-b9b2-d168e2cad57d",
        analysis_id="analysis-1",
    )

    name = _container_name(identity=identity, namespace="default")
    second = _container_name(identity=identity, namespace="default")

    # Docker resolves container names as DNS labels: max 63 chars, no "_".
    assert len(name) <= 63
    assert "_" not in name
    assert name != second  # full-identity hash suffix keeps them unique


def test_container_rpc_target_uses_unique_container_dns_name(monkeypatch) -> None:
    class Container:
        name = "/dataforge-engine-analysis-abc123"
        status = "running"

        def reload(self) -> None:
            return None

    monkeypatch.setattr(settings, "engine_rpc_port", 50053)

    assert _container_rpc_target(Container(), _LOCAL_HOST) == "dataforge-engine-analysis-abc123:50053"


def test_container_rpc_target_uses_dns_without_polling_docker(monkeypatch) -> None:
    class Container:
        name = "/dataforge-engine-analysis-starting"
        status = "created"

        def reload(self) -> None:
            raise AssertionError("Docker status is observed only if gRPC readiness fails")

    monkeypatch.setattr(settings, "engine_rpc_port", 50053)
    container = Container()

    assert _container_rpc_target(container, _LOCAL_HOST) == "dataforge-engine-analysis-starting:50053"
    assert container.status == "created"


def test_container_rpc_target_dials_the_host_connect_address_for_published_ports(monkeypatch) -> None:
    class Container:
        name = "/dataforge-engine-analysis-remote"
        attrs = {"NetworkSettings": {"Ports": {"50053/tcp": [{"HostIp": "0.0.0.0", "HostPort": "40123"}]}}}

        def reload(self) -> None:
            return None

    monkeypatch.setattr(settings, "engine_rpc_port", 50053)

    assert _container_rpc_target(Container(), _REMOTE_HOST) == "10.0.0.5:40123"


def test_await_listening_waits_for_channel_then_checks_health_once(monkeypatch) -> None:
    calls: list[object] = []

    class ReadyFuture:
        def result(self, *, timeout: float) -> None:
            calls.append(("ready", timeout))

    class Stub:
        def Health(self, _request, *, timeout: float):  # noqa: N802 - generated gRPC method
            calls.append(("health", timeout))
            return compute_worker_runtime_pb2.ComputeWorkerHealthResponse()

    engine = DockerComputeWorker(_identity())
    engine._channel = object()  # type: ignore[assignment]
    engine._stub = Stub()  # type: ignore[assignment]
    monkeypatch.setattr(settings, "engine_start_timeout_seconds", 30)
    monkeypatch.setattr(grpc, "channel_ready_future", lambda channel: ReadyFuture())

    engine._await_listening()

    assert calls[0][0] == "ready"
    assert calls[0][1] == pytest.approx(30, abs=0.001)
    assert calls[1] == ("health", 2.0)


def test_await_listening_retries_transient_health_deadlines_within_start_deadline(monkeypatch) -> None:
    calls: list[object] = []
    retry_delays: list[float] = []

    class ReadyFuture:
        def result(self, *, timeout: float) -> None:
            calls.append(("ready", timeout))

    class TransientHealthError(grpc.RpcError):
        def code(self):
            return grpc.StatusCode.DEADLINE_EXCEEDED

        def details(self):
            return "listener is temporarily busy"

    class Stub:
        attempts = 0

        def Health(self, _request, *, timeout: float):  # noqa: N802 - generated gRPC method
            calls.append(("health", timeout))
            self.attempts += 1
            if self.attempts == 1:
                raise TransientHealthError()
            return compute_worker_runtime_pb2.ComputeWorkerHealthResponse()

    engine = DockerComputeWorker(_identity())
    engine._channel = object()  # type: ignore[assignment]
    engine._stub = Stub()  # type: ignore[assignment]
    monkeypatch.setattr(settings, "engine_start_timeout_seconds", 30)
    monkeypatch.setattr(grpc, "channel_ready_future", lambda channel: ReadyFuture())
    monkeypatch.setattr("runtime.docker_compute_worker.time.sleep", retry_delays.append)

    engine._await_listening()

    assert [call[0] for call in calls] == ["ready", "health", "health"]
    assert retry_delays == [0.1]


def test_engine_object_store_endpoint_prefers_the_host_override(monkeypatch) -> None:
    monkeypatch.setattr(settings, "object_store_endpoint", "http://127.0.0.1:9000")
    host = DockerHostSpec(name="local", docker_host="unix:///var/run/docker.sock", object_store_endpoint="http://rustfs:9000")

    assert _compute_worker_object_store_endpoint(host) == "http://rustfs:9000"
    # A remote host without an override gets the worker's endpoint unchanged;
    # the loopback rewrite only applies to a host-connected local daemon.
    assert _compute_worker_object_store_endpoint(_REMOTE_HOST) == "http://127.0.0.1:9000"
    assert _compute_worker_object_store_endpoint(_HOST_CONNECTED_LOCAL) == "http://host.docker.internal:9000"


def test_export_submits_object_store_artifact_instead_of_worker_path(monkeypatch, tmp_path: Path) -> None:
    engine = DockerComputeWorker(_identity(), namespace="tenant-a")
    submitted: dict[str, object] = {}
    presigned: dict[str, object] = {}

    def submit(kind: str, payload: dict[str, object], *, job_id: str | None = None) -> str:
        submitted.update({"kind": kind, "payload": payload, "job_id": job_id})
        return job_id or "missing"

    monkeypatch.setattr(engine, "_submit", submit)
    monkeypatch.setattr(
        "runtime.docker_compute_worker.presigned_put_url",
        lambda target_url, **options: presigned.update(target_url=target_url, **options) or "http://object-store/presigned-put",
    )
    engine._host = _HOST_CONNECTED_LOCAL
    monkeypatch.setattr(settings, "object_store_endpoint", "http://127.0.0.1:9000")
    output_path = tmp_path / "result.parquet"

    job_id = engine.export({}, [], str(output_path), "parquet")

    payload = submitted["payload"]
    assert isinstance(payload, dict)
    assert "output_path" not in payload
    assert str(payload["artifact_url"]).startswith(f"s3://tenant-a/runtime-staging/analysis-1/{job_id}/")
    assert payload["artifact_upload_url"] == "http://object-store/presigned-put"
    assert presigned["endpoint_url"] == "http://host.docker.internal:9000"
    assert presigned["content_type"] == "application/octet-stream"
    assert engine._artifact_transfers[job_id][0] == output_path


def test_startup_reconciliation_removes_only_current_deployment_engines(monkeypatch) -> None:
    removed: list[str] = []

    class Api:
        def containers(self, *, all: bool, filters: dict[str, object]):
            assert all
            assert filters == {"label": ["io.dataforge.managed=true", "io.dataforge.deployment=test-deployment"]}
            return [{"Id": "container-1", "State": "running"}]

        def remove_container(self, container_id: str, *, force: bool) -> None:
            assert force
            removed.append(container_id)

    class Client:
        api = Api()

        def close(self) -> None:
            return None

    monkeypatch.setattr(settings, "deployment_id", "test-deployment")
    monkeypatch.setattr("runtime.docker_compute_worker.docker.DockerClient", lambda **_kwargs: Client())

    assert reconcile_deployment_containers() == 1
    assert removed == ["container-1"]


def test_periodic_reconciliation_removes_only_stopped_owned_containers(monkeypatch) -> None:
    removed: list[str] = []

    class Api:
        def containers(self, *, all: bool, filters: dict[str, object]):
            assert all
            assert filters == {
                "label": [
                    "io.dataforge.managed=true",
                    "io.dataforge.deployment=test-deployment",
                    "io.dataforge.supervisor=worker-1",
                ]
            }
            return [
                {"Id": "running", "State": "running"},
                {"Id": "starting", "State": "created"},
                {"Id": "stopped", "State": "exited"},
                {"Id": "dead", "State": "dead"},
            ]

        def remove_container(self, container_id: str, *, force: bool) -> None:
            assert force
            removed.append(container_id)

    class Client:
        api = Api()

        def close(self) -> None:
            return None

    monkeypatch.setattr(settings, "deployment_id", "test-deployment")
    monkeypatch.setattr("runtime.docker_compute_worker.docker.DockerClient", lambda **_kwargs: Client())

    assert reconcile_deployment_containers(supervisor_id="worker-1", remove_running=False) == 2
    assert removed == ["stopped", "dead"]


def test_periodic_reconciliation_removes_old_untracked_running_containers(monkeypatch) -> None:
    removed: list[str] = []
    old = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    current = datetime.now(UTC).isoformat()

    class Api:
        def containers(self, *, all: bool, filters: dict[str, object]):
            assert all
            return [
                {"Id": "old-running", "State": "running", "Labels": {"io.dataforge.created-at": old}},
                {"Id": "new-running", "State": "running", "Labels": {"io.dataforge.created-at": current}},
                {"Id": "unknown-created-at", "State": "running", "Labels": {}},
            ]

        def remove_container(self, container_id: str, *, force: bool) -> None:
            assert force
            removed.append(container_id)

    class Client:
        api = Api()

        def close(self) -> None:
            return None

    monkeypatch.setattr(settings, "deployment_id", "test-deployment")
    monkeypatch.setattr("runtime.docker_compute_worker.docker.DockerClient", lambda **_kwargs: Client())

    assert (
        reconcile_deployment_containers(
            supervisor_id="worker-1",
            running_grace_seconds=5,
        )
        == 1
    )
    assert removed == ["old-running"]


def test_startup_reconciliation_removes_untracked_running_containers(monkeypatch) -> None:
    removed: list[str] = []

    class Api:
        def containers(self, *, all: bool, filters: dict[str, object]):
            assert all
            return [
                {"Id": "tracked", "State": "running"},
                {"Id": "orphan-running", "State": "running"},
                {"Id": "orphan-created", "State": "created"},
            ]

        def remove_container(self, container_id: str, *, force: bool) -> None:
            assert force
            removed.append(container_id)

    class Client:
        api = Api()

        def close(self) -> None:
            return None

    monkeypatch.setattr(settings, "deployment_id", "test-deployment")
    monkeypatch.setattr("runtime.docker_compute_worker.docker.DockerClient", lambda **_kwargs: Client())

    assert reconcile_deployment_containers(supervisor_id="worker-1", keep_container_ids={"tracked"}) == 2
    assert removed == ["orphan-running", "orphan-created"]


def test_coordinator_takeover_removes_stale_generation_and_keeps_current_generation(monkeypatch) -> None:
    removed: list[str] = []

    class Api:
        def containers(self, *, all: bool, filters: dict[str, object]):
            assert all
            assert filters == {"label": ["io.dataforge.managed=true", "io.dataforge.deployment=test-deployment"]}
            return [
                {"Id": "stale-running", "State": "running", "Labels": {"io.dataforge.coordinator-generation": "4"}},
                {"Id": "unlabeled-running", "State": "running", "Labels": {}},
                {"Id": "current-running", "State": "running", "Labels": {"io.dataforge.coordinator-generation": "5"}},
            ]

        def remove_container(self, container_id: str, *, force: bool) -> None:
            assert force
            removed.append(container_id)

    class Client:
        api = Api()

        def close(self) -> None:
            return None

    monkeypatch.setattr(settings, "deployment_id", "test-deployment")
    monkeypatch.setattr("runtime.docker_compute_worker.docker.DockerClient", lambda **_kwargs: Client())

    assert reconcile_deployment_containers(coordinator_generation=5, keep_container_ids=("current-running",)) == 2
    assert removed == ["stale-running", "unlabeled-running"]


def test_stale_coordinator_is_rejected_before_engine_start_or_submit(monkeypatch) -> None:
    def fenced() -> None:
        raise RuntimeError("stale coordinator")

    def docker_client_must_not_be_opened(**_kwargs):
        raise AssertionError("stale coordinator reached Docker")

    monkeypatch.setattr("runtime.docker_compute_worker.docker.DockerClient", docker_client_must_not_be_opened)
    engine = DockerComputeWorker(_identity(), coordinator_guard=fenced)

    with pytest.raises(RuntimeError, match="stale coordinator"):
        engine.start()
    with pytest.raises(RuntimeError, match="stale coordinator"):
        engine.preview({}, [])


def test_stale_coordinator_cannot_remove_containers_during_reconciliation(monkeypatch) -> None:
    removed: list[str] = []

    class Api:
        def containers(self, *, all: bool, filters: dict[str, object]):
            assert all
            return [{"Id": "stale", "State": "running", "Labels": {"io.dataforge.coordinator-generation": "4"}}]

        def remove_container(self, container_id: str, *, force: bool) -> None:
            removed.append(container_id)

    class Client:
        api = Api()

        def close(self) -> None:
            return None

    guard_calls = 0

    def fenced() -> None:
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls == 2:
            raise RuntimeError("stale coordinator")

    monkeypatch.setattr(settings, "deployment_id", "test-deployment")
    monkeypatch.setattr("runtime.docker_compute_worker.docker.DockerClient", lambda **_kwargs: Client())

    with pytest.raises(RuntimeError, match="stale coordinator"):
        reconcile_deployment_containers(coordinator_generation=5, coordinator_guard=fenced)

    assert guard_calls == 2
    assert removed == []


def test_stale_coordinator_shutdown_detaches_without_mutating_container(monkeypatch) -> None:
    actions: list[str] = []

    class Container:
        status = "running"

        def reload(self) -> None:
            actions.append("reload")

        def stop(self, *, timeout: float) -> None:
            actions.append("stop")

        def remove(self, *, force: bool) -> None:
            actions.append("remove")

    class Stub:
        def Shutdown(self, *_args, **_kwargs) -> None:  # noqa: N802 - generated gRPC method
            actions.append("shutdown")

    class Handle:
        def close(self) -> None:
            actions.append("close")

    def fenced() -> None:
        raise RuntimeError("stale")

    engine = DockerComputeWorker(_identity(), coordinator_generation=4, coordinator_guard=fenced)
    engine._container = Container()
    engine._container_id = "engine-container"
    engine._stub = Stub()  # type: ignore[assignment]
    engine._channel = Handle()  # type: ignore[assignment]
    engine._client = Handle()
    engine._artifact_transfers["job"] = (Path("/tmp/artifact"), "s3://bucket/artifact")
    monkeypatch.setattr(settings, "engine_shutdown_grace_seconds", 0)
    monkeypatch.setattr("runtime.docker_compute_worker.delete_object", lambda _url: actions.append("delete-artifact"))

    engine.shutdown()

    assert actions == ["close", "close"]
    assert engine._container is None
    assert engine._container_id is None
    assert engine._stub is None
    assert engine._channel is None
    assert engine._client is None
    assert engine._artifact_transfers == {}


def test_failed_start_leaves_container_for_current_generation_reconciliation() -> None:
    actions: list[str] = []

    class Container:
        def remove(self, *, force: bool) -> None:
            actions.append("remove")

    class Client:
        def close(self) -> None:
            actions.append("close")

    def fenced() -> None:
        raise RuntimeError("stale")

    engine = DockerComputeWorker(_identity(), coordinator_generation=4, coordinator_guard=fenced)
    engine._container_id = "partially-started"

    engine._cleanup_failed_start(Container(), Client())

    assert actions == ["close"]
    assert engine._container_id is None


def test_coordinator_loss_mid_shutdown_prevents_stop_remove_and_artifact_delete(monkeypatch) -> None:
    actions: list[str] = []
    guard_calls = 0

    class Container:
        status = "running"

        def reload(self) -> None:
            actions.append("reload")

        def stop(self, *, timeout: float) -> None:
            actions.append("stop")

        def remove(self, *, force: bool) -> None:
            actions.append("remove")

    class Stub:
        def Shutdown(self, *_args, **_kwargs) -> None:  # noqa: N802 - generated gRPC method
            actions.append("shutdown")

    class Handle:
        def close(self) -> None:
            actions.append("close")

    def guard() -> None:
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls == 2:
            raise RuntimeError("stale")

    engine = DockerComputeWorker(_identity(), coordinator_generation=4, coordinator_guard=guard)
    engine._container = Container()
    engine._container_id = "engine-container"
    engine._stub = Stub()  # type: ignore[assignment]
    engine._channel = Handle()  # type: ignore[assignment]
    engine._client = Handle()
    engine._artifact_transfers["job"] = (Path("/tmp/artifact"), "s3://bucket/artifact")
    monkeypatch.setattr(settings, "engine_shutdown_grace_seconds", 0)
    monkeypatch.setattr("runtime.docker_compute_worker.delete_object", lambda _url: actions.append("delete-artifact"))

    engine.shutdown()

    assert guard_calls == 2
    assert actions == ["shutdown", "reload", "close", "close"]
    assert engine._container is None
    assert engine._container_id is None
    assert engine._artifact_transfers == {}


def test_intentional_shutdown_is_not_reported_as_container_crash(monkeypatch) -> None:
    engine = DockerComputeWorker(_identity())
    engine._shutdown_requested = True
    monkeypatch.setattr(engine, "is_process_alive", lambda: False)

    result = engine.get_result(job_id="job-1", timeout=0)

    assert result is not None
    assert result.error == "Engine shutdown requested"
    assert result.error_kind == "engine_shutdown"


def test_initialize_fails_fast_on_identity_collision(monkeypatch) -> None:
    engine = DockerComputeWorker(_identity())
    engine._host = _LOCAL_HOST
    calls = 0

    class AlreadyInitialized(grpc.RpcError):
        def code(self):
            return grpc.StatusCode.FAILED_PRECONDITION

        def details(self):
            return "Engine already initialized for another-engine"

    class Stub:
        def Initialize(self, request, timeout):  # noqa: N802 - gRPC stub name
            nonlocal calls
            del request, timeout
            calls += 1
            raise AlreadyInitialized()

    engine._stub = Stub()  # type: ignore[assignment]
    monkeypatch.setattr(settings, "engine_start_timeout_seconds", 120)

    with pytest.raises(RuntimeError, match="Engine identity collision"):
        engine._initialize(
            resources={"max_threads": 1, "max_memory_mb": 256, "streaming_chunk_size": 0},
            credentials=ObjectStoreCredentials(access_key="access", secret_key="secret"),
        )

    assert calls == 1


def test_initialize_does_not_retry_transient_rpc_failures(monkeypatch) -> None:
    engine = DockerComputeWorker(_identity())
    engine._host = _LOCAL_HOST
    calls = 0

    class Unavailable(grpc.RpcError):
        def code(self):
            return grpc.StatusCode.UNAVAILABLE

        def details(self):
            return "engine temporarily unavailable"

    class Stub:
        def Initialize(self, request, timeout):  # noqa: N802 - generated gRPC method
            nonlocal calls
            del request, timeout
            calls += 1
            raise Unavailable()

    engine._stub = Stub()  # type: ignore[assignment]
    monkeypatch.setattr(settings, "engine_start_timeout_seconds", 120)

    with pytest.raises(RuntimeError, match="Engine initialization failed"):
        engine._initialize(
            resources={"max_threads": 1, "max_memory_mb": 256, "streaming_chunk_size": 0},
            credentials=ObjectStoreCredentials(access_key="access", secret_key="secret"),
        )

    assert calls == 1


def test_oom_exit_is_reported_with_container_details() -> None:
    engine = DockerComputeWorker(_identity())

    class Container:
        id = "container-oom"
        status = "exited"
        attrs = {"State": {"ExitCode": 137, "OOMKilled": True}}

        def reload(self) -> None:
            return None

    engine._container = Container()
    engine._container_id = "container-oom"
    engine._alive = True

    result = engine.get_result(job_id="job-oom", timeout=0)

    assert result is not None
    assert result.error_kind == "engine_oom_killed"
    assert result.error_details == {
        "container_id": "container-oom",
        "exit_code": 137,
        "oom_killed": True,
        "termination_reason": "oom_killed",
    }
    assert result.error == "Engine container terminated (reason=oom_killed, exit_code=137, oom_killed=True)"


def test_repeated_grpc_health_failures_do_not_evict_a_running_container(monkeypatch) -> None:
    class Container:
        id = "healthy-container"
        status = "running"
        attrs = {"State": {"Status": "running"}}
        reloads = 0

        def reload(self) -> None:
            self.reloads += 1

    engine = DockerComputeWorker(_identity())
    container = Container()
    notifications: list[bool] = []
    engine._container = container
    engine._container_id = container.id
    engine._alive = True
    engine.bind_capacity_notifier(lambda: notifications.append(True))
    engine._heartbeat_stop.clear()
    monkeypatch.setattr(settings, "engine_heartbeat_interval_seconds", 0)
    monkeypatch.setattr("runtime.docker_compute_worker._LIVENESS_CACHE_SECONDS", 0.0)

    class Stub:
        calls = 0

        def Health(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 3:
                engine._heartbeat_stop.set()
            raise RuntimeError("transient gRPC health delay")

    stub = Stub()
    engine._stub = stub  # type: ignore[assignment]

    engine._heartbeat_loop()

    assert stub.calls == 3
    assert container.reloads == 3
    assert engine.last_known_alive is True
    assert notifications == []


def test_job_watch_resumes_clean_stream_close_without_leaking_active_job(monkeypatch) -> None:
    engine = DockerComputeWorker(_identity())
    job_id = "job-resume"
    result = compute_worker_runtime_pb2.ComputeWorkerJobResult(job_id=job_id, data_json=b'{"rows":[1]}')
    progress = compute_worker_runtime_pb2.ComputeWorkerJobEvent(job_id=job_id, sequence=1, progress_json=b'{"type":"compute_start"}')
    terminal = compute_worker_runtime_pb2.ComputeWorkerJobEvent(job_id=job_id, sequence=2, result=result)

    class Stub:
        requests: list[int] = []

        def WatchJob(self, request, metadata):
            del metadata
            self.requests.append(request.after_sequence)
            return iter((progress,)) if len(self.requests) == 1 else iter((terminal,))

        def GetJobResult(self, request, *, timeout, metadata):
            del request, timeout, metadata
            return result

    stub = Stub()
    engine._stub = stub  # type: ignore[assignment]
    engine._active_job_ids.add(job_id)
    engine.current_job_id = job_id
    monkeypatch.setattr(engine._heartbeat_stop, "wait", lambda _timeout: False)

    engine._watch_job(job_id)

    published = engine.get_result(timeout=0, job_id=job_id)
    assert published is not None
    assert published.data == {"rows": [1]}
    assert stub.requests == [0, 1]
    assert engine.current_job_id is None
    assert job_id not in engine._active_job_ids


def test_job_watch_recovers_terminal_result_after_progress_cursor_eviction() -> None:
    engine = DockerComputeWorker(_identity())
    job_id = "job-evicted"
    result = compute_worker_runtime_pb2.ComputeWorkerJobResult(job_id=job_id, data_json=b'{"rows":[1]}')

    class CursorEvicted(grpc.RpcError):
        def code(self):
            return grpc.StatusCode.OUT_OF_RANGE

    class Stub:
        def WatchJob(self, request, metadata):
            del request, metadata
            raise CursorEvicted()

        def GetJobResult(self, request, *, timeout, metadata):
            del request, timeout, metadata
            return result

    engine._stub = Stub()  # type: ignore[assignment]
    engine._active_job_ids.add(job_id)
    engine.current_job_id = job_id

    engine._watch_job(job_id)

    published = engine.get_result(timeout=0, job_id=job_id)
    assert published is not None
    assert published.data == {"rows": [1]}
    assert published.error is None


def test_runtime_readiness_probes_every_host_and_requires_one_ready(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        settings,
        "engine_docker_hosts",
        '[{"name": "local", "docker_host": "unix:///var/run/docker.sock"},'
        ' {"name": "node-b", "docker_host": "tcp://10.0.0.5:2375", "connect_host": "10.0.0.5"}]',
    )

    class BrokenClient:
        def ping(self) -> None:
            raise OSError("connection refused")

        def close(self) -> None:
            return None

    def open_client(spec: DockerHostSpec, **_kwargs):
        calls.append(spec.name)
        return _ProbeClient() if spec.name == "local" else BrokenClient()

    monkeypatch.setattr("runtime.docker_compute_worker._warn_unpinned_compute_worker_image", lambda: calls.append("image-reference"))
    monkeypatch.setattr("runtime.docker_hosts.open_docker_client", open_client)
    registry = docker_host_registry()
    monkeypatch.setattr(registry, "start_health_monitor", lambda interval: calls.append(f"monitor:{interval}"))

    validate_compute_worker_runtime_readiness()

    assert calls == ["image-reference", "local", "node-b", f"monitor:{settings.engine_docker_host_health_interval_seconds}"]
    statuses = {status.name: status.healthy for status in registry.snapshot()}
    assert statuses == {"local": True, "node-b": False}


def test_runtime_readiness_fails_when_no_host_answers(monkeypatch) -> None:
    class BrokenClient:
        def ping(self) -> None:
            raise OSError("connection refused")

        def close(self) -> None:
            return None

    monkeypatch.setattr("runtime.docker_hosts.open_docker_client", lambda _spec, **_kwargs: BrokenClient())

    with pytest.raises(RuntimeError, match="No Docker host is available"):
        validate_compute_worker_runtime_readiness()


def test_container_nano_cpus_skips_hard_quota_only_for_host_connected_local_engines() -> None:
    from runtime.docker_compute_worker import _container_nano_cpus

    assert _container_nano_cpus(1, host=_HOST_CONNECTED_LOCAL) is None
    assert _container_nano_cpus(4, host=_HOST_CONNECTED_LOCAL) is None

    assert _container_nano_cpus(1, host=_LOCAL_HOST) == 1_000_000_000
    assert _container_nano_cpus(0, host=_LOCAL_HOST) is None
    # A remote machine is a dedicated compute host; it keeps the quota even
    # though it also dials engines through published ports.
    assert _container_nano_cpus(2, host=_REMOTE_HOST) == 2_000_000_000


def test_resolve_launch_context_caches_daemon_and_image_lookups_per_host(monkeypatch) -> None:
    class Image:
        id = "sha256:abc"

    class Images:
        calls = 0

        def get(self, name: str):
            self.calls += 1
            assert name == "engine:test"
            return Image()

    class Networks:
        calls = 0

        def get(self, name: str):
            self.calls += 1
            assert name == "net-test"
            return object()

    class Client:
        def __init__(self) -> None:
            self.images = Images()
            self.networks = Networks()
            self.info_calls = 0

        def info(self):
            self.info_calls += 1
            return {"NCPU": 6}

    registry = DockerHostRegistry([_LOCAL_HOST, _REMOTE_HOST], engine_image="engine:test")

    client = Client()
    first = registry.launch_context(_LOCAL_HOST, client)
    second = registry.launch_context(_LOCAL_HOST, client)

    assert first == (6, "sha256:abc")
    assert second == first
    assert client.info_calls == 1
    assert client.images.calls == 1
    # The network is checked on every launch context resolution; it is cheap
    # and a removed network must fail fast.
    assert client.networks.calls == 2

    # Another host has its own daemon, image id and CPU count.
    other = Client()
    assert registry.launch_context(_REMOTE_HOST, other) == (6, "sha256:abc")
    assert other.info_calls == 1


def test_engine_credentials_are_cached_per_namespace_and_role(monkeypatch) -> None:
    requests: list[tuple[str, str]] = []

    class FakeClient:
        def engine_credentials(self, *, namespace: str, role: str):
            requests.append((namespace, role))
            return worker_runtime_pb2.WorkerComputeWorkerCredentialsResponse(access_key="ns-reader", secret_key="ns-secret")

    monkeypatch.setattr("runtime.compute_worker_credentials.client_from_env", lambda: FakeClient())

    first = resolve_compute_worker_credentials("tenant-a", _identity())
    second = resolve_compute_worker_credentials("tenant-a", _identity())

    assert first == second
    assert requests == [("tenant-a", "reader")]


def test_engine_credentials_singleflight_concurrent_cold_starts(monkeypatch) -> None:
    callers = 8
    barrier = threading.Barrier(callers)
    request_started = threading.Event()
    release_response = threading.Event()
    requests: list[tuple[str, str]] = []

    class FakeClient:
        def engine_credentials(self, *, namespace: str, role: str):
            requests.append((namespace, role))
            request_started.set()
            assert release_response.wait(2)
            return worker_runtime_pb2.WorkerComputeWorkerCredentialsResponse(access_key="ns-reader", secret_key="ns-secret")

    monkeypatch.setattr("runtime.compute_worker_credentials.client_from_env", lambda: FakeClient())

    def resolve() -> ObjectStoreCredentials:
        barrier.wait(timeout=2)
        return resolve_compute_worker_credentials("tenant-a", _identity())

    with ThreadPoolExecutor(max_workers=callers) as executor:
        futures = [executor.submit(resolve) for _ in range(callers)]
        assert request_started.wait(2)
        release_response.set()
        credentials = [future.result(timeout=2) for future in futures]

    assert len(set(credentials)) == 1
    assert requests == [("tenant-a", "reader")]


def test_engine_start_closes_docker_client_when_container_creation_fails(monkeypatch) -> None:
    class Containers:
        def create(self, **_kwargs):
            raise RuntimeError("Docker create failed")

    class Client:
        containers = Containers()
        closed = False

        def close(self) -> None:
            self.closed = True

    client = Client()
    _ready_registry(monkeypatch)
    engine = DockerComputeWorker(_identity(), namespace="tenant-a")
    monkeypatch.setattr("runtime.docker_compute_worker.resolve_compute_worker_credentials", lambda *_args: ObjectStoreCredentials("key", "secret"))
    monkeypatch.setattr("runtime.docker_compute_worker._resolve_launch_context", lambda _host, _client: (1, "image-id"))
    monkeypatch.setattr("runtime.docker_compute_worker._effective_resources", lambda *_args, **_kwargs: {"max_threads": 1, "max_memory_mb": 256})
    monkeypatch.setattr("runtime.docker_compute_worker.docker.DockerClient", lambda **_kwargs: client)

    # A request-level failure propagates unchanged; it is not a host failure.
    with pytest.raises(RuntimeError, match="Docker create failed"):
        engine.start()

    assert client.closed
    assert docker_host_registry().snapshot()[0].healthy


def test_engine_start_waits_for_rpc_listener_before_initializing(monkeypatch, caplog) -> None:
    calls: list[str] = []
    created: dict[str, object] = {}
    monkeypatch.setattr("runtime.docker_compute_worker._SLOW_COMPUTE_WORKER_START_SECONDS", 0.0)
    monkeypatch.setattr("runtime.docker_compute_worker.get_compute_request_id", lambda: "cold-preview-request")
    caplog.set_level(logging.WARNING, logger="runtime.docker_compute_worker")

    class Container:
        id = "engine-container"

        def start(self) -> None:
            calls.append("container.start")

    class Containers:
        def create(self, **kwargs):
            created.update(kwargs)
            calls.append("container.create")
            return Container()

    class Client:
        containers = Containers()

        def close(self) -> None:
            calls.append("client.close")

    client = Client()
    _ready_registry(monkeypatch)
    engine = DockerComputeWorker(_identity(), namespace="tenant-a")
    monkeypatch.setattr("runtime.docker_compute_worker.resolve_compute_worker_credentials", lambda *_args: ObjectStoreCredentials("key", "secret"))
    monkeypatch.setattr("runtime.docker_compute_worker._resolve_launch_context", lambda _host, _client: (1, "image-id"))
    monkeypatch.setattr(
        "runtime.docker_compute_worker._effective_resources",
        lambda *_args, **_kwargs: {"max_threads": 1, "max_memory_mb": 256, "streaming_chunk_size": 0},
    )
    monkeypatch.setattr("runtime.docker_compute_worker.docker.DockerClient", lambda **_kwargs: client)
    monkeypatch.setattr("runtime.docker_compute_worker._container_rpc_target", lambda _container, _host: "engine:50053")
    monkeypatch.setattr("runtime.docker_compute_worker.grpc.insecure_channel", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("runtime.docker_compute_worker.compute_worker_runtime_pb2_grpc.PolarsComputeWorkerServiceStub", lambda _channel: object())
    monkeypatch.setattr(engine, "_await_listening", lambda: calls.append("rpc.listener_ready"))
    monkeypatch.setattr(engine, "_initialize", lambda **_kwargs: calls.append("rpc.initialize"))
    monkeypatch.setattr(engine, "_heartbeat_loop", lambda: None)

    engine.start()

    assert calls == ["container.create", "container.start", "rpc.listener_ready", "rpc.initialize"]
    assert created["cpu_shares"] == 128
    assert created["labels"]["io.dataforge.docker-host"] == "local"
    assert engine.docker_host == "local"
    assert docker_host_registry().snapshot()[0].placements == 1
    startup_log = next(record.message for record in caplog.records if "Slow engine startup" in record.message)
    assert "request_id=cold-preview-request" in startup_log
    assert "namespace=tenant-a" in startup_log
    assert "engine_scope=analysis_interactive" in startup_log
    assert f"resource_id={engine.identity.resource_id}" in startup_log
    client.close()


def test_warm_worker_uses_the_standard_engine_runtime(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Container:
        id = "warm-container"

        def start(self) -> None:
            return None

    class Containers:
        def create(self, **kwargs):
            captured.update(kwargs)
            return Container()

    class Client:
        containers = Containers()

        def close(self) -> None:
            return None

    class Channel:
        def close(self) -> None:
            return None

    client = Client()
    monkeypatch.setattr(settings, "engine_connect_host", "")
    _ready_registry(monkeypatch)
    engine = DockerComputeWorker()
    monkeypatch.setattr("runtime.docker_compute_worker._resolve_launch_context", lambda _host, _client: (1, "image-id"))
    monkeypatch.setattr(
        "runtime.docker_compute_worker._effective_resources",
        lambda *_args, **_kwargs: {"max_threads": 1, "max_memory_mb": 256, "streaming_chunk_size": 0},
    )
    monkeypatch.setattr("runtime.docker_compute_worker.docker.DockerClient", lambda **_kwargs: client)
    monkeypatch.setattr("runtime.docker_compute_worker._container_rpc_target", lambda _container, _host: "warm-engine:50053")
    monkeypatch.setattr("runtime.docker_compute_worker.grpc.insecure_channel", lambda *_args, **_kwargs: Channel())
    monkeypatch.setattr("runtime.docker_compute_worker.compute_worker_runtime_pb2_grpc.PolarsComputeWorkerServiceStub", lambda _channel: object())
    monkeypatch.setattr(engine, "_await_listening", lambda: None)

    engine.start_warm_worker()

    environment = captured["environment"]
    assert isinstance(environment, dict)
    assert environment["ENGINE_INIT_TIMEOUT_SECONDS"] == "0"
    assert "ENGINE_PRELOAD_COMPUTE" not in environment
    assert captured["cpu_shares"] == 128
    assert docker_host_registry().snapshot()[0].placements == 1
    engine._detach_local_handles()
    assert docker_host_registry().snapshot()[0].placements == 0


class _FakeContainer:
    def __init__(self, status: str = "running") -> None:
        self.status = status
        self.reloads = 0

    def reload(self) -> None:
        self.reloads += 1


def test_liveness_probe_is_rate_limited(monkeypatch) -> None:
    engine = DockerComputeWorker(_identity(), namespace="tenant-a")
    container = _FakeContainer()
    engine._container = container
    engine._alive = True

    assert engine.is_process_alive()
    assert engine.is_process_alive()
    assert container.reloads == 1

    # Cached liveness answers without any daemon round trip at all.
    assert engine.last_known_alive is True
    assert container.reloads == 1


def test_liveness_probe_does_not_wait_for_the_lifecycle_lock() -> None:
    engine = DockerComputeWorker(_identity(), namespace="tenant-a")
    engine._container = _FakeContainer()
    engine._alive = True
    lock_held = threading.Event()
    release = threading.Event()

    def hold_lifecycle_lock() -> None:
        with engine._lock:
            lock_held.set()
            release.wait(5)

    holder = threading.Thread(target=hold_lifecycle_lock, daemon=True)
    holder.start()
    try:
        assert lock_held.wait(2)
        # A container boot can hold the lifecycle lock for minutes; status and
        # capacity callers must not queue behind it.
        started = time.monotonic()
        assert engine.is_process_alive()
        assert time.monotonic() - started < 1.0
    finally:
        release.set()
        holder.join(timeout=5)


def test_submit_releases_the_lifecycle_lock_during_the_rpc(monkeypatch) -> None:
    engine = DockerComputeWorker(_identity(), namespace="tenant-a")
    engine._container = _FakeContainer()
    engine._alive = True
    engine._token = "token"
    lock_free_during_rpc = threading.Event()

    class FakeStub:
        def SubmitJob(self, request, timeout=None, metadata=None):  # noqa: N802 - gRPC stub name
            probe = threading.Thread(target=lambda: engine._lock.acquire(timeout=2) and (lock_free_during_rpc.set(), engine._lock.release()))
            probe.start()
            probe.join(timeout=3)
            return compute_worker_runtime_pb2.ComputeWorkerJobReference(job_id=request.job_id)

    engine._stub = FakeStub()
    monkeypatch.setattr(engine, "_watch_job", lambda job_id: None)

    job_id = engine._submit("preview", {})

    assert job_id
    assert lock_free_during_rpc.is_set()


def test_submit_restarts_an_engine_that_was_shut_down(monkeypatch) -> None:
    """A reaped or crashed engine is restarted by the next job, not reported broken."""
    engine = DockerComputeWorker(_identity(), namespace="tenant-a")
    submitted: list[str] = []

    class FakeStub:
        def SubmitJob(self, request, timeout=None, metadata=None):  # noqa: N802 - gRPC stub name
            submitted.append(request.job_id)
            return compute_worker_runtime_pb2.ComputeWorkerJobReference(job_id=request.job_id)

    def fake_start() -> None:
        engine._container = _FakeContainer()
        engine._stub = FakeStub()
        engine._alive = True

    monkeypatch.setattr(engine, "start", fake_start)
    monkeypatch.setattr(engine, "_watch_job", lambda job_id: None)

    job_id = engine._submit("preview", {})

    assert submitted == [job_id]
