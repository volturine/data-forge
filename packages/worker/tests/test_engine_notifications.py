import asyncio

import runtime.engine_notifications as engine_notifications


def test_snapshot_projection_failure_does_not_fail_engine_lifecycle(monkeypatch) -> None:
    loop = asyncio.new_event_loop()
    try:
        calls: list[tuple[str, str]] = []

        def fail_to_persist(*, worker_id: str, namespace: str, statuses) -> None:
            del statuses
            calls.append((worker_id, namespace))
            raise RuntimeError("api worker replaced")

        monkeypatch.setattr(engine_notifications, "persist_engine_snapshot", fail_to_persist)
        notify = engine_notifications.create_snapshot_notifier(
            loop,
            namespace_provider=lambda: "default",
            worker_id="build-manager-1",
        )

        notify([])

        assert calls == [("build-manager-1", "default")]
    finally:
        loop.close()
