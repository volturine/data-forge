from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import urlopen

IMAGE = 'rustfs/rustfs:latest'
LABEL = 'data-forge.dev-rustfs=1'
STARTUP_TIMEOUT_SECONDS = 30.0
LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}
WEB_UI_PORT = 9001


@dataclass(frozen=True)
class DevRustfs:
    host: str
    port: int
    access_key: str
    secret_key: str

    @property
    def container(self) -> str:
        return f'data-forge-dev-rustfs-{self.port}'

    @property
    def volume(self) -> str:
        return f'{self.container}-data'


@dataclass(frozen=True)
class DevRustfsTarget:
    host: str
    port: int

    @property
    def container(self) -> str:
        return f'data-forge-dev-rustfs-{self.port}'

    @property
    def volume(self) -> str:
        return f'{self.container}-data'


def parse_endpoint(endpoint: str) -> DevRustfsTarget:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {'http', 'https'}:
        raise ValueError('OBJECT_STORE_ENDPOINT must be an http(s) URL')
    if parsed.hostname is None:
        raise ValueError('OBJECT_STORE_ENDPOINT must include a hostname')
    return DevRustfsTarget(host=parsed.hostname, port=parsed.port or 9000)


def parse_config(endpoint: str, access_key: str, secret_key: str) -> DevRustfs:
    target = parse_endpoint(endpoint)
    if not access_key:
        raise ValueError('OBJECT_STORE_ACCESS_KEY must be set before running just dev')
    if not secret_key:
        raise ValueError('OBJECT_STORE_SECRET_KEY must be set before running just dev')
    return DevRustfs(
        host=target.host,
        port=target.port,
        access_key=access_key,
        secret_key=secret_key,
    )


def is_local_host(host: str) -> bool:
    return host in LOCAL_HOSTS


def endpoint_ready(endpoint: str, *, timeout: float = 1.0) -> bool:
    try:
        with urlopen(endpoint, timeout=timeout):
            return True
    except HTTPError:
        return True
    except (URLError, OSError):
        return False


def run_command(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check)


def docker_available(run: Callable[..., subprocess.CompletedProcess[str]] = run_command) -> bool:
    try:
        result = run(['docker', 'info'], check=False)
    except FileNotFoundError:
        return False
    return result.returncode == 0


def container_exists(cfg: DevRustfsTarget, run: Callable[..., subprocess.CompletedProcess[str]] = run_command) -> bool:
    result = run(['docker', 'container', 'inspect', cfg.container], check=False)
    return result.returncode == 0


def container_running(cfg: DevRustfsTarget, run: Callable[..., subprocess.CompletedProcess[str]] = run_command) -> bool:
    result = run(['docker', 'container', 'inspect', '-f', '{{.State.Running}}', cfg.container], check=False)
    return result.returncode == 0 and result.stdout.strip() == 'true'


def container_state(cfg: DevRustfsTarget, run: Callable[..., subprocess.CompletedProcess[str]] = run_command) -> str:
    result = run(['docker', 'container', 'inspect', '-f', '{{.State.Status}}', cfg.container], check=False)
    if result.returncode != 0:
        return 'missing'
    return result.stdout.strip()


def container_mounts(cfg: DevRustfsTarget, run: Callable[..., subprocess.CompletedProcess[str]] = run_command) -> list[str]:
    result = run(['docker', 'container', 'inspect', '-f', '{{range .Mounts}}{{println .Destination}}{{end}}', cfg.container], check=False)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def container_exposes_web_ui(cfg: DevRustfsTarget, run: Callable[..., subprocess.CompletedProcess[str]] = run_command) -> bool:
    result = run(['docker', 'port', cfg.container, '9001/tcp'], check=False)
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def create_container(cfg: DevRustfs, run: Callable[..., subprocess.CompletedProcess[str]] = run_command) -> None:
    run(['docker', 'volume', 'create', '--label', LABEL, cfg.volume])
    run(
        [
            'docker',
            'run',
            '-d',
            '--name',
            cfg.container,
            '--label',
            LABEL,
            '-e',
            f'RUSTFS_ACCESS_KEY={cfg.access_key}',
            '-e',
            f'RUSTFS_SECRET_KEY={cfg.secret_key}',
            '-p',
            f'127.0.0.1:{cfg.port}:9000',
            '-p',
            f'127.0.0.1:{WEB_UI_PORT}:9001',
            '-v',
            f'{cfg.volume}:/data',
            IMAGE,
            '/data',
        ]
    )


def start_container(cfg: DevRustfsTarget, run: Callable[..., subprocess.CompletedProcess[str]] = run_command) -> None:
    run(['docker', 'start', cfg.container])


def remove_container(cfg: DevRustfsTarget, run: Callable[..., subprocess.CompletedProcess[str]] = run_command) -> None:
    run(['docker', 'rm', '-f', cfg.container], check=False)


def remove_volume(cfg: DevRustfsTarget, run: Callable[..., subprocess.CompletedProcess[str]] = run_command) -> None:
    run(['docker', 'volume', 'rm', '-f', cfg.volume], check=False)


def recent_logs(cfg: DevRustfsTarget, run: Callable[..., subprocess.CompletedProcess[str]] = run_command) -> str:
    result = run(['docker', 'logs', '--tail', '50', cfg.container], check=False)
    return '\n'.join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)


def wait_for_rustfs(
    cfg: DevRustfsTarget,
    endpoint: str,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = run_command,
    probe: Callable[..., bool] = endpoint_ready,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = STARTUP_TIMEOUT_SECONDS,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = container_state(cfg, run)
        if state in {'exited', 'dead'}:
            raise RuntimeError(f'RustFS container {cfg.container} exited during startup')
        if probe(endpoint, timeout=1.0):
            return
        sleep(0.5)
    raise RuntimeError(f'Timed out waiting for RustFS on {cfg.host}:{cfg.port}')


def ensure_local_rustfs(
    endpoint: str,
    access_key: str,
    secret_key: str,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = run_command,
    probe: Callable[..., bool] = endpoint_ready,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = STARTUP_TIMEOUT_SECONDS,
) -> None:
    cfg = parse_config(endpoint, access_key, secret_key)
    if not is_local_host(cfg.host):
        return
    if not docker_available(run):
        raise RuntimeError(
            f'RustFS is not reachable at {cfg.host}:{cfg.port} and Docker is unavailable. '
            'Start RustFS or start the Docker daemon and rerun just dev.'
        )

    if container_exists(cfg, run):
        mounts = container_mounts(cfg, run)
        has_data_mount = '/data' in mounts
        has_web_ui = container_exposes_web_ui(cfg, run)
        if not has_data_mount or not has_web_ui:
            print(f'Recreating stale local RustFS container {cfg.container}...', file=sys.stderr)
            remove_container(cfg, run)
            remove_volume(cfg, run)

    if container_exists(cfg, run):
        if not container_running(cfg, run):
            print(f'Starting local RustFS container {cfg.container}...', file=sys.stderr)
            start_container(cfg, run)
    else:
        print(f'Creating local RustFS container {cfg.container}...', file=sys.stderr)
        create_container(cfg, run)

    try:
        wait_for_rustfs(cfg, endpoint, run=run, probe=probe, sleep=sleep, timeout=timeout)
    except RuntimeError as exc:
        logs = recent_logs(cfg, run)
        if not logs:
            raise
        raise RuntimeError(f'{exc}\n\nRecent Docker logs for {cfg.container}:\n{logs}') from exc


def remove_local_rustfs(endpoint: str, *, run: Callable[..., subprocess.CompletedProcess[str]] = run_command) -> None:
    cfg = parse_endpoint(endpoint)
    if not is_local_host(cfg.host):
        return
    remove_container(cfg, run)
    remove_volume(cfg, run)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--remove', action='store_true')
    args = parser.parse_args()

    endpoint = os.environ.get('OBJECT_STORE_ENDPOINT')
    if not endpoint:
        raise SystemExit('OBJECT_STORE_ENDPOINT must be set before running just dev')

    try:
        if args.remove:
            remove_local_rustfs(endpoint)
            return
        ensure_local_rustfs(
            endpoint,
            os.environ.get('OBJECT_STORE_ACCESS_KEY', ''),
            os.environ.get('OBJECT_STORE_SECRET_KEY', ''),
        )
    except (RuntimeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == '__main__':
    main()
