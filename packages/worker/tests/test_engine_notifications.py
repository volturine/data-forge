from threading import Event

import runtime.engine_notifications as engine_notifications
from runtime.domain.compute.base import EngineStatusInfo


def _status(resource_id: str) -> EngineStatusInfo:
    return EngineStatusInfo(
        analysis_id=resource_id,
        resource_id=resource_id,
        status="running",
        container_id=None,
        image_digest=None,
        lifecycle_status=None,
        termination_reason=None,
        exit_code=None,
        oom_killed=None,
        supervisor_id=None,
        owner_id=None,
        last_activity=None,
        current_job_id=None,
        resource_config=None,
        effective_resources=None,
        defaults={},
    )


def test_snapshot_projection_failure_retries_without_failing_engine_lifecycle(monkeypatch) -> None:
    calls = 0
    succeeded = Event()

    def fail_once(*, worker_id: str, namespace: str, statuses) -> None:
        nonlocal calls
        del worker_id, namespace, statuses
        calls += 1
        if calls == 1:
            raise RuntimeError("api worker replaced")
        succeeded.set()

    monkeypatch.setattr(engine_notifications, "persist_engine_snapshot", fail_once)
    notify = engine_notifications.create_snapshot_notifier(
        namespace_provider=lambda: "default",
        worker_id="build-manager-1",
    )
    try:
        notify([])
        assert succeeded.wait(2)
    finally:
        notify.close()

    assert calls == 2


def test_snapshot_publisher_coalesces_to_latest_per_namespace() -> None:
    first_started = Event()
    release_first = Event()
    calls: list[tuple[str, list[str]]] = []

    def persist(namespace: str, statuses: list[EngineStatusInfo]) -> None:
        resource_ids = [status.resource_id for status in statuses]
        calls.append((namespace, resource_ids))
        if resource_ids == ["first"]:
            first_started.set()
            assert release_first.wait(2)

    notify = engine_notifications.create_snapshot_notifier(
        namespace_provider=lambda: "default",
        persist=persist,
    )
    try:
        notify([_status("first")])
        assert first_started.wait(2)
        notify([_status("stale")])
        notify([_status("latest")])
        notify.publish("other", [_status("other")])
        release_first.set()
    finally:
        release_first.set()
        notify.close()

    assert calls == [("default", ["first"]), ("default", ["latest"]), ("other", ["other"])]


def test_snapshot_publisher_logs_slow_round_trip_with_engine_count(monkeypatch, caplog) -> None:
    completed = Event()
    monkeypatch.setattr(engine_notifications, "_SLOW_SNAPSHOT_PUBLISH_SECONDS", 0.0)

    def persist(_namespace: str, _statuses: list[EngineStatusInfo]) -> None:
        completed.set()

    notify = engine_notifications.create_snapshot_notifier(
        namespace_provider=lambda: "default",
        persist=persist,
    )
    try:
        with caplog.at_level("WARNING", logger="runtime.engine_notifications"):
            notify([_status("analysis-1"), _status("analysis-2")])
            assert completed.wait(2)
            notify.close()
    finally:
        notify.close()

    assert "Slow engine snapshot publish namespace=default engine_count=2 duration_ms=" in caplog.text
