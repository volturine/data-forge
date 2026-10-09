from __future__ import annotations

import logging

from runtime.environment import read_env, read_int


def test_new_environment_name_takes_precedence_without_warning(monkeypatch, caplog) -> None:
    monkeypatch.setenv("COMPUTE_WORKER_IMAGE", "compute-worker:new")
    monkeypatch.setenv("DF_ENGINE_IMAGE", "compute-worker:old")

    with caplog.at_level(logging.WARNING):
        value = read_env("COMPUTE_WORKER_IMAGE", legacy_names=("DF_ENGINE_IMAGE",))

    assert value == "compute-worker:new"
    assert not caplog.records


def test_legacy_environment_name_is_read_and_deprecated(monkeypatch, caplog) -> None:
    monkeypatch.delenv("COMPUTE_WORKER_IMAGE", raising=False)
    monkeypatch.setenv("DF_ENGINE_IMAGE", "compute-worker:legacy")

    with caplog.at_level(logging.WARNING):
        value = read_env("COMPUTE_WORKER_IMAGE", legacy_names=("DF_ENGINE_IMAGE",))

    assert value == "compute-worker:legacy"
    assert "DF_ENGINE_IMAGE" in caplog.text
    assert "COMPUTE_WORKER_IMAGE" in caplog.text


def test_legacy_integer_setting_uses_new_validation_name(monkeypatch, caplog) -> None:
    monkeypatch.delenv("COMPUTE_WORKER_RPC_PORT", raising=False)
    monkeypatch.setenv("ENGINE_RPC_PORT", "60000")

    with caplog.at_level(logging.WARNING):
        value = read_int("COMPUTE_WORKER_RPC_PORT", 50053, max_value=65535, legacy_names=("ENGINE_RPC_PORT",))

    assert value == 60000
    assert "ENGINE_RPC_PORT" in caplog.text

    monkeypatch.setenv("ENGINE_RPC_PORT", "70000")
    try:
        read_int("COMPUTE_WORKER_RPC_PORT", 50053, max_value=65535, legacy_names=("ENGINE_RPC_PORT",))
    except RuntimeError as exc:
        assert "COMPUTE_WORKER_RPC_PORT" in str(exc)
    else:
        raise AssertionError("expected the renamed environment variable to be validated")
