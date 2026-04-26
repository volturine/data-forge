from __future__ import annotations

import contextlib
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend'
FRONTEND = ROOT / 'frontend'


def _load_env() -> dict[str, str]:
    env = os.environ.copy()
    path = BACKEND / 'e2e.env'
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        env[key] = value.strip().strip('"')
    env.pop('NO_COLOR', None)
    env.setdefault('PLAYWRIGHT_DISABLE_WEB_SERVER', 'true')
    return env


def _spawn(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    stdout: int | None = None,
    stderr: int | None = None,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )


def _kill_tree(proc: subprocess.Popen[str] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=5)


def _kill_port_listeners(ports: list[int]) -> None:
    for port in ports:
        result = subprocess.run(
            ['lsof', '-ti', f'tcp:{port}'],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode not in (0, 1):
            continue
        for raw_pid in result.stdout.splitlines():
            pid = raw_pid.strip()
            if not pid:
                continue
            with contextlib.suppress(ProcessLookupError, ValueError):
                os.kill(int(pid), signal.SIGTERM)


def _wait_for_port(port: int, *, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                return True
        time.sleep(1)
    return False


def _pipe_stream(stream, target, chunks: list[str]) -> None:
    if stream is None:
        return
    for line in stream:
        chunks.append(line)
        target.write(line)
        target.flush()


def _run_playwright(env: dict[str, str]) -> int:
    return subprocess.run(['npx', 'playwright', 'test'], cwd=FRONTEND, env=env, text=True, check=False).returncode


def _env_port(env: dict[str, str], key: str, default: int) -> int:
    value = env.get(key)
    if value is None:
        return default
    return int(value)


def main() -> int:
    env = _load_env()
    backend_port = _env_port(env, 'PORT', 8001)
    frontend_port = _env_port(env, 'FRONTEND_PORT', 3001)
    _kill_port_listeners([backend_port, frontend_port])
    backend_proc: subprocess.Popen[str] | None = None
    worker_proc: subprocess.Popen[str] | None = None
    scheduler_proc: subprocess.Popen[str] | None = None
    frontend_proc: subprocess.Popen[str] | None = None
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    threads: list[threading.Thread] = []
    try:
        backend_proc = _spawn(
            ['uv', 'run', '--no-env-file', './main.py'],
            cwd=BACKEND,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        worker_proc = _spawn(
            ['uv', 'run', '--no-env-file', './worker.py'],
            cwd=BACKEND,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        scheduler_proc = _spawn(
            ['uv', 'run', '--no-env-file', './scheduler.py'],
            cwd=BACKEND,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        frontend_proc = _spawn(
            ['sh', '-lc', 'bun run predev && exec node ./node_modules/vite/bin/vite.js dev'],
            cwd=FRONTEND,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for proc in [backend_proc, worker_proc, scheduler_proc, frontend_proc]:
            for stream, target, chunks in [
                (proc.stdout, sys.stdout, stdout_chunks),
                (proc.stderr, sys.stderr, stderr_chunks),
            ]:
                thread = threading.Thread(target=_pipe_stream, args=(stream, target, chunks), daemon=True)
                thread.start()
                threads.append(thread)
        if not _wait_for_port(backend_port, timeout=90) or not _wait_for_port(frontend_port, timeout=90):
            print('Timed out waiting for backend/frontend to start for e2e tests', file=sys.stderr)
            return 1
        return _run_playwright(env)
    finally:
        _kill_tree(frontend_proc)
        _kill_tree(scheduler_proc)
        _kill_tree(worker_proc)
        _kill_tree(backend_proc)
        for thread in threads:
            thread.join(timeout=1)


if __name__ == '__main__':
    raise SystemExit(main())
