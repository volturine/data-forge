from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

IMAGE = 'postgres:18-alpine'
LABEL = 'data-forge.dev-postgres=1'
STARTUP_TIMEOUT_SECONDS = 30.0
LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}


@dataclass(frozen=True)
class DevPostgres:
    host: str
    port: int
    database: str
    user: str
    password: str

    @property
    def container(self) -> str:
        return f'data-forge-dev-postgres-{self.port}'

    @property
    def volume(self) -> str:
        return f'{self.container}-data'


def parse_database_url(database_url: str) -> DevPostgres:
    parsed = urlparse(database_url)
    if not parsed.scheme.startswith('postgresql'):
        raise ValueError('DATABASE_URL must be a PostgreSQL connection string')
    if parsed.hostname is None:
        raise ValueError('DATABASE_URL must include a hostname')

    database = parsed.path.lstrip('/')
    if not database:
        raise ValueError('DATABASE_URL must include a database name')
    if parsed.username is None:
        raise ValueError('DATABASE_URL must include a username')
    if parsed.password is None:
        raise ValueError('DATABASE_URL must include a password')

    return DevPostgres(
        host=parsed.hostname,
        port=parsed.port or 5432,
        database=database,
        user=unquote(parsed.username),
        password=unquote(parsed.password),
    )



def normalized_database_url(database_url: str) -> str:
    if database_url.startswith('postgresql+psycopg://'):
        return database_url.replace('postgresql+psycopg://', 'postgresql://', 1)
    return database_url



def is_local_host(host: str) -> bool:
    return host in LOCAL_HOSTS



def database_ready(database_url: str, *, timeout: float = 1.0) -> bool:
    import psycopg

    try:
        with psycopg.connect(
            normalized_database_url(database_url),
            autocommit=True,
            connect_timeout=max(1, int(timeout)),
        ) as connection:
            connection.execute('SELECT 1')
        return True
    except psycopg.Error:
        return False



def run_command(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check)



def docker_available(
    run: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> bool:
    try:
        result = run(['docker', 'info'], check=False)
    except FileNotFoundError:
        return False
    return result.returncode == 0



def container_exists(
    cfg: DevPostgres,
    run: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> bool:
    result = run(['docker', 'container', 'inspect', cfg.container], check=False)
    return result.returncode == 0



def container_running(
    cfg: DevPostgres,
    run: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> bool:
    result = run(['docker', 'container', 'inspect', '-f', '{{.State.Running}}', cfg.container], check=False)
    return result.returncode == 0 and result.stdout.strip() == 'true'



def container_state(
    cfg: DevPostgres,
    run: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> str:
    result = run(['docker', 'container', 'inspect', '-f', '{{.State.Status}}', cfg.container], check=False)
    if result.returncode != 0:
        return 'missing'
    return result.stdout.strip()



def container_mounts(
    cfg: DevPostgres,
    run: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> list[str]:
    result = run(['docker', 'container', 'inspect', '-f', '{{range .Mounts}}{{println .Destination}}{{end}}', cfg.container], check=False)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]



def create_container(
    cfg: DevPostgres,
    run: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> None:
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
            f'POSTGRES_DB={cfg.database}',
            '-e',
            f'POSTGRES_USER={cfg.user}',
            '-e',
            f'POSTGRES_PASSWORD={cfg.password}',
            '-p',
            f'127.0.0.1:{cfg.port}:5432',
            '-v',
            f'{cfg.volume}:/var/lib/postgresql',
            IMAGE,
        ]
    )



def start_container(
    cfg: DevPostgres,
    run: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> None:
    run(['docker', 'start', cfg.container])



def remove_container(
    cfg: DevPostgres,
    run: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> None:
    run(['docker', 'rm', '-f', cfg.container], check=False)



def remove_volume(
    cfg: DevPostgres,
    run: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> None:
    run(['docker', 'volume', 'rm', '-f', cfg.volume], check=False)



def recent_logs(
    cfg: DevPostgres,
    run: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> str:
    result = run(['docker', 'logs', '--tail', '50', cfg.container], check=False)
    return '\n'.join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)



def wait_for_database(
    cfg: DevPostgres,
    database_url: str,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = run_command,
    probe: Callable[..., bool] = database_ready,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = STARTUP_TIMEOUT_SECONDS,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = container_state(cfg, run)
        if state in {'exited', 'dead'}:
            raise RuntimeError(f'PostgreSQL container {cfg.container} exited during startup')
        if probe(database_url, timeout=1.0):
            return
        sleep(0.5)
    raise RuntimeError(f'Timed out waiting for PostgreSQL on {cfg.host}:{cfg.port}')



def ensure_local_postgres(
    database_url: str,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = run_command,
    probe: Callable[..., bool] = database_ready,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = STARTUP_TIMEOUT_SECONDS,
) -> None:
    cfg = parse_database_url(database_url)
    if not is_local_host(cfg.host):
        return
    if not docker_available(run):
        raise RuntimeError(
            f'PostgreSQL is not reachable at {cfg.host}:{cfg.port} and Docker is unavailable. '
            'Start PostgreSQL or start the Docker daemon and rerun just dev.'
        )

    if container_exists(cfg, run) and '/var/lib/postgresql/data' in container_mounts(cfg, run):
        print(f'Recreating stale local PostgreSQL container {cfg.container}...', file=sys.stderr)
        remove_container(cfg, run)
        remove_volume(cfg, run)

    if container_exists(cfg, run):
        if not container_running(cfg, run):
            print(f'Starting local PostgreSQL container {cfg.container}...', file=sys.stderr)
            start_container(cfg, run)
    else:
        print(f'Creating local PostgreSQL container {cfg.container}...', file=sys.stderr)
        create_container(cfg, run)

    try:
        wait_for_database(cfg, database_url, run=run, probe=probe, sleep=sleep, timeout=timeout)
    except RuntimeError as exc:
        logs = recent_logs(cfg, run)
        if not logs:
            raise
        raise RuntimeError(f'{exc}\n\nRecent Docker logs for {cfg.container}:\n{logs}') from exc



def main() -> None:
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise SystemExit('DATABASE_URL must be set before running just dev')

    try:
        ensure_local_postgres(database_url)
    except (RuntimeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == '__main__':
    main()
