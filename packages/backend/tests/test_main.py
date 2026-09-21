import pytest
from fastapi.responses import FileResponse

from backend_core import runtime_workers_service as runtime_worker_service
from backend_core.database import run_settings_db
from backend_core.domain.runtime_workers.models import RuntimeWorkerKind
from main import (
    _configure_sync_thread_capacity,
    _guard_runtime_workers,
    _resolve_uvicorn_limit_concurrency,
    _resolve_uvicorn_workers,
)


class TestUvicornSettings:
    @pytest.mark.asyncio
    async def test_sync_thread_capacity_matches_database_budget(self, monkeypatch) -> None:
        import anyio.to_thread

        from backend_core.config import settings

        monkeypatch.setattr(settings, 'worker_connections', 64, raising=False)
        monkeypatch.setattr(settings, 'database_pool_size', 32, raising=False)
        monkeypatch.setattr(settings, 'database_max_overflow', 16, raising=False)
        limiter = anyio.to_thread.current_default_thread_limiter()
        original = limiter.total_tokens
        try:
            limiter.total_tokens = 40
            assert _configure_sync_thread_capacity() == 48
        finally:
            limiter.total_tokens = original

    def test_resolve_uvicorn_workers_uses_auto_for_non_positive(self, monkeypatch) -> None:
        from backend_core.config import settings

        monkeypatch.setattr(settings, 'debug', False, raising=False)
        monkeypatch.setattr(settings, 'workers', 0, raising=False)
        monkeypatch.setattr('main.os.cpu_count', lambda: 4)

        assert _resolve_uvicorn_workers() == 9

    def test_resolve_uvicorn_workers_forces_single_worker_in_debug(self, monkeypatch) -> None:
        from backend_core.config import settings

        monkeypatch.setattr(settings, 'debug', True, raising=False)
        monkeypatch.setattr(settings, 'workers', 8, raising=False)

        assert _resolve_uvicorn_workers() == 1

    def test_guard_runtime_workers_rejects_auto_resolved_multi_worker_count(self, monkeypatch) -> None:
        from backend_core.config import settings

        monkeypatch.setattr(settings, 'debug', False, raising=False)
        monkeypatch.setattr(settings, 'workers', 0, raising=False)
        monkeypatch.setattr('main.os.cpu_count', lambda: 4)

        with pytest.raises(RuntimeError, match='Multiple workers are not supported'):
            _guard_runtime_workers(_resolve_uvicorn_workers())

    def test_guard_runtime_workers_allows_single_worker(self) -> None:
        assert _guard_runtime_workers(1) == 1

    def test_guard_runtime_workers_rejects_multiple_workers(self) -> None:
        with pytest.raises(RuntimeError, match='Multiple workers are not supported'):
            _guard_runtime_workers(2)

    def test_guard_runtime_workers_allows_multiple_workers_with_distributed_runtime(self, monkeypatch) -> None:
        monkeypatch.setattr('main.supports_distributed_runtime', lambda: True)

        assert _guard_runtime_workers(2) == 2

    def test_resolve_uvicorn_limit_concurrency_ignores_non_positive(self, monkeypatch) -> None:
        from backend_core.config import settings

        monkeypatch.setattr(settings, 'worker_connections', -1, raising=False)
        assert _resolve_uvicorn_limit_concurrency() is None

        monkeypatch.setattr(settings, 'worker_connections', 100, raising=False)
        assert _resolve_uvicorn_limit_concurrency() == 100

    def test_main_module_no_longer_owns_scheduler_loop(self) -> None:
        import main

        assert not hasattr(main, 'scheduler_loop')

    def test_main_module_no_longer_owns_embedded_build_worker_toggle(self) -> None:
        import main

        assert not hasattr(main, '_should_start_embedded_build_worker')

    def test_api_worker_register_and_stop_lifecycle(self, monkeypatch) -> None:
        import main

        monkeypatch.setattr('main.socket.gethostname', lambda: 'host-1')
        monkeypatch.setattr('main.os.getpid', lambda: 12345)

        main._register_api_worker('api:12345')
        worker = run_settings_db(lambda session: runtime_worker_service.get_worker(session, 'api:12345'))

        assert worker is not None
        assert worker.kind == RuntimeWorkerKind.API
        assert worker.hostname == 'host-1'
        assert worker.pid == 12345
        assert worker.stopped_at is None

        main._stop_api_worker('api:12345')
        stopped = run_settings_db(lambda session: runtime_worker_service.get_worker(session, 'api:12345'))

        assert stopped is not None
        assert stopped.stopped_at is not None

    @pytest.mark.asyncio
    async def test_static_route_serves_prerendered_extensionless_document(self, monkeypatch, tmp_path) -> None:
        import main

        (tmp_path / 'login.html').write_text('<h1>Sign in</h1>', encoding='utf8')
        (tmp_path / '200.html').write_text('<script>spa fallback</script>', encoding='utf8')
        monkeypatch.setattr(main.settings, 'prod_mode_enabled', True, raising=False)
        monkeypatch.setattr(main, 'frontend_build_dir', tmp_path)

        response = await main.serve_static_or_index('login')

        assert isinstance(response, FileResponse)
        assert response.path == str(tmp_path / 'login.html')

    @pytest.mark.asyncio
    async def test_static_route_uses_loaded_frontend_asset_cache(self, monkeypatch, tmp_path) -> None:
        import main

        asset = tmp_path / '_app' / 'immutable' / 'entry.js'
        asset.parent.mkdir(parents=True)
        asset.write_bytes(b'console.log("cached");')
        monkeypatch.setattr(main.settings, 'prod_mode_enabled', True, raising=False)
        monkeypatch.setattr(main, 'frontend_build_dir', tmp_path)

        main._load_frontend_asset_cache()
        response = await main.serve_static_or_index('_app/immutable/entry.js')

        assert not isinstance(response, FileResponse)
        assert response.body == b'console.log("cached");'
        assert response.headers['cache-control'] == 'public, max-age=31536000, immutable'
