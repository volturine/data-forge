from main import _resolve_uvicorn_limit_concurrency, _resolve_uvicorn_workers


class TestUvicornSettings:
    def test_resolve_uvicorn_workers_uses_auto_for_non_positive(self, monkeypatch) -> None:
        from core.config import settings

        monkeypatch.setattr(settings, 'debug', False, raising=False)
        monkeypatch.setattr(settings, 'workers', 0, raising=False)
        monkeypatch.setattr('main.os.cpu_count', lambda: 4)

        assert _resolve_uvicorn_workers() == 9

    def test_resolve_uvicorn_workers_forces_single_worker_in_debug(self, monkeypatch) -> None:
        from core.config import settings

        monkeypatch.setattr(settings, 'debug', True, raising=False)
        monkeypatch.setattr(settings, 'workers', 8, raising=False)

        assert _resolve_uvicorn_workers() == 1

    def test_resolve_uvicorn_limit_concurrency_ignores_non_positive(self, monkeypatch) -> None:
        from core.config import settings

        monkeypatch.setattr(settings, 'worker_connections', -1, raising=False)
        assert _resolve_uvicorn_limit_concurrency() is None

        monkeypatch.setattr(settings, 'worker_connections', 100, raising=False)
        assert _resolve_uvicorn_limit_concurrency() == 100
