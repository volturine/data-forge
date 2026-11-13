"""Runtime work listing filters."""

import logging

import pytest

from backend_core import runtime_work_service


def test_invalid_namespace_warning_is_logged_once_per_process(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(runtime_work_service, '_WARNED_INVALID_NAMESPACES', set())
    caplog.set_level(logging.WARNING, logger=runtime_work_service.__name__)

    results = [runtime_work_service._servable_namespace(namespace) for namespace in ('team_a', 'team_a', 'default', 'team_b', 'team_a')]

    assert results == [False, False, True, False, False]
    warnings = [record.getMessage() for record in caplog.records if record.name == runtime_work_service.__name__]
    assert warnings == ["Skipping runtime work for invalid namespace 'team_a'", "Skipping runtime work for invalid namespace 'team_b'"]
