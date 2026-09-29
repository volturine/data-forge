from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from tests.harness import base_fixtures


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
