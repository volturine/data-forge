from __future__ import annotations

import contextlib
import os
import signal
import socket
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import psycopg

REPO_ROOT = Path(__file__).resolve().parents[4]
CORE_ROOT = REPO_ROOT / 'packages' / 'shared'
BACKEND_ROOT = REPO_ROOT / 'packages' / 'backend'
SCHEDULER_ROOT = REPO_ROOT / 'packages' / 'scheduler'
WORKER_ROOT = REPO_ROOT / 'packages' / 'worker-manager'


def docker_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env['PYTHONPATH'] = f'{BACKEND_ROOT}{os.pathsep}{SCHEDULER_ROOT}{os.pathsep}{WORKER_ROOT}{os.pathsep}{CORE_ROOT}'
    if extra is not None:
        env.update(extra)
    return env


def docker_available() -> bool:
    try:
        result = subprocess.run(
            ['docker', 'info'], cwd=REPO_ROOT, env=docker_env(), text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


def require_docker() -> None:
    import pytest

    if docker_available():
        return
    pytest.skip('Docker daemon is required for Postgres integration tests')


def run_command(
    command: list[str], *, cwd: Path = REPO_ROOT, env: dict[str, str] | None = None, timeout: float = 120, check: bool = True
) -> subprocess.CompletedProcess[str]:
    merged_env = env if env is not None else os.environ.copy()
    return subprocess.run(command, cwd=cwd, env=merged_env, text=True, capture_output=True, timeout=timeout, check=check)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        sock.listen()
        return int(sock.getsockname()[1])


def wait_for_http_ready(url: str, *, timeout: float = 90) -> None:
    deadline = time.time() + timeout
    last_error = ''
    while time.time() < deadline:
        try:
            response = httpx.get(url, timeout=5)
            if response.status_code == 200:
                return
            last_error = f'HTTP {response.status_code}: {response.text}'
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(1)
    raise AssertionError(f'Timed out waiting for {url}: {last_error}')


def wait_for_condition(predicate, *, timeout: float = 60, interval: float = 0.5, description: str):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError(f'Timed out waiting for {description}')


def _drain_stream(stream, chunks: list[str]) -> None:
    if stream is None:
        return
    for line in stream:
        chunks.append(line)


@dataclass
class ManagedProcess:
    name: str
    command: list[str]
    cwd: Path
    env: dict[str, str]
    proc: subprocess.Popen[str] | None = None
    stdout_chunks: list[str] = field(default_factory=list)
    stderr_chunks: list[str] = field(default_factory=list)
    threads: list[threading.Thread] = field(default_factory=list)

    def start(self) -> None:
        self.proc = subprocess.Popen(
            self.command, cwd=self.cwd, env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
        )
        for stream, chunks in ((self.proc.stdout, self.stdout_chunks), (self.proc.stderr, self.stderr_chunks)):
            thread = threading.Thread(target=_drain_stream, args=(stream, chunks), daemon=True)
            thread.start()
            self.threads.append(thread)

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            self._join_threads()
            return
        with contextlib.suppress(ProcessLookupError):
            os.killpg(self.proc.pid, signal.SIGTERM)
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.proc.pid, signal.SIGKILL)
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.proc.wait(timeout=5)
        self._join_threads()

    def tail(self, *, limit: int = 80) -> str:
        lines = [*self.stdout_chunks, *self.stderr_chunks]
        return ''.join(lines[-limit:])

    def _join_threads(self) -> None:
        for thread in self.threads:
            thread.join(timeout=1)


@dataclass
class ExternalPostgres:
    url: str

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.url.replace('+psycopg', ''), autocommit=True)


@dataclass
class PostgresContainer:
    user: str = 'dataforge'
    password: str = 'dataforge'
    database: str = 'dataforge'
    image: str = 'postgres:18-alpine'
    name: str = field(default_factory=lambda: f'df-pg-{uuid.uuid4().hex[:10]}')
    container_id: str | None = None
    port: int | None = None

    @property
    def url(self) -> str:
        assert self.port is not None
        return f'postgresql+psycopg://{self.user}:{self.password}@127.0.0.1:{self.port}/{self.database}'

    def start(self) -> None:
        result = run_command(
            [
                'docker',
                'run',
                '-d',
                '--rm',
                '--name',
                self.name,
                '-e',
                f'POSTGRES_DB={self.database}',
                '-e',
                f'POSTGRES_USER={self.user}',
                '-e',
                f'POSTGRES_PASSWORD={self.password}',
                '-p',
                '127.0.0.1::5432',
                self.image,
            ],
            env=docker_env(),
            timeout=300,
        )
        self.container_id = result.stdout.strip()
        self.port = self._wait_for_port_mapping()
        self.wait_ready()

    def _wait_for_port_mapping(self, *, timeout: float = 30) -> int:
        deadline = time.time() + timeout
        last_error = ''
        while time.time() < deadline:
            result = run_command(['docker', 'port', self.name, '5432/tcp'], env=docker_env(), check=False)
            output = result.stdout.strip()
            if result.returncode == 0 and output:
                return int(output.rsplit(':', 1)[-1])
            last_error = result.stderr.strip() or output or f'exit code {result.returncode}'
            time.sleep(0.2)
        raise AssertionError(f'Timed out waiting for Postgres port mapping for {self.name}: {last_error}')

    def wait_ready(self, *, timeout: float = 90) -> None:
        deadline = time.time() + timeout
        last_error = ''
        while time.time() < deadline:
            try:
                with psycopg.connect(self.url.replace('+psycopg', ''), autocommit=True) as connection:
                    connection.execute('SELECT 1')
                return
            except psycopg.Error as exc:
                last_error = str(exc)
                time.sleep(1)
        raise AssertionError(f'Timed out waiting for Postgres container {self.name}: {last_error}')

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.url.replace('+psycopg', ''), autocommit=True)

    def stop(self) -> None:
        if self.container_id is None:
            return
        run_command(['docker', 'rm', '-f', self.name], env=docker_env(), check=False, timeout=120)
        self.container_id = None
        self.port = None

    def __enter__(self) -> PostgresContainer:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
