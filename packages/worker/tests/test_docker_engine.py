from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import grpc

from dataforge_protocol import compute_pb2, engine_runtime_pb2, enums_pb2, worker_runtime_pb2
from runtime.config import settings
from runtime.docker_engine import (
    DockerComputeEngine,
    _container_name,
    _effective_resources,
    _engine_object_store_endpoint,
    reconcile_deployment_containers,
    validate_engine_runtime_readiness,
)
from runtime.engine_credentials import resolve_engine_credentials


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


def _identity(scope: int = enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE) -> compute_pb2.EngineIdentity:
    return compute_pb2.EngineIdentity(
        scope=scope,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        resource_id="analysis-1",
        analysis_id="analysis-1",
    )


def test_engine_credentials_fetch_namespace_scoped_identity_from_backend(monkeypatch) -> None:
    requests: list[tuple[str, str]] = []

    class FakeClient:
        def engine_credentials(self, *, namespace: str, role: str):
            requests.append((namespace, role))
            return worker_runtime_pb2.WorkerEngineCredentialsResponse(
                access_key="ns-reader",
                secret_key="ns-secret",
            )

    monkeypatch.setattr("runtime.engine_credentials.client_from_env", lambda: FakeClient())

    credentials = resolve_engine_credentials("tenant-a", _identity())

    assert requests == [("tenant-a", "reader")]
    assert credentials.access_key == "ns-reader"
    assert credentials.secret_key == "ns-secret"

    resolve_engine_credentials("tenant-b", _identity(enums_pb2.ENGINE_SCOPE_BUILD))
    assert requests[-1] == ("tenant-b", "builder")


def test_unpinned_engine_image_warns_in_prod_but_is_allowed(monkeypatch, caplog) -> None:
    from runtime.docker_engine import _warn_unpinned_engine_image

    monkeypatch.setattr(settings, "prod_mode_enabled", True)
    monkeypatch.setattr(settings, "engine_image", "registry.example/dataforge-engine:latest")

    with caplog.at_level(logging.WARNING):
        _warn_unpinned_engine_image()

    assert "not digest-pinned" in caplog.text

    monkeypatch.setattr(settings, "engine_image", f"registry.example/dataforge-engine@sha256:{'a' * 64}")
    _warn_unpinned_engine_image()
    assert caplog.text.count("not digest-pinned") == 1


def test_container_name_is_dns_safe_and_bounded(monkeypatch) -> None:
    monkeypatch.setattr(settings, "engine_connect_host", "")
    identity = compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        resource_id="4675dc19-dced-4163-b9b2-d168e2cad57d",
        analysis_id="analysis-1",
    )

    name = _container_name(identity=identity, namespace="default")
    second = _container_name(identity=identity, namespace="default")

    # Docker resolves container names as DNS labels: max 63 chars, no "_".
    assert len(name) <= 63
    assert "_" not in name
    assert name != second  # full-identity hash suffix keeps them unique


def test_engine_object_store_endpoint_prefers_private_network_override(monkeypatch) -> None:
    monkeypatch.setattr(settings, "object_store_endpoint", "http://127.0.0.1:9000")
    monkeypatch.setattr(settings, "engine_object_store_endpoint", "http://rustfs:9000")

    assert _engine_object_store_endpoint() == "http://rustfs:9000"


def test_export_submits_object_store_artifact_instead_of_worker_path(monkeypatch, tmp_path: Path) -> None:
    engine = DockerComputeEngine(_identity(), namespace="tenant-a")
    submitted: dict[str, object] = {}
    presigned: dict[str, object] = {}

    def submit(kind: str, payload: dict[str, object], *, job_id: str | None = None) -> str:
        submitted.update({"kind": kind, "payload": payload, "job_id": job_id})
        return job_id or "missing"

    monkeypatch.setattr(engine, "_submit", submit)
    monkeypatch.setattr(
        "runtime.docker_engine.presigned_put_url",
        lambda target_url, **options: presigned.update(target_url=target_url, **options) or "http://object-store/presigned-put",
    )
    monkeypatch.setattr(settings, "engine_connect_host", "127.0.0.1")
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
    monkeypatch.setattr("runtime.docker_engine.docker.DockerClient", lambda **_kwargs: Client())

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
    monkeypatch.setattr("runtime.docker_engine.docker.DockerClient", lambda **_kwargs: Client())

    assert reconcile_deployment_containers(supervisor_id="worker-1", remove_running=False) == 2
    assert removed == ["stopped", "dead"]


def test_intentional_shutdown_is_not_reported_as_container_crash(monkeypatch) -> None:
    engine = DockerComputeEngine(_identity())
    engine._shutdown_requested = True
    monkeypatch.setattr(engine, "is_process_alive", lambda: False)

    result = engine.get_result(job_id="job-1", timeout=0)

    assert result is not None
    assert result.error == "Engine shutdown requested"
    assert result.error_kind == "engine_shutdown"


def test_oom_exit_is_reported_with_container_details() -> None:
    engine = DockerComputeEngine(_identity())

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


def test_job_watch_resumes_clean_stream_close_without_leaking_active_job(monkeypatch) -> None:
    engine = DockerComputeEngine(_identity())
    job_id = "job-resume"
    result = engine_runtime_pb2.EngineJobResult(job_id=job_id, data_json=b'{"rows":[1]}')
    progress = engine_runtime_pb2.EngineJobEvent(job_id=job_id, sequence=1, progress_json=b'{"type":"compute_start"}')
    terminal = engine_runtime_pb2.EngineJobEvent(job_id=job_id, sequence=2, result=result)

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
    engine = DockerComputeEngine(_identity())
    job_id = "job-evicted"
    result = engine_runtime_pb2.EngineJobResult(job_id=job_id, data_json=b'{"rows":[1]}')

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


def test_runtime_readiness_checks_credentials_image_and_network(monkeypatch) -> None:
    calls: list[str] = []

    class Client:
        def close(self) -> None:
            calls.append("close")

    monkeypatch.setattr("runtime.docker_engine._warn_unpinned_engine_image", lambda: calls.append("image-reference"))
    monkeypatch.setattr("runtime.docker_engine._resolve_launch_context", lambda client: calls.append("docker") or (4, "sha256:abc"))
    monkeypatch.setattr("runtime.docker_engine.docker.DockerClient", lambda **_kwargs: Client())

    validate_engine_runtime_readiness()

    assert calls == ["image-reference", "docker", "close"]


def test_container_nano_cpus_skips_hard_quota_for_host_connected_engines(monkeypatch) -> None:
    from runtime.docker_engine import _container_nano_cpus

    monkeypatch.setattr(settings, "engine_connect_host", "127.0.0.1")
    assert _container_nano_cpus(1) is None
    assert _container_nano_cpus(4) is None

    monkeypatch.setattr(settings, "engine_connect_host", "")
    assert _container_nano_cpus(1) == 1_000_000_000
    assert _container_nano_cpus(0) is None


def test_resolve_launch_context_caches_daemon_and_image_lookups(monkeypatch) -> None:
    from runtime import docker_engine

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

    monkeypatch.setattr(settings, "engine_image", "engine:test")
    monkeypatch.setattr(settings, "engine_docker_network", "net-test")
    docker_engine._cached_daemon_cpu_count = None
    docker_engine._validated_image_ref = None
    docker_engine._validated_image_id = None
    docker_engine._validated_network = None

    client = Client()
    first = docker_engine._resolve_launch_context(client)
    second = docker_engine._resolve_launch_context(client)

    assert first == (6, "sha256:abc")
    assert second == first
    assert client.info_calls == 1
    assert client.images.calls == 1
    assert client.networks.calls == 1


def test_engine_credentials_are_cached_per_namespace_and_role(monkeypatch) -> None:
    requests: list[tuple[str, str]] = []

    class FakeClient:
        def engine_credentials(self, *, namespace: str, role: str):
            requests.append((namespace, role))
            return worker_runtime_pb2.WorkerEngineCredentialsResponse(access_key="ns-reader", secret_key="ns-secret")

    monkeypatch.setattr("runtime.engine_credentials.client_from_env", lambda: FakeClient())

    first = resolve_engine_credentials("tenant-a", _identity())
    second = resolve_engine_credentials("tenant-a", _identity())

    assert first == second
    assert requests == [("tenant-a", "reader")]


class _FakeContainer:
    def __init__(self, status: str = "running") -> None:
        self.status = status
        self.reloads = 0

    def reload(self) -> None:
        self.reloads += 1


def test_liveness_probe_is_rate_limited(monkeypatch) -> None:
    engine = DockerComputeEngine(_identity(), namespace="tenant-a")
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
    engine = DockerComputeEngine(_identity(), namespace="tenant-a")
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
    engine = DockerComputeEngine(_identity(), namespace="tenant-a")
    engine._container = _FakeContainer()
    engine._alive = True
    engine._token = "token"
    lock_free_during_rpc = threading.Event()

    class FakeStub:
        def SubmitJob(self, request, timeout=None, metadata=None):  # noqa: N802 - gRPC stub name
            probe = threading.Thread(target=lambda: engine._lock.acquire(timeout=2) and (lock_free_during_rpc.set(), engine._lock.release()))
            probe.start()
            probe.join(timeout=3)
            return engine_runtime_pb2.EngineJobReference(job_id=request.job_id)

    engine._stub = FakeStub()
    monkeypatch.setattr(engine, "_watch_job", lambda job_id: None)

    job_id = engine._submit("preview", {})

    assert job_id
    assert lock_free_during_rpc.is_set()


def test_submit_restarts_an_engine_that_was_shut_down(monkeypatch) -> None:
    """A reaped or crashed engine is restarted by the next job, not reported broken."""
    engine = DockerComputeEngine(_identity(), namespace="tenant-a")
    submitted: list[str] = []

    class FakeStub:
        def SubmitJob(self, request, timeout=None, metadata=None):  # noqa: N802 - gRPC stub name
            submitted.append(request.job_id)
            return engine_runtime_pb2.EngineJobReference(job_id=request.job_id)

    def fake_start() -> None:
        engine._container = _FakeContainer()
        engine._stub = FakeStub()
        engine._alive = True

    monkeypatch.setattr(engine, "start", fake_start)
    monkeypatch.setattr(engine, "_watch_job", lambda job_id: None)

    job_id = engine._submit("preview", {})

    assert submitted == [job_id]
