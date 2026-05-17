import pytest
from contracts.runtime_workers.models import RuntimeWorkerKind
from core import runtime_workers_service as runtime_worker_service
from core.database import run_settings_db

from main import (
    _guard_runtime_workers,
    _resolve_uvicorn_limit_concurrency,
    _resolve_uvicorn_workers,
)


class TestUvicornSettings:
    def test_resolve_uvicorn_workers_uses_auto_for_non_positive(self, monkeypatch) -> None:
        from core.config import settings

        monkeypatch.setattr(settings, "debug", False, raising=False)
        monkeypatch.setattr(settings, "workers", 0, raising=False)
        monkeypatch.setattr("main.os.cpu_count", lambda: 4)

        assert _resolve_uvicorn_workers() == 9

    def test_resolve_uvicorn_workers_forces_single_worker_in_debug(self, monkeypatch) -> None:
        from core.config import settings

        monkeypatch.setattr(settings, "debug", True, raising=False)
        monkeypatch.setattr(settings, "workers", 8, raising=False)

        assert _resolve_uvicorn_workers() == 1

    def test_guard_runtime_workers_rejects_auto_resolved_multi_worker_count(self, monkeypatch) -> None:
        from core.config import settings

        monkeypatch.setattr(settings, "debug", False, raising=False)
        monkeypatch.setattr(settings, "workers", 0, raising=False)
        monkeypatch.setattr("main.os.cpu_count", lambda: 4)

        with pytest.raises(RuntimeError, match="Multiple workers are not supported"):
            _guard_runtime_workers(_resolve_uvicorn_workers())

    def test_guard_runtime_workers_allows_single_worker(self) -> None:
        assert _guard_runtime_workers(1) == 1

    def test_guard_runtime_workers_rejects_multiple_workers(self) -> None:
        with pytest.raises(RuntimeError, match="Multiple workers are not supported"):
            _guard_runtime_workers(2)

    def test_guard_runtime_workers_allows_multiple_workers_with_distributed_runtime(self, monkeypatch) -> None:
        monkeypatch.setattr("main.supports_distributed_runtime", lambda: True)

        assert _guard_runtime_workers(2) == 2

    def test_resolve_uvicorn_limit_concurrency_ignores_non_positive(self, monkeypatch) -> None:
        from core.config import settings

        monkeypatch.setattr(settings, "worker_connections", -1, raising=False)
        assert _resolve_uvicorn_limit_concurrency() is None

        monkeypatch.setattr(settings, "worker_connections", 100, raising=False)
        assert _resolve_uvicorn_limit_concurrency() == 100

    def test_main_module_no_longer_owns_scheduler_loop(self) -> None:
        import main

        assert not hasattr(main, "scheduler_loop")

    def test_main_module_no_longer_owns_embedded_build_worker_toggle(self) -> None:
        import main

        assert not hasattr(main, "_should_start_embedded_build_worker")

    def test_api_worker_register_and_stop_lifecycle(self, monkeypatch) -> None:
        import main

        monkeypatch.setattr("main.socket.gethostname", lambda: "host-1")
        monkeypatch.setattr("main.os.getpid", lambda: 12345)

        main._register_api_worker("api:12345")
        worker = run_settings_db(lambda session: runtime_worker_service.get_worker(session, "api:12345"))

        assert worker is not None
        assert worker.kind == RuntimeWorkerKind.API
        assert worker.hostname == "host-1"
        assert worker.pid == 12345
        assert worker.stopped_at is None

        main._stop_api_worker("api:12345")
        stopped = run_settings_db(lambda session: runtime_worker_service.get_worker(session, "api:12345"))

        assert stopped is not None
        assert stopped.stopped_at is not None
