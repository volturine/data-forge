from __future__ import annotations

import docker
import pytest
import requests

from dataforge_protocol import compute_pb2, enums_pb2
from runtime.compute_worker_credentials import ObjectStoreCredentials
from runtime.config import settings
from runtime.docker_compute_worker import (
    ComputeWorkerStartTimeout,
    DockerComputeWorker,
    docker_host_registry,
    reconcile_deployment_containers,
)
from runtime.docker_hosts import (
    DockerHostConfigError,
    DockerHostRegistry,
    DockerHostSpec,
    NoEligibleDockerHost,
    open_docker_client,
    parse_docker_hosts,
)

_DEFAULTS = {
    "default_docker_host": "unix:///var/run/docker.sock",
    "default_connect_host": "",
    "default_compute_worker_network": "dataforge-compute-worker-runtime",
    "default_object_store_endpoint": "",
}


def _spec(name: str, *, docker_host: str = "tcp://10.0.0.5:2375", connect_host: str = "10.0.0.5", max_workers: int = 0) -> DockerHostSpec:
    return DockerHostSpec(name=name, docker_host=docker_host, connect_host=connect_host, compute_worker_network="net", max_workers=max_workers)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _ProbeClient:
    def __init__(self, *, cpus: int = 4, fail: bool = False) -> None:
        self.cpus = cpus
        self.fail = fail
        self.images = type("Images", (), {"get": staticmethod(lambda _name: type("Image", (), {"id": "sha256:img"})())})()
        self.networks = type("Networks", (), {"get": staticmethod(lambda _name: object())})()

    def ping(self) -> bool:
        if self.fail:
            raise requests.exceptions.ConnectionError("daemon unreachable")
        return True

    def info(self) -> dict[str, object]:
        return {"NCPU": self.cpus}

    def close(self) -> None:
        return None


def _ready(registry: DockerHostRegistry, monkeypatch, *, cpus: dict[str, int] | None = None, failing: set[str] = frozenset()) -> None:
    cpus = cpus or {}
    monkeypatch.setattr(
        "runtime.docker_hosts.open_docker_client",
        lambda spec, **_kwargs: _ProbeClient(cpus=cpus.get(spec.name, 4), fail=spec.name in failing),
    )
    registry.probe_all()


# ---------------------------------------------------------------------------
# Configuration parsing
# ---------------------------------------------------------------------------


def test_empty_host_list_keeps_the_single_legacy_host() -> None:
    hosts = parse_docker_hosts(
        "",
        default_docker_host="unix:///var/run/docker.sock",
        default_connect_host="127.0.0.1",
        default_compute_worker_network="net",
        default_object_store_endpoint="http://rustfs:9000",
    )

    assert hosts == (
        DockerHostSpec(
            name="local",
            docker_host="unix:///var/run/docker.sock",
            connect_host="127.0.0.1",
            compute_worker_network="net",
            object_store_endpoint="http://rustfs:9000",
        ),
    )
    assert hosts[0].is_local
    assert hosts[0].uses_published_ports
    assert not hosts[0].enforces_cpu_quota


def test_host_list_fills_omitted_fields_from_single_host_defaults() -> None:
    raw = """
    [
      {"name": "local", "docker_host": "unix:///var/run/docker.sock"},
      {"name": "node-b", "docker_host": "tcp://10.0.0.5:2376", "connect_host": "10.0.0.5",
       "object_store_endpoint": "http://10.0.0.1:9000", "max_workers": 6, "tls_cert_path": "/certs/node-b"},
      {"name": "node-c", "docker_host": "ssh://dataforge@10.0.0.6", "connect_host": "10.0.0.6"}
    ]
    """

    local, node_b, node_c = parse_docker_hosts(raw, **_DEFAULTS)

    assert local == DockerHostSpec(name="local", docker_host="unix:///var/run/docker.sock", compute_worker_network="dataforge-compute-worker-runtime")
    assert node_b.max_workers == 6
    assert node_b.object_store_endpoint == "http://10.0.0.1:9000"
    assert node_b.tls_cert_path == "/certs/node-b"
    assert node_b.compute_worker_network == "dataforge-compute-worker-runtime"
    assert not node_b.is_local
    assert node_b.enforces_cpu_quota
    assert node_c.uses_published_ports


def test_legacy_host_network_field_is_accepted_with_a_warning(caplog) -> None:
    raw = '[{"name":"local","docker_host":"unix:///var/run/docker.sock","engine_network":"legacy-net"}]'

    with caplog.at_level("WARNING"):
        (host,) = parse_docker_hosts(raw, **_DEFAULTS)

    assert host.compute_worker_network == "legacy-net"
    assert "Deprecated compute-worker host field engine_network" in caplog.text


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("not json", "must be a JSON list"),
        ("[]", "non-empty JSON list"),
        ('[{"docker_host": "tcp://a:2375", "connect_host": "a"}, {"docker_host": "tcp://b:2375", "connect_host": "b"}]', "needs a name"),
        ('[{"name": "Bad Name", "docker_host": "tcp://a:2375", "connect_host": "a"}]', "needs a name"),
        ('[{"name": "a", "docker_host": "tcp://a:2375", "connect_host": "a"}, {"name": "a", "docker_host": "tcp://b:2375", "connect_host": "b"}]', "duplicate"),
        ('[{"name": "a", "docker_host": "ftp://a"}]', "must start with"),
        ('[{"name": "a", "docker_host": "tcp://a:2375"}]', "needs connect_host"),
        ('[{"name": "a", "docker_host": "tcp://a:2375", "connect_host": "a", "max_workers": -1}]', "max_workers"),
        ('[{"name": "a", "docker_host": "tcp://a:2375", "connect_host": "a", "max_workers": true}]', "max_workers"),
        ('[{"name": "a", "docker_host": "unix:///var/run/docker.sock", "tls_cert_path": "/certs"}]', "tls_cert_path"),
    ],
)
def test_invalid_host_lists_are_rejected(raw: str, message: str) -> None:
    with pytest.raises(DockerHostConfigError, match=message):
        parse_docker_hosts(raw, **_DEFAULTS)


def test_open_docker_client_passes_host_specific_transport_options(monkeypatch, tmp_path) -> None:
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(docker, "DockerClient", lambda **kwargs: captured.append(kwargs) or object())

    for name in ("ca.pem", "cert.pem", "key.pem"):
        (tmp_path / name).write_text("placeholder")

    open_docker_client(_spec("plain"))
    open_docker_client(_spec("over-ssh", docker_host="ssh://user@10.0.0.6"))
    open_docker_client(
        DockerHostSpec(name="tls", docker_host="tcp://10.0.0.7:2376", connect_host="10.0.0.7", tls_cert_path=str(tmp_path)),
        timeout=3,
    )

    assert captured[0] == {"base_url": "tcp://10.0.0.5:2375"}
    assert captured[1] == {"base_url": "ssh://user@10.0.0.6", "use_ssh_client": True}
    assert captured[2]["timeout"] == 3
    tls = captured[2]["tls"]
    assert tls.ca_cert == str(tmp_path / "ca.pem")
    assert tls.cert == (str(tmp_path / "cert.pem"), str(tmp_path / "key.pem"))


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------


def test_select_prefers_the_least_loaded_host_per_cpu(monkeypatch) -> None:
    registry = DockerHostRegistry([_spec("small"), _spec("big")], compute_worker_image="compute-worker:test")
    _ready(registry, monkeypatch, cpus={"small": 2, "big": 8})

    # Empty hosts tie on load; configuration order breaks the tie.
    assert registry.select().name == "small"
    registry.record_placement("small", "c1")
    # small: 1/2 = 0.5, big: 0/8 = 0 -> big
    assert registry.select().name == "big"
    registry.record_placement("big", "c2")
    registry.record_placement("big", "c3")
    # small: 0.5, big: 2/8 = 0.25 -> big still has more headroom per CPU
    assert registry.select().name == "big"
    registry.release_placement("small", "c1")
    assert registry.select().name == "small"


def test_select_honours_per_host_max_workers_and_exclusions(monkeypatch) -> None:
    registry = DockerHostRegistry([_spec("a", max_workers=1), _spec("b", max_workers=1)], compute_worker_image="compute-worker:test")
    _ready(registry, monkeypatch)
    registry.record_placement("a", "c1")

    assert registry.select().name == "b"
    with pytest.raises(NoEligibleDockerHost, match="a=full, b=excluded"):
        registry.select(exclude={"b"})
    registry.record_placement("b", "c2")
    with pytest.raises(NoEligibleDockerHost, match="a=full, b=full"):
        registry.select()
    assert registry.placement_capacity() == 2
    # Releasing a placement (idempotent) frees the slot again.
    registry.release_placement("a", "c1")
    registry.release_placement("a", "c1")
    assert registry.select().name == "a"


def test_select_skips_unhealthy_hosts_until_the_cooldown_passes(monkeypatch) -> None:
    clock = _Clock()
    registry = DockerHostRegistry([_spec("a"), _spec("b")], compute_worker_image="compute-worker:test", failure_cooldown_seconds=30, clock=clock)
    _ready(registry, monkeypatch)

    registry.report_failure("a", RuntimeError("boom"))
    assert registry.select().name == "b"
    status = registry.snapshot()[0]
    assert not status.healthy
    assert status.last_error == "RuntimeError: boom"

    # A probe during the cooldown that succeeds restores the host.
    clock.now += 5
    assert registry.probe(registry.get("a"))
    assert registry.select().name == "a"

    # A host that stays broken is never selected, and the error is reported.
    _ready(registry, monkeypatch, failing={"b"})
    clock.now += 100
    assert not registry.probe(registry.get("b"))
    assert [status.healthy for status in registry.snapshot()] == [True, False]
    with pytest.raises(NoEligibleDockerHost, match="a=excluded, b=unhealthy"):
        registry.select(exclude={"a"})


def test_launch_context_does_not_hold_the_registry_lock_during_daemon_calls(monkeypatch) -> None:
    registry = DockerHostRegistry([_spec("a")], compute_worker_image="compute-worker:test")
    seen: list[bool] = []

    class Client(_ProbeClient):
        def info(self) -> dict[str, object]:
            seen.append(registry._lock.locked())
            return super().info()

    cpu_count, image_id = registry.launch_context(registry.get("a"), Client(cpus=3))

    assert (cpu_count, image_id) == (3, "sha256:img")
    assert seen == [False]
    # The second call serves the cached values without touching the daemon.
    registry.launch_context(registry.get("a"), Client(cpus=99))
    assert seen == [False]
    assert registry.launch_context(registry.get("a"), _ProbeClient())[0] == 3


def test_hosts_never_probed_are_not_placement_candidates() -> None:
    registry = DockerHostRegistry([_spec("a")], compute_worker_image="compute-worker:test")

    with pytest.raises(NoEligibleDockerHost):
        registry.select()
    assert registry.placement_capacity() is None


def test_health_monitor_probes_every_host_periodically(monkeypatch) -> None:
    import threading

    probed: list[str] = []
    first_round = threading.Event()
    registry = DockerHostRegistry([_spec("a"), _spec("b")], compute_worker_image="compute-worker:test")

    def probe(spec: DockerHostSpec) -> bool:
        probed.append(spec.name)
        if len(probed) >= 2:
            first_round.set()
        return True

    monkeypatch.setattr(registry, "probe", probe)
    registry.start_health_monitor(0.01)
    try:
        assert first_round.wait(2)
    finally:
        registry.stop_health_monitor()
    assert probed[:2] == ["a", "b"]


# ---------------------------------------------------------------------------
# Launch failover and reconciliation across hosts
# ---------------------------------------------------------------------------


def _identity() -> compute_pb2.ComputeWorkerIdentity:
    return compute_pb2.ComputeWorkerIdentity(
        scope=enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE,
        reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
        resource_id="analysis-1",
        analysis_id="analysis-1",
    )


_TWO_HOSTS = (
    '[{"name": "a", "docker_host": "tcp://10.0.0.5:2375", "connect_host": "10.0.0.5"},'
    ' {"name": "b", "docker_host": "tcp://10.0.0.6:2375", "connect_host": "10.0.0.6"}]'
)


def _prepare_launch(monkeypatch, *, clients: dict[str, object]) -> DockerHostRegistry:
    monkeypatch.setattr(settings, "compute_worker_docker_hosts", _TWO_HOSTS)
    monkeypatch.setattr("runtime.docker_hosts.open_docker_client", lambda _spec, **_kwargs: _ProbeClient())
    registry = docker_host_registry()
    assert all(registry.probe_all().values())
    monkeypatch.setattr("runtime.docker_compute_worker.open_docker_client", lambda spec, **_kwargs: clients[spec.name])
    monkeypatch.setattr("runtime.docker_compute_worker.resolve_compute_worker_credentials", lambda *_args: ObjectStoreCredentials("key", "secret"))
    monkeypatch.setattr("runtime.docker_compute_worker._resolve_launch_context", lambda _host, _client: (1, "image-id"))
    monkeypatch.setattr(
        "runtime.docker_compute_worker._effective_resources",
        lambda *_args, **_kwargs: {"max_threads": 1, "max_memory_mb": 256, "streaming_chunk_size": 0},
    )
    monkeypatch.setattr("runtime.docker_compute_worker._container_rpc_target", lambda _container, host: f"{host.connect_host}:50053")
    monkeypatch.setattr("runtime.docker_compute_worker.grpc.insecure_channel", lambda *_args, **_kwargs: type("Channel", (), {"close": lambda self: None})())
    monkeypatch.setattr("runtime.docker_compute_worker.compute_worker_runtime_pb2_grpc.PolarsComputeWorkerServiceStub", lambda _channel: object())
    return registry


class _Container:
    def __init__(self, container_id: str, events: list[str]) -> None:
        self.id = container_id
        self.events = events

    def start(self) -> None:
        self.events.append(f"start:{self.id}")

    def remove(self, *, force: bool) -> None:
        self.events.append(f"remove:{self.id}")


class _HostClient:
    def __init__(self, name: str, events: list[str], *, create_error: BaseException | None = None) -> None:
        self.name = name
        self.events = events
        self.create_error = create_error
        self.closed = False
        client = self

        class Containers:
            def create(self, **_kwargs):
                client.events.append(f"create:{client.name}")
                if client.create_error is not None:
                    raise client.create_error
                return _Container(f"{client.name}-container", client.events)

        self.containers = Containers()

    def close(self) -> None:
        self.closed = True


def test_engine_launch_fails_over_to_the_next_host_after_a_docker_error(monkeypatch) -> None:
    events: list[str] = []
    broken = _HostClient("a", events, create_error=docker.errors.APIError("daemon exploded"))  # type: ignore[attr-defined]
    healthy = _HostClient("b", events)
    registry = _prepare_launch(monkeypatch, clients={"a": broken, "b": healthy})
    engine = DockerComputeWorker(_identity(), namespace="tenant-a")
    monkeypatch.setattr(engine, "_await_listening", lambda: events.append("listener-ready"))
    monkeypatch.setattr(engine, "_initialize", lambda **_kwargs: events.append("initialize"))
    monkeypatch.setattr(engine, "_heartbeat_loop", lambda: None)

    engine.start()

    assert events == ["create:a", "create:b", "start:b-container", "listener-ready", "initialize"]
    assert engine.docker_host == "b"
    assert engine.container_id == "b-container"
    assert broken.closed
    statuses = {status.name: status for status in registry.snapshot()}
    assert not statuses["a"].healthy
    assert "daemon exploded" in str(statuses["a"].last_error)
    assert statuses["b"].placements == 1
    assert statuses["a"].placements == 0


def test_engine_launch_moves_on_when_the_listener_never_becomes_ready(monkeypatch) -> None:
    events: list[str] = []
    clients = {"a": _HostClient("a", events), "b": _HostClient("b", events)}
    registry = _prepare_launch(monkeypatch, clients=clients)
    engine = DockerComputeWorker()
    attempts = 0

    def await_listening() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ComputeWorkerStartTimeout("Timed out waiting for engine listener", container_status="running")
        events.append("listener-ready")

    monkeypatch.setattr(engine, "_await_listening", await_listening)

    engine.start_warm_worker()

    # The container on the failing host is still running but unreachable, so
    # it is removed, its slot is released, and the warm worker lands on the
    # other host.
    assert events == ["create:a", "start:a-container", "remove:a-container", "create:b", "start:b-container", "listener-ready"]
    assert engine.docker_host == "b"
    statuses = {status.name: status for status in registry.snapshot()}
    assert statuses["a"].placements == 0
    assert statuses["b"].placements == 1
    assert not statuses["a"].healthy


def test_engine_that_exits_during_start_does_not_fail_over_or_exclude_the_host(monkeypatch) -> None:
    events: list[str] = []
    clients = {"a": _HostClient("a", events), "b": _HostClient("b", events)}
    registry = _prepare_launch(monkeypatch, clients=clients)
    engine = DockerComputeWorker(_identity(), namespace="tenant-a")

    def await_listening() -> None:
        raise ComputeWorkerStartTimeout("Timed out waiting for engine listener; container status=exited", container_status="exited")

    monkeypatch.setattr(engine, "_await_listening", await_listening)

    with pytest.raises(ComputeWorkerStartTimeout, match="status=exited"):
        engine.start()

    # The crash is the engine's, not the host's: no second host is tried, the
    # host stays eligible, and the removed container no longer holds a slot.
    assert events == ["create:a", "start:a-container", "remove:a-container"]
    statuses = {status.name: status for status in registry.snapshot()}
    assert statuses["a"].healthy and statuses["b"].healthy
    assert statuses["a"].placements == 0
    assert engine.container_id is None


def test_placement_slot_is_released_only_when_the_container_is_gone(monkeypatch) -> None:
    import docker.errors

    registry = _prepare_launch(monkeypatch, clients={})
    engine = DockerComputeWorker()

    class Client:
        def close(self) -> None:
            return None

    class Container:
        def __init__(self, error: BaseException | None = None) -> None:
            self.error = error

        def remove(self, *, force: bool) -> None:
            if self.error is not None:
                raise self.error

    def place(container_id: str) -> None:
        engine._host = registry.get("a")
        engine._container_id = container_id
        registry.record_placement("a", container_id)

    # Detaching (fenced-out coordinator, failed removal) keeps the slot.
    place("c-detached")
    engine._detach_local_handles()
    assert registry.snapshot()[0].placements == 1

    # A removal that fails for any reason other than "already gone" keeps it too.
    place("c-stuck")
    engine._cleanup_failed_start(Container(error=RuntimeError("daemon busy")), Client())
    assert registry.snapshot()[0].placements == 2

    # A successful removal, or a container Docker no longer knows, frees it.
    place("c-removed")
    engine._cleanup_failed_start(Container(), Client())
    place("c-missing")
    engine._cleanup_failed_start(Container(error=docker.errors.NotFound("gone")), Client())
    assert registry.snapshot()[0].placements == 2
    assert {status.name: status.placements for status in registry.snapshot()}["a"] == 2
    registry.release_placement("a", "c-detached")
    registry.release_placement("a", "c-stuck")
    assert registry.snapshot()[0].placements == 0


def test_engine_launch_reports_every_host_when_all_fail(monkeypatch) -> None:
    events: list[str] = []
    clients = {
        "a": _HostClient("a", events, create_error=requests.exceptions.ConnectionError("a is down")),
        "b": _HostClient("b", events, create_error=OSError("b is down")),
    }
    registry = _prepare_launch(monkeypatch, clients=clients)
    engine = DockerComputeWorker(_identity(), namespace="tenant-a")

    with pytest.raises(RuntimeError, match="every eligible Docker host") as excinfo:
        engine.start()

    assert events == ["create:a", "create:b"]
    assert isinstance(excinfo.value.__cause__, OSError)
    assert all(not status.healthy for status in registry.snapshot())
    assert engine.docker_host is None
    assert engine.container_id is None


def test_reconciliation_frees_the_slot_of_a_detached_container(monkeypatch) -> None:
    import docker.errors

    registry = _prepare_launch(monkeypatch, clients={})
    monkeypatch.setattr(settings, "deployment_id", "test-deployment")
    engine = DockerComputeWorker()
    engine._host = registry.get("a")
    engine._container_id = "a-detached"
    registry.record_placement("a", "a-detached")
    registry.record_placement("a", "a-already-gone")
    registry.record_placement("a", "a-stuck")
    # The engine let go of its handles but the container kept running.
    engine._detach_local_handles()
    assert registry.snapshot()[0].placements == 3

    class Api:
        def containers(self, *, all: bool, filters: dict[str, object]):
            return [
                {"Id": "a-detached", "State": "running"},
                {"Id": "a-already-gone", "State": "exited"},
                {"Id": "a-stuck", "State": "exited"},
            ]

        def remove_container(self, container_id: str, *, force: bool) -> None:
            if container_id == "a-already-gone":
                raise docker.errors.NotFound("gone")
            if container_id == "a-stuck":
                raise RuntimeError("daemon busy")

    class Client:
        api = Api()

        def close(self) -> None:
            return None

    def open_client(spec: DockerHostSpec, **_kwargs):
        return Client() if spec.name == "a" else _HostClient("b", [])

    monkeypatch.setattr("runtime.docker_compute_worker.open_docker_client", open_client)
    monkeypatch.setattr(_HostClient, "api", property(lambda self: type("Api", (), {"containers": lambda *_a, **_k: []})()), raising=False)

    # Removed and already-absent containers give their slots back; the one
    # the daemon would not remove keeps its slot until a later sweep.
    assert reconcile_deployment_containers() == 2
    assert {status.name: status.placements for status in registry.snapshot()} == {"a": 1, "b": 0}


def test_reconciliation_sweeps_every_host_and_skips_unreachable_ones(monkeypatch) -> None:
    removed: list[str] = []
    monkeypatch.setattr(settings, "compute_worker_docker_hosts", _TWO_HOSTS)
    monkeypatch.setattr(settings, "deployment_id", "test-deployment")

    class Api:
        def __init__(self, name: str) -> None:
            self.name = name

        def containers(self, *, all: bool, filters: dict[str, object]):
            assert all and filters == {"label": ["io.dataforge.managed=true", "io.dataforge.deployment=test-deployment"]}
            return [{"Id": f"{self.name}-stopped", "State": "exited"}]

        def remove_container(self, container_id: str, *, force: bool) -> None:
            assert force
            removed.append(container_id)

    class Client:
        def __init__(self, name: str) -> None:
            self.api = Api(name)

        def close(self) -> None:
            return None

    def open_client(spec: DockerHostSpec, **_kwargs):
        if spec.name == "b":
            raise requests.exceptions.ConnectionError("b is down")
        return Client(spec.name)

    monkeypatch.setattr("runtime.docker_compute_worker.open_docker_client", open_client)

    assert reconcile_deployment_containers() == 1
    assert removed == ["a-stopped"]
    statuses = {status.name: status for status in docker_host_registry().snapshot()}
    assert "b is down" in str(statuses["b"].last_error)
