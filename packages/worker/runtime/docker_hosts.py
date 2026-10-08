"""Docker host registry for compute containers.

One worker manager can place compute containers on several Docker daemons
(local sockets, ``tcp://`` or ``ssh://`` endpoints on other machines). The
registry owns the configured host specs, their health, their launch context
(image id, network, CPU count) and the least-loaded placement decision. The
Docker API calls themselves stay in :mod:`runtime.docker_compute_worker`.

Placement is *least loaded*: among healthy hosts with free capacity, the host
whose placed-container count per daemon CPU is lowest wins; ties go to the
host with fewer placements, then to configuration order. A host that fails a
probe or a launch is excluded for a cooldown period and re-probed by the
background health monitor; launches fail over to the next eligible host.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import docker

logger = logging.getLogger(__name__)

_HOST_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")
_LOCAL_SCHEMES = ("unix://", "npipe://", "http+unix://")
_SUPPORTED_SCHEMES = (*_LOCAL_SCHEMES, "tcp://", "ssh://", "http://", "https://")
DEFAULT_HOST_NAME = "local"
# A host that fails is kept out of placement for this long, then re-probed.
HOST_FAILURE_COOLDOWN_SECONDS = 30.0
# Docker API round trips for probes are short; a daemon that cannot answer a
# ping within this budget is not a placement candidate.
HOST_PROBE_TIMEOUT_SECONDS = 5


class DockerHostConfigError(ValueError):
    """``ENGINE_DOCKER_HOSTS`` is malformed or inconsistent."""


class NoEligibleDockerHost(RuntimeError):
    """No healthy Docker host with free capacity is available for a launch."""


@dataclass(frozen=True, slots=True)
class DockerHostSpec:
    name: str
    docker_host: str
    # Address the worker dials for engine RPC ports published on this host.
    # Empty means Docker DNS on ``engine_network``, which only works for a
    # daemon the worker container itself is attached to.
    connect_host: str = ""
    engine_network: str = ""
    # Object store endpoint handed to engines on this host. Empty falls back
    # to the worker's own endpoint.
    object_store_endpoint: str = ""
    # Hard cap of compute containers placed on this host; 0 = bounded only by
    # COMPUTE_WORKERS.
    max_workers: int = 0
    # Directory holding ca.pem, cert.pem and key.pem for a TLS tcp:// daemon.
    tls_cert_path: str = ""

    @property
    def is_local(self) -> bool:
        return self.docker_host.startswith(_LOCAL_SCHEMES)

    @property
    def uses_published_ports(self) -> bool:
        return bool(self.connect_host)

    @property
    def enforces_cpu_quota(self) -> bool:
        """Hard CPU quotas apply everywhere except host-connected local runs.

        A local daemon with a published connect host is the dev/E2E shape that
        shares cores with the API, worker and browsers; a remote machine is a
        dedicated compute host and keeps the production quota.
        """
        return not (self.is_local and self.uses_published_ports)


@dataclass(slots=True)
class DockerHostStatus:
    name: str
    healthy: bool
    placements: int
    cpu_count: int | None
    max_workers: int
    last_error: str | None
    checked_at: float | None


@dataclass(slots=True)
class _HostState:
    spec: DockerHostSpec
    order: int
    healthy: bool = False
    unavailable_until: float = 0.0
    last_error: str | None = None
    checked_at: float | None = None
    cpu_count: int | None = None
    image_id: str | None = None
    image_ref: str | None = None
    placements: set[str] = field(default_factory=set)


def _read_str(entry: dict[str, Any], key: str, *, default: str = "") -> str:
    value = entry.get(key, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise DockerHostConfigError(f"ENGINE_DOCKER_HOSTS entry field {key!r} must be a string")
    return value.strip()


def parse_docker_hosts(
    raw: str,
    *,
    default_docker_host: str,
    default_connect_host: str,
    default_engine_network: str,
    default_object_store_endpoint: str,
) -> tuple[DockerHostSpec, ...]:
    """Parse ``ENGINE_DOCKER_HOSTS``; an empty value yields the single legacy host.

    The single-host variables (``ENGINE_DOCKER_HOST``, ``ENGINE_CONNECT_HOST``,
    ``ENGINE_DOCKER_NETWORK``, ``ENGINE_OBJECT_STORE_ENDPOINT``) remain the
    defaults for every entry that omits the field, so an existing deployment
    keeps working without the list.
    """
    text = raw.strip()
    if not text:
        return (
            DockerHostSpec(
                name=DEFAULT_HOST_NAME,
                docker_host=default_docker_host,
                connect_host=default_connect_host,
                engine_network=default_engine_network,
                object_store_endpoint=default_object_store_endpoint,
            ),
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DockerHostConfigError(f"ENGINE_DOCKER_HOSTS must be a JSON list: {exc}") from exc
    if not isinstance(payload, list) or not payload:
        raise DockerHostConfigError("ENGINE_DOCKER_HOSTS must be a non-empty JSON list of host objects")
    specs: list[DockerHostSpec] = []
    seen: set[str] = set()
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise DockerHostConfigError(f"ENGINE_DOCKER_HOSTS[{index}] must be an object")
        name = _read_str(entry, "name", default=DEFAULT_HOST_NAME if len(payload) == 1 else "")
        if not _HOST_NAME_RE.fullmatch(name):
            raise DockerHostConfigError(f"ENGINE_DOCKER_HOSTS[{index}] needs a name matching {_HOST_NAME_RE.pattern}")
        if name in seen:
            raise DockerHostConfigError(f"ENGINE_DOCKER_HOSTS has duplicate host name {name!r}")
        seen.add(name)
        docker_host = _read_str(entry, "docker_host") or default_docker_host
        if not docker_host.startswith(_SUPPORTED_SCHEMES):
            raise DockerHostConfigError(f"ENGINE_DOCKER_HOSTS[{name}] docker_host must start with one of {', '.join(_SUPPORTED_SCHEMES)}")
        max_workers_raw = entry.get("max_workers", 0)
        if isinstance(max_workers_raw, bool) or not isinstance(max_workers_raw, int) or max_workers_raw < 0:
            raise DockerHostConfigError(f"ENGINE_DOCKER_HOSTS[{name}] max_workers must be a non-negative integer")
        spec = DockerHostSpec(
            name=name,
            docker_host=docker_host,
            connect_host=_read_str(entry, "connect_host", default=default_connect_host),
            engine_network=_read_str(entry, "engine_network") or default_engine_network,
            object_store_endpoint=_read_str(entry, "object_store_endpoint") or default_object_store_endpoint,
            max_workers=max_workers_raw,
            tls_cert_path=_read_str(entry, "tls_cert_path"),
        )
        if not spec.is_local and not spec.connect_host:
            raise DockerHostConfigError(
                f"ENGINE_DOCKER_HOSTS[{name}] is a remote daemon and needs connect_host: engines there publish their RPC port and the worker dials that address"
            )
        if spec.tls_cert_path and not spec.docker_host.startswith(("tcp://", "https://")):
            raise DockerHostConfigError(f"ENGINE_DOCKER_HOSTS[{name}] tls_cert_path only applies to tcp:// daemons")
        specs.append(spec)
    return tuple(specs)


def open_docker_client(spec: DockerHostSpec, *, timeout: int | None = None) -> Any:
    """Open a docker-py client for one host; callers close it."""
    kwargs: dict[str, Any] = {"base_url": spec.docker_host}
    if timeout is not None:
        kwargs["timeout"] = timeout
    if spec.docker_host.startswith("ssh://"):
        # The ssh binary handles keys, agents and known hosts; paramiko is not
        # a dependency of the worker image.
        kwargs["use_ssh_client"] = True
    if spec.tls_cert_path:
        cert_dir = Path(spec.tls_cert_path)
        kwargs["tls"] = docker.tls.TLSConfig(  # type: ignore[attr-defined]  # docker-py has no Python 3.14 stubs.
            client_cert=(str(cert_dir / "cert.pem"), str(cert_dir / "key.pem")),
            ca_cert=str(cert_dir / "ca.pem"),
            verify=True,
        )
    return docker.DockerClient(**kwargs)  # type: ignore[attr-defined]


class DockerHostRegistry:
    """Health, launch context and placement for the configured Docker hosts."""

    def __init__(
        self,
        hosts: Iterable[DockerHostSpec],
        *,
        engine_image: str,
        failure_cooldown_seconds: float = HOST_FAILURE_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        specs = tuple(hosts)
        if not specs:
            raise DockerHostConfigError("At least one Docker host is required")
        self._states: dict[str, _HostState] = {spec.name: _HostState(spec=spec, order=index) for index, spec in enumerate(specs)}
        self._engine_image = engine_image
        self._failure_cooldown_seconds = failure_cooldown_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None

    @property
    def hosts(self) -> tuple[DockerHostSpec, ...]:
        return tuple(state.spec for state in sorted(self._states.values(), key=lambda state: state.order))

    def get(self, name: str) -> DockerHostSpec:
        return self._states[name].spec

    # -- health -----------------------------------------------------------

    def launch_context(self, spec: DockerHostSpec, client: Any) -> tuple[int | None, str]:
        """Return ``(daemon_cpu_count, image_id)`` for a host, cached per host.

        Image and network are immutable for a worker process, so one lookup
        per host serves every launch there. A changed ``engine_image`` setting
        (tests) invalidates the cached image id.
        """
        state = self._states[spec.name]
        with self._lock:
            if state.cpu_count is None:
                ncpu = client.info().get("NCPU")
                state.cpu_count = ncpu if isinstance(ncpu, int) and ncpu > 0 else 0
            if state.image_ref != self._engine_image or not state.image_id:
                image = client.images.get(self._engine_image)
                state.image_ref = self._engine_image
                state.image_id = str(image.id)
            client.networks.get(spec.engine_network)
            cpu_count = state.cpu_count if state.cpu_count else None
            assert state.image_id is not None
            return cpu_count, state.image_id

    def probe(self, spec: DockerHostSpec) -> bool:
        """Ping one daemon and validate its launch context; record the outcome."""
        state = self._states[spec.name]
        was_healthy = state.healthy
        try:
            client = open_docker_client(spec, timeout=HOST_PROBE_TIMEOUT_SECONDS)
            try:
                client.ping()
                self.launch_context(spec, client)
            finally:
                client.close()
        except Exception as exc:
            with self._lock:
                state.healthy = False
                state.last_error = f"{type(exc).__name__}: {exc}"
                state.checked_at = self._clock()
                state.unavailable_until = self._clock() + self._failure_cooldown_seconds
            if was_healthy:
                logger.error("Docker host unavailable name=%s docker_host=%s error=%s", spec.name, spec.docker_host, state.last_error)
            else:
                logger.warning("Docker host probe failed name=%s docker_host=%s error=%s", spec.name, spec.docker_host, state.last_error)
            return False
        with self._lock:
            state.healthy = True
            state.last_error = None
            state.checked_at = self._clock()
            state.unavailable_until = 0.0
            cpu_count = state.cpu_count
        if not was_healthy:
            logger.info("Docker host ready name=%s docker_host=%s cpus=%s max_workers=%s", spec.name, spec.docker_host, cpu_count, spec.max_workers)
        return True

    def probe_all(self) -> dict[str, bool]:
        return {spec.name: self.probe(spec) for spec in self.hosts}

    def report_failure(self, name: str, error: BaseException) -> None:
        """Take a host out of placement after a launch or API failure on it."""
        state = self._states[name]
        with self._lock:
            state.healthy = False
            state.last_error = f"{type(error).__name__}: {error}"
            state.checked_at = self._clock()
            state.unavailable_until = self._clock() + self._failure_cooldown_seconds
        logger.error("Docker host failed, excluding it from placement name=%s error=%s", name, state.last_error)

    def start_health_monitor(self, interval_seconds: float) -> None:
        if self._monitor_thread is not None:
            return
        self._monitor_stop.clear()

        def run() -> None:
            while not self._monitor_stop.wait(interval_seconds):
                for spec in self.hosts:
                    if self._monitor_stop.is_set():
                        return
                    self.probe(spec)

        self._monitor_thread = threading.Thread(target=run, name="docker-host-health", daemon=True)
        self._monitor_thread.start()

    def stop_health_monitor(self) -> None:
        self._monitor_stop.set()
        thread = self._monitor_thread
        self._monitor_thread = None
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    # -- placement --------------------------------------------------------

    def record_placement(self, name: str, container_id: str) -> None:
        with self._lock:
            self._states[name].placements.add(container_id)

    def release_placement(self, name: str, container_id: str) -> None:
        with self._lock:
            self._states[name].placements.discard(container_id)

    def _eligible_locked(self, state: _HostState, now: float, exclude: Iterable[str]) -> bool:
        if state.spec.name in exclude:
            return False
        if not state.healthy or now < state.unavailable_until:
            return False
        return not (state.spec.max_workers and len(state.placements) >= state.spec.max_workers)

    def select(self, *, exclude: Iterable[str] = ()) -> DockerHostSpec:
        """Pick the least-loaded eligible host or raise :class:`NoEligibleDockerHost`."""
        excluded = set(exclude)
        now = self._clock()
        with self._lock:
            candidates = [state for state in self._states.values() if self._eligible_locked(state, now, excluded)]
            if not candidates:
                raise NoEligibleDockerHost(f"No Docker host can accept a compute container ({self._describe_ineligible_locked(now, excluded)})")

            def score(state: _HostState) -> tuple[float, int, int]:
                placements = len(state.placements)
                return (placements / max(state.cpu_count or 1, 1), placements, state.order)

            return min(candidates, key=score).spec

    def _describe_ineligible_locked(self, now: float, excluded: set[str]) -> str:
        parts: list[str] = []
        for state in sorted(self._states.values(), key=lambda state: state.order):
            if state.spec.name in excluded:
                reason = "excluded"
            elif not state.healthy or now < state.unavailable_until:
                reason = "unhealthy"
            else:
                reason = "full"
            parts.append(f"{state.spec.name}={reason}")
        return ", ".join(parts)

    def snapshot(self) -> list[DockerHostStatus]:
        now = self._clock()
        with self._lock:
            return [
                DockerHostStatus(
                    name=state.spec.name,
                    healthy=state.healthy and now >= state.unavailable_until,
                    placements=len(state.placements),
                    cpu_count=state.cpu_count,
                    max_workers=state.spec.max_workers,
                    last_error=state.last_error,
                    checked_at=state.checked_at,
                )
                for state in sorted(self._states.values(), key=lambda state: state.order)
            ]

    def placement_capacity(self) -> int | None:
        """Sum of per-host caps, or ``None`` when any host is uncapped."""
        total = 0
        for spec in self.hosts:
            if spec.max_workers == 0:
                return None
            total += spec.max_workers
        return total
