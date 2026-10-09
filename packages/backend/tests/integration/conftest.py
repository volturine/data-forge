from __future__ import annotations

import pytest
from faux_datasource_runtime import FauxDatasourceRuntime

from tests.harness.base_fixtures import cleanup_stale_test_compute_worker_networks_for_controller


def pytest_sessionstart(session: pytest.Session) -> None:
    # Workers share one daemon; clean orphaned networks once before they start.
    cleanup_stale_test_compute_worker_networks_for_controller(session)


@pytest.fixture
def faux_datasource_runtime() -> FauxDatasourceRuntime:
    return FauxDatasourceRuntime()


@pytest.fixture(autouse=True)
def install_faux_datasource_runtime(
    faux_datasource_runtime: FauxDatasourceRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    faux_datasource_runtime.install(monkeypatch)
