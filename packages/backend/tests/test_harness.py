from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace
from typing import cast

import pytest

from tests.harness import base_fixtures, postgres_harness
from tests.harness.postgres_harness import DockerResourceOwner, PostgresContainer, RustfsContainer


def _docker_labels(owner: DockerResourceOwner, resource_label: str) -> dict[str, str]:
    arguments = owner.docker_labels(resource_label)
    labels: dict[str, str] = {}
    for flag, argument in zip(arguments[::2], arguments[1::2], strict=True):
        if flag != '--label':
            continue
        key, value = argument.split('=', maxsplit=1)
        labels[key] = value
    return labels


def _owner_labels(*, host: str = 'test-host', pid: int, process_start: float) -> dict[str, str]:
    return {
        'data-forge.test-owner-host': host,
        'data-forge.test-owner-pid': str(pid),
        'data-forge.test-owner-start': format(process_start, '.17g'),
    }


def test_sessionstart_stale_container_cleanup_runs_only_in_xdist_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        'POLARS_CORES_AVAILABLE',
        'POLARS_MAX_THREADS',
        'POLARS_STREAMING_CHUNK_SIZE',
        'ENV_FILE',
        'SETTINGS_ENCRYPTION_KEY',
        'DATABASE_URL',
    ):
        monkeypatch.setenv(key, 'test-value')
    monkeypatch.delenv('TEST_POSTGRES_URL', raising=False)
    monkeypatch.setattr(base_fixtures, 'docker_available', lambda: True)
    cleanups: list[str] = []
    monkeypatch.setattr(base_fixtures, 'cleanup_stale_test_postgres', lambda: cleanups.append('postgres'))
    monkeypatch.setattr(base_fixtures, 'cleanup_stale_test_rustfs', lambda: cleanups.append('rustfs'))

    worker_session = cast(pytest.Session, SimpleNamespace(config=SimpleNamespace(workerinput={})))
    base_fixtures.pytest_sessionstart(worker_session)
    assert cleanups == []

    controller_session = cast(pytest.Session, SimpleNamespace(config=SimpleNamespace()))
    base_fixtures.pytest_sessionstart(controller_session)
    assert cleanups == ['postgres', 'rustfs']


def test_cleanup_from_second_session_preserves_live_first_session_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    owner_process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        owner = DockerResourceOwner.for_pid(owner_process.pid)
        labels = _docker_labels(owner, 'data-forge.test-postgres=1')
        live_labels = {'data-forge.test-postgres': '1', **labels}
        removed: list[list[str]] = []

        def fake_run_command(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            if command[1:3] == ['ps', '-aq']:
                return subprocess.CompletedProcess(command, 0, 'session-a-postgres\n', '')
            if command[1:4] == ['volume', 'ls', '-q']:
                return subprocess.CompletedProcess(command, 0, 'session-a-volume\n', '')
            if command[1] == 'inspect' or command[1:3] == ['volume', 'inspect']:
                return subprocess.CompletedProcess(command, 0, json.dumps(live_labels), '')
            removed.append(command)
            return subprocess.CompletedProcess(command, 0, '', '')

        monkeypatch.setattr(postgres_harness, 'run_command', fake_run_command)
        postgres_harness.cleanup_stale_test_postgres()

        assert removed == []
    finally:
        owner_process.terminate()
        owner_process.wait(timeout=5)


def test_stale_cleanup_removes_dead_and_reused_process_containers_and_volumes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(postgres_harness.socket, 'gethostname', lambda: 'test-host')

    def fake_process(pid: int) -> SimpleNamespace:
        if pid == 22:
            return SimpleNamespace(create_time=lambda: 200.0)
        raise postgres_harness.psutil.NoSuchProcess(pid)

    monkeypatch.setattr(postgres_harness.psutil, 'Process', fake_process)
    owners = {
        'dead-container': {'data-forge.test-postgres': '1', **_owner_labels(pid=21, process_start=100.0)},
        'reused-volume': {'data-forge.test-postgres': '1', **_owner_labels(pid=22, process_start=100.0)},
    }
    removed: list[list[str]] = []

    def fake_run_command(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ['ps', '-aq']:
            return subprocess.CompletedProcess(command, 0, 'dead-container\n', '')
        if command[1:4] == ['volume', 'ls', '-q']:
            return subprocess.CompletedProcess(command, 0, 'reused-volume\n', '')
        if command[1] == 'inspect' or command[1:3] == ['volume', 'inspect']:
            return subprocess.CompletedProcess(command, 0, json.dumps(owners[command[-1]]), '')
        removed.append(command)
        return subprocess.CompletedProcess(command, 0, '', '')

    monkeypatch.setattr(postgres_harness, 'run_command', fake_run_command)
    postgres_harness.cleanup_stale_test_postgres()

    assert removed == [
        ['docker', 'rm', '-f', 'dead-container'],
        ['docker', 'volume', 'rm', '-f', 'reused-volume'],
    ]


@pytest.mark.parametrize(
    ('labels', 'process_error'),
    [
        ({'data-forge.test-postgres': '1'}, None),
        ({'data-forge.test-postgres': '1', **_owner_labels(host='other-host', pid=31, process_start=100.0)}, None),
        ({'data-forge.test-postgres': '1', **_owner_labels(pid=32, process_start=100.0)}, 'access-denied'),
    ],
)
def test_cleanup_preserves_unknown_foreign_and_inaccessible_owners(monkeypatch: pytest.MonkeyPatch, labels: dict[str, str], process_error: str | None) -> None:
    monkeypatch.setattr(postgres_harness.socket, 'gethostname', lambda: 'test-host')

    def fake_process(pid: int) -> SimpleNamespace:
        if process_error == 'access-denied':
            raise postgres_harness.psutil.AccessDenied(pid)
        return SimpleNamespace(create_time=lambda: 100.0)

    monkeypatch.setattr(postgres_harness.psutil, 'Process', fake_process)
    removed: list[list[str]] = []

    def fake_run_command(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ['ps', '-aq']:
            return subprocess.CompletedProcess(command, 0, 'preserved-container\n', '')
        if command[1:4] == ['volume', 'ls', '-q']:
            return subprocess.CompletedProcess(command, 0, 'preserved-volume\n', '')
        if command[1] == 'inspect' or command[1:3] == ['volume', 'inspect']:
            return subprocess.CompletedProcess(command, 0, json.dumps(labels), '')
        removed.append(command)
        return subprocess.CompletedProcess(command, 0, '', '')

    monkeypatch.setattr(postgres_harness, 'run_command', fake_run_command)

    postgres_harness.cleanup_stale_test_postgres()

    assert removed == []


def test_new_postgres_resources_share_owner_labels_and_context_exit_targets_exact_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = DockerResourceOwner.current()
    container = PostgresContainer(owner=owner)
    commands: list[list[str]] = []

    def fake_run_command(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        stdout = 'container-id\n' if command[1:3] == ['run', '-d'] else ''
        return subprocess.CompletedProcess(command, 0, stdout, '')

    monkeypatch.setattr(postgres_harness, 'run_command', fake_run_command)
    monkeypatch.setattr(container, '_wait_for_port_mapping', lambda: 54321)
    monkeypatch.setattr(container, 'wait_ready', lambda: None)

    container.__enter__()
    container.__exit__(None, None, None)

    owner_labels = _docker_labels(owner, container.label)
    assert all(all(f'{key}={value}' in command for key, value in owner_labels.items()) for command in commands[:2])
    assert commands[2] == ['docker', 'rm', '-f', 'container-id']
    assert commands[3] == ['docker', 'volume', 'rm', '-f', container.volume_name]


def test_new_rustfs_container_carries_owner_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = DockerResourceOwner.current()
    container = RustfsContainer(owner=owner)
    commands: list[list[str]] = []

    def fake_run_command(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        stdout = 'container-id\n' if command[1:3] == ['run', '-d'] else ''
        return subprocess.CompletedProcess(command, 0, stdout, '')

    monkeypatch.setattr(postgres_harness, 'run_command', fake_run_command)
    monkeypatch.setattr(container, '_wait_for_port_mapping', lambda: 9000)
    monkeypatch.setattr(container, 'wait_ready', lambda: None)

    container.start()
    container.stop()

    owner_labels = _docker_labels(owner, container.label)
    assert all(f'{key}={value}' in commands[0] for key, value in owner_labels.items())


def test_integration_network_cleanup_runs_only_in_xdist_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base_fixtures, 'docker_available', lambda: True)
    cleanups: list[str] = []
    monkeypatch.setattr(base_fixtures, 'cleanup_stale_test_engine_networks', lambda: cleanups.append('networks'))

    worker_session = cast(pytest.Session, SimpleNamespace(config=SimpleNamespace(workerinput={})))
    base_fixtures.cleanup_stale_test_engine_networks_for_controller(worker_session)
    assert cleanups == []

    controller_session = cast(pytest.Session, SimpleNamespace(config=SimpleNamespace()))
    base_fixtures.cleanup_stale_test_engine_networks_for_controller(controller_session)
    assert cleanups == ['networks']
