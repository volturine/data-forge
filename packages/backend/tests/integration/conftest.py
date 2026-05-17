from __future__ import annotations

import pytest
from faux_datasource_runtime import FauxDatasourceRuntime


@pytest.fixture
def faux_datasource_runtime() -> FauxDatasourceRuntime:
    return FauxDatasourceRuntime()


@pytest.fixture(autouse=True)
def install_faux_datasource_runtime(
    faux_datasource_runtime: FauxDatasourceRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    faux_datasource_runtime.install(monkeypatch)
