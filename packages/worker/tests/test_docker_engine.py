from __future__ import annotations

import os
from pathlib import Path

import pytest

from dataforge_protocol import compute_pb2, enums_pb2
from runtime.config import settings
from runtime.docker_engine import (
    DockerComputeEngine,
    _effective_resources,
    _engine_object_store_endpoint,
    _validate_engine_image_reference,
    reconcile_deployment_containers,
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


def test_production_engine_credentials_are_namespace_scoped(monkeypatch) -> None:
    monkeypatch.setattr(settings, "prod_mode_enabled", True)
    monkeypatch.setattr(settings, "object_store_access_key", "platform-key")
    monkeypatch.setattr(settings, "object_store_secret_key", "platform-secret")
    monkeypatch.setattr(
        settings,
        "engine_object_store_credentials_json",
        '{"tenant-a":{"reader":{"access_key":"tenant-reader","secret_key":"tenant-secret"}}}',
    )

    credentials = resolve_engine_credentials("tenant-a", _identity())

    assert credentials.access_key == "tenant-reader"
    assert credentials.secret_key == "tenant-secret"


def test_production_engine_rejects_platform_credentials(monkeypatch) -> None:
    monkeypatch.setattr(settings, "prod_mode_enabled", True)
    monkeypatch.setattr(settings, "object_store_access_key", "platform-key")
    monkeypatch.setattr(settings, "object_store_secret_key", "platform-secret")
    monkeypatch.setattr(
        settings,
        "engine_object_store_credentials_json",
        '{"tenant-a":{"reader":{"access_key":"platform-key","secret_key":"platform-secret"}}}',
    )

    with pytest.raises(RuntimeError, match="must not reuse platform"):
        resolve_engine_credentials("tenant-a", _identity())


def test_production_requires_immutable_engine_digest(monkeypatch) -> None:
    monkeypatch.setattr(settings, "prod_mode_enabled", True)
    monkeypatch.setattr(settings, "engine_image", "registry.example/dataforge-engine:latest")

    with pytest.raises(RuntimeError, match="immutable"):
        _validate_engine_image_reference()

    monkeypatch.setattr(settings, "engine_image", f"registry.example/dataforge-engine@sha256:{'a' * 64}")
    _validate_engine_image_reference()


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
    class Container:
        removed = False

        def remove(self, *, force: bool) -> None:
            assert force
            self.removed = True

    container = Container()

    class Containers:
        def list(self, *, all: bool, filters: dict[str, object]):
            assert all
            assert filters == {"label": ["io.dataforge.managed=true", "io.dataforge.deployment=test-deployment"]}
            return [container]

    class Client:
        containers = Containers()

        def close(self) -> None:
            return None

    monkeypatch.setattr(settings, "deployment_id", "test-deployment")
    monkeypatch.setattr("runtime.docker_engine.docker.DockerClient", lambda **_kwargs: Client())

    assert reconcile_deployment_containers() == 1
    assert container.removed


def test_intentional_shutdown_is_not_reported_as_container_crash(monkeypatch) -> None:
    engine = DockerComputeEngine(_identity())
    engine._shutdown_requested = True
    monkeypatch.setattr(engine, "is_process_alive", lambda: False)

    result = engine.get_result(job_id="job-1", timeout=0)

    assert result is not None
    assert result.error == "Engine shutdown requested"
    assert result.error_kind == "engine_shutdown"


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
