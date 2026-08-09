from __future__ import annotations

import os

from runtime.config import settings
from runtime.docker_engine import _effective_resources


def test_effective_resources_resolves_zero_threads_to_logical_cpu_count(monkeypatch) -> None:
    monkeypatch.setattr(settings, "polars_cores_available", 0)

    resources = _effective_resources({"max_threads": 0})

    assert resources["max_threads"] == (os.cpu_count() or 1)
    assert resources["max_threads"] > 0


def test_effective_resources_caps_requested_threads_to_global_limit(monkeypatch) -> None:
    monkeypatch.setattr(settings, "polars_cores_available", 4)

    assert _effective_resources({"max_threads": 8})["max_threads"] == 4
