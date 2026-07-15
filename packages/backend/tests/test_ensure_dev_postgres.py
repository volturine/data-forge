from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('ensure_dev_postgres', ROOT / 'scripts' / 'ensure_dev_postgres.py')
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def done(args: list[str], *, returncode: int = 0, stdout: str = '', stderr: str = '') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)


def test_parse_database_url_extracts_container_settings() -> None:
    cfg = MODULE.parse_database_url('postgresql+psycopg://dev%40user:secret%21@127.0.0.1:5544/dataforge')

    assert cfg.host == '127.0.0.1'
    assert cfg.port == 5544
    assert cfg.database == 'dataforge'
    assert cfg.user == 'dev@user'
    assert cfg.password == 'secret!'
    assert cfg.container == 'data-forge-dev-postgres-5544'
    assert cfg.volume == 'data-forge-dev-postgres-5544-data'


def test_ensure_local_postgres_skips_remote_hosts() -> None:
    calls: list[list[str]] = []

    def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return done(args)

    MODULE.ensure_local_postgres(
        'postgresql+psycopg://user:pass@db.example.com:5432/dataforge',
        run=run,
        probe=lambda database_url, timeout=1.0: False,
        sleep=lambda _: None,
    )

    assert calls == []


def test_ensure_local_postgres_creates_container_when_missing() -> None:
    calls: list[list[str]] = []
    probes = iter([False, True])

    def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args == ['docker', 'info']:
            return done(args)
        if args[:4] == ['docker', 'container', 'inspect', 'data-forge-dev-postgres-5432']:
            return done(args, returncode=1, stderr='No such container')
        if args == ['docker', 'container', 'inspect', '-f', '{{.State.Status}}', 'data-forge-dev-postgres-5432']:
            return done(args, stdout='running\n')
        if args[:4] == ['docker', 'volume', 'create', '--label']:
            return done(args, stdout='created-volume\n')
        if args[:2] == ['docker', 'run']:
            return done(args, stdout='container-id\n')
        raise AssertionError(f'unexpected command: {args}')

    MODULE.ensure_local_postgres(
        'postgresql+psycopg://user:pass@127.0.0.1:5432/dataforge',
        run=run,
        probe=lambda database_url, timeout=1.0: next(probes),
        sleep=lambda _: None,
    )

    assert calls == [
        ['docker', 'info'],
        ['docker', 'container', 'inspect', 'data-forge-dev-postgres-5432'],
        ['docker', 'container', 'inspect', 'data-forge-dev-postgres-5432'],
        ['docker', 'volume', 'create', '--label', 'data-forge.dev-postgres=1', 'data-forge-dev-postgres-5432-data'],
        [
            'docker',
            'run',
            '-d',
            '--name',
            'data-forge-dev-postgres-5432',
            '--label',
            'data-forge.dev-postgres=1',
            '-e',
            'POSTGRES_DB=dataforge',
            '-e',
            'POSTGRES_USER=user',
            '-e',
            'POSTGRES_PASSWORD=pass',
            '-p',
            '127.0.0.1:5432:5432',
            '-v',
            'data-forge-dev-postgres-5432-data:/var/lib/postgresql',
            'postgres:18-alpine',
        ],
        ['docker', 'container', 'inspect', '-f', '{{.State.Status}}', 'data-forge-dev-postgres-5432'],
    ]


def test_ensure_local_postgres_starts_existing_stopped_container() -> None:
    calls: list[list[str]] = []
    probes = iter([False, True])

    def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args == ['docker', 'info']:
            return done(args)
        if args[:4] == ['docker', 'container', 'inspect', 'data-forge-dev-postgres-5432']:
            return done(args, stdout='[]')
        if args == [
            'docker',
            'container',
            'inspect',
            '-f',
            '{{range .Mounts}}{{println .Destination}}{{end}}',
            'data-forge-dev-postgres-5432',
        ]:
            return done(args, stdout='/var/lib/postgresql\n')
        if args[:5] == ['docker', 'container', 'inspect', '-f', '{{.State.Running}}']:
            return done(args, stdout='false\n')
        if args == ['docker', 'container', 'inspect', '-f', '{{.State.Status}}', 'data-forge-dev-postgres-5432']:
            return done(args, stdout='running\n')
        if args[:2] == ['docker', 'start']:
            return done(args, stdout='data-forge-dev-postgres-5432\n')
        raise AssertionError(f'unexpected command: {args}')

    MODULE.ensure_local_postgres(
        'postgresql+psycopg://user:pass@127.0.0.1:5432/dataforge',
        run=run,
        probe=lambda database_url, timeout=1.0: next(probes),
        sleep=lambda _: None,
    )

    assert calls == [
        ['docker', 'info'],
        ['docker', 'container', 'inspect', 'data-forge-dev-postgres-5432'],
        ['docker', 'container', 'inspect', '-f', '{{range .Mounts}}{{println .Destination}}{{end}}', 'data-forge-dev-postgres-5432'],
        ['docker', 'container', 'inspect', 'data-forge-dev-postgres-5432'],
        ['docker', 'container', 'inspect', '-f', '{{.State.Running}}', 'data-forge-dev-postgres-5432'],
        ['docker', 'start', 'data-forge-dev-postgres-5432'],
        ['docker', 'container', 'inspect', '-f', '{{.State.Status}}', 'data-forge-dev-postgres-5432'],
    ]


def test_ensure_local_postgres_recreates_stale_mount_container() -> None:
    calls: list[list[str]] = []
    probes = iter([False, True])

    def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args == ['docker', 'info']:
            return done(args)
        if args[:4] == ['docker', 'container', 'inspect', 'data-forge-dev-postgres-5432']:
            if len([call for call in calls if call[:4] == args[:4]]) == 1:
                return done(args, stdout='[]')
            return done(args, returncode=1, stderr='No such container')
        if args == [
            'docker',
            'container',
            'inspect',
            '-f',
            '{{range .Mounts}}{{println .Destination}}{{end}}',
            'data-forge-dev-postgres-5432',
        ]:
            return done(args, stdout='/var/lib/postgresql/data\n')
        if args[:2] == ['docker', 'rm']:
            return done(args)
        if args[:3] == ['docker', 'volume', 'rm']:
            return done(args)
        if args[:4] == ['docker', 'volume', 'create', '--label']:
            return done(args)
        if args[:2] == ['docker', 'run']:
            return done(args, stdout='container-id\n')
        if args == ['docker', 'container', 'inspect', '-f', '{{.State.Status}}', 'data-forge-dev-postgres-5432']:
            return done(args, stdout='running\n')
        raise AssertionError(f'unexpected command: {args}')

    MODULE.ensure_local_postgres(
        'postgresql+psycopg://user:pass@127.0.0.1:5432/dataforge',
        run=run,
        probe=lambda database_url, timeout=1.0: next(probes),
        sleep=lambda _: None,
    )

    assert ['docker', 'rm', '-f', 'data-forge-dev-postgres-5432'] in calls
    assert ['docker', 'volume', 'rm', '-f', 'data-forge-dev-postgres-5432-data'] in calls
    assert ['docker', 'volume', 'create', '--label', 'data-forge.dev-postgres=1', 'data-forge-dev-postgres-5432-data'] in calls


def test_ensure_local_postgres_fails_without_docker() -> None:
    with pytest.raises(RuntimeError, match='Docker is unavailable'):
        MODULE.ensure_local_postgres(
            'postgresql+psycopg://user:pass@127.0.0.1:5432/dataforge',
            run=lambda args, check=True: (_ for _ in ()).throw(FileNotFoundError(args[0])),
            probe=lambda database_url, timeout=1.0: False,
            sleep=lambda _: None,
        )
