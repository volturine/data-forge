from __future__ import annotations

import pytest

from runtime.environment import read_env, read_int


def test_blank_values_fall_back_and_integer_bounds_name_the_variable(monkeypatch) -> None:
    monkeypatch.setenv("COMPUTE_WORKER_IMAGE", "  ")
    monkeypatch.setenv("COMPUTE_WORKER_RPC_PORT", "70000")

    assert read_env("COMPUTE_WORKER_IMAGE", "compute-worker:default") == "compute-worker:default"
    with pytest.raises(RuntimeError, match="COMPUTE_WORKER_RPC_PORT must be at most 65535"):
        read_int("COMPUTE_WORKER_RPC_PORT", 50053, max_value=65535)
