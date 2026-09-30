import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend_core.api_execution_budget import ApiDatabaseBudget
from main import (
    _api_observability_snapshot,
    _api_thread_budget,
    _configure_sync_thread_capacity,
    _guard_runtime_workers,
    _prewarm_anyio_thread_pool,
    _prewarm_executor,
    _resolve_uvicorn_limit_concurrency,
    _resolve_uvicorn_workers,
    app,
)


class TestUvicornSettings:
    @pytest.mark.asyncio
    async def test_prewarm_starts_all_configured_anyio_threads(self) -> None:
        import anyio.to_thread

        limiter = anyio.to_thread.current_default_thread_limiter()
        original = limiter.total_tokens
        try:
            limiter.total_tokens = 3
            assert await _prewarm_anyio_thread_pool(3) == 3
            assert limiter.statistics().borrowed_tokens == 0
            assert await anyio.to_thread.run_sync(lambda: threading.get_ident()) in {thread.ident for thread in threading.enumerate()}
        finally:
            limiter.total_tokens = original

    @pytest.mark.asyncio
    async def test_prewarm_rejects_anyio_worker_count_above_limiter(self) -> None:
        import anyio.to_thread

        limiter = anyio.to_thread.current_default_thread_limiter()
        original = limiter.total_tokens
        try:
            limiter.total_tokens = 1
            with pytest.raises(ValueError, match='1-token limiter'):
                await _prewarm_anyio_thread_pool(2)
        finally:
            limiter.total_tokens = original

    @pytest.mark.asyncio
    async def test_prewarm_starts_all_bounded_executor_threads(self) -> None:
        executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix='prewarm-test')
        try:
            await _prewarm_executor(executor, 3)
            assert sum(thread.name.startswith('prewarm-test_') for thread in threading.enumerate()) == 3
        finally:
            executor.shutdown(wait=True)

    @pytest.mark.asyncio
    async def test_prewarm_rejects_worker_count_above_executor_capacity(self) -> None:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='prewarm-test')
        try:
            with pytest.raises(ValueError, match='executor capped at 1'):
                await _prewarm_executor(executor, 2)
        finally:
            executor.shutdown(wait=True)

    @pytest.mark.asyncio
    async def test_slow_request_diagnostics_return_cached_snapshot_without_waiting(self, monkeypatch) -> None:
        import main

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='snapshot-test')
        refresh_started = threading.Event()
        allow_refresh = threading.Event()
        monkeypatch.setattr(main, '_API_DIAGNOSTICS_EXECUTOR', executor)
        monkeypatch.setattr(main, '_api_process_snapshot_refreshing', False)
        monkeypatch.setattr(
            main,
            '_api_process_snapshot_cache',
            (time.monotonic() - 10, {'snapshot': 'stale'}),
        )

        def refresh_snapshot() -> dict[str, object]:
            refresh_started.set()
            if not allow_refresh.wait(timeout=2):
                raise TimeoutError('test snapshot refresh was not released')
            with main._API_PROCESS_SNAPSHOT_LOCK:
                main._api_process_snapshot_cache = (time.monotonic(), {'snapshot': 'fresh'})
            return {'snapshot': 'fresh'}

        monkeypatch.setattr(main, '_api_process_snapshot', refresh_snapshot)
        try:
            snapshots = await asyncio.wait_for(
                asyncio.gather(*(_api_observability_snapshot() for _ in range(20))),
                timeout=0.2,
            )
            assert all(snapshot['snapshot'] == 'stale' for snapshot in snapshots)
            assert await asyncio.get_running_loop().run_in_executor(None, refresh_started.wait, 1)

            allow_refresh.set()
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                with main._API_PROCESS_SNAPSHOT_LOCK:
                    cache = main._api_process_snapshot_cache
                if cache is not None and cache[1].get('snapshot') == 'fresh':
                    break
                await asyncio.sleep(0.01)
            assert cache is not None and cache[1]['snapshot'] == 'fresh'
        finally:
            allow_refresh.set()
            executor.shutdown(wait=True)

    def test_api_uvicorn_disables_websocket_compression(self, monkeypatch) -> None:
        import uvicorn

        import main

        call: dict[str, object] = {}

        def capture_run(*args, **kwargs) -> None:
            call.update(kwargs)

        monkeypatch.setattr(uvicorn, 'run', capture_run)
        monkeypatch.setattr(main, '_resolve_uvicorn_workers', lambda: 1)
        monkeypatch.setattr(main, '_guard_runtime_workers', lambda workers: workers)
        monkeypatch.setattr(main, '_resolve_uvicorn_limit_concurrency', lambda: None)

        main._run_api_server()

        assert call['ws_per_message_deflate'] is False

    def test_cors_allows_and_exposes_client_request_ids(self) -> None:
        cors = next(middleware for middleware in app.user_middleware if middleware.cls is CORSMiddleware)
        allow_headers = cors.kwargs.get('allow_headers')
        expose_headers = cors.kwargs.get('expose_headers')
        assert isinstance(allow_headers, list) and 'X-Request-ID' in allow_headers
        assert isinstance(expose_headers, list) and 'X-Request-ID' in expose_headers

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
            assert _api_thread_budget() == ApiDatabaseBudget(12, 6, 4, 2)
            assert _configure_sync_thread_capacity() == 4
        finally:
            limiter.total_tokens = original

    def test_api_thread_budget_respects_a_single_pool_when_connections_are_unlimited(self, monkeypatch) -> None:
        from backend_core.config import settings

        monkeypatch.setattr(settings, 'worker_connections', 0, raising=False)
        monkeypatch.setattr(settings, 'database_pool_size', 8, raising=False)
        monkeypatch.setattr(settings, 'database_max_overflow', 4, raising=False)

        assert _api_thread_budget() == ApiDatabaseBudget(12, 6, 4, 2)

    def test_api_thread_budget_scales_down_with_database_pool(self, monkeypatch) -> None:
        from backend_core.config import settings

        monkeypatch.setattr(settings, 'worker_connections', 1000, raising=False)
        monkeypatch.setattr(settings, 'database_pool_size', 2, raising=False)
        monkeypatch.setattr(settings, 'database_max_overflow', 1, raising=False)

        assert _api_thread_budget() == ApiDatabaseBudget(3, 1, 1, 1)

    def test_api_budget_ignores_http_connection_limit(self, monkeypatch) -> None:
        from backend_core.config import settings

        monkeypatch.setattr(settings, 'worker_connections', 1, raising=False)
        monkeypatch.setattr(settings, 'database_pool_size', 8, raising=False)
        monkeypatch.setattr(settings, 'database_max_overflow', 4, raising=False)

        assert _api_thread_budget() == ApiDatabaseBudget(12, 6, 4, 2)

    def test_api_budget_rejects_database_capacity_below_three(self, monkeypatch) -> None:
        from backend_core.config import settings

        monkeypatch.setattr(settings, 'database_pool_size', 2, raising=False)
        monkeypatch.setattr(settings, 'database_max_overflow', 0, raising=False)

        with pytest.raises(ValueError, match='at least 3 pooled database connections'):
            _api_thread_budget()

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

        monkeypatch.setattr(settings, 'runtime_coordinator_target', '', raising=False)

        with pytest.raises(RuntimeError, match='RUNTIME_COORDINATOR_TARGET'):
            _guard_runtime_workers(_resolve_uvicorn_workers())

    def test_guard_runtime_workers_allows_single_worker(self, monkeypatch) -> None:
        from backend_core.config import settings

        monkeypatch.setattr(settings, 'runtime_coordinator_target', '', raising=False)
        assert _guard_runtime_workers(1) == 1

    def test_guard_runtime_workers_rejects_multiple_workers_without_coordinator(self, monkeypatch) -> None:
        from backend_core.config import settings

        monkeypatch.setattr(settings, 'runtime_coordinator_target', '', raising=False)

        with pytest.raises(RuntimeError, match='RUNTIME_COORDINATOR_TARGET'):
            _guard_runtime_workers(2)

    def test_guard_runtime_workers_allows_multiple_workers_with_coordinator(self, monkeypatch) -> None:
        from backend_core.config import settings

        monkeypatch.setattr(settings, 'distributed_runtime_enabled', True, raising=False)
        monkeypatch.setattr(settings, 'runtime_coordinator_target', 'runtime:50051', raising=False)

        assert _guard_runtime_workers(2) == 2

    def test_guard_runtime_workers_rejects_coordinator_without_distributed_runtime(self, monkeypatch) -> None:
        from backend_core.config import settings

        monkeypatch.setattr(settings, 'distributed_runtime_enabled', False, raising=False)
        monkeypatch.setattr(settings, 'runtime_coordinator_target', 'runtime:50051', raising=False)

        with pytest.raises(RuntimeError, match='DISTRIBUTED_RUNTIME_ENABLED'):
            _guard_runtime_workers(2)

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

    @pytest.mark.asyncio
    async def test_frontend_asset_cache_supports_symlinked_build_root(self, monkeypatch, tmp_path) -> None:
        import main

        target = tmp_path / 'build-target'
        asset = target / '_app' / 'immutable' / 'entry.js'
        asset.parent.mkdir(parents=True)
        asset.write_bytes(b'console.log("cached symlink");')
        linked_build = tmp_path / 'build-link'
        linked_build.symlink_to(target, target_is_directory=True)

        monkeypatch.setattr(main.settings, 'prod_mode_enabled', True, raising=False)
        monkeypatch.setattr(main, 'frontend_build_dir', linked_build)
        monkeypatch.setattr(main, '_FRONTEND_ASSET_CACHE', {})
        monkeypatch.setattr(main, '_FRONTEND_ASSET_CACHE_ROOT', None)
        monkeypatch.setattr(main, '_FRONTEND_ASSET_CACHE_SOURCE', None)

        main._load_frontend_asset_cache()
        response = await main.serve_static_or_index('_app/immutable/entry.js')

        assert not isinstance(response, FileResponse)
        assert response.body == b'console.log("cached symlink");'

    @pytest.mark.asyncio
    async def test_static_file_fallback_checks_filesystem_off_event_loop(self, monkeypatch, tmp_path) -> None:
        import main

        page = tmp_path / 'login.html'
        page.write_text('<html>login</html>')
        loop_thread = threading.get_ident()
        check_threads: list[int] = []
        original_is_file = type(page).is_file

        def is_file(path) -> bool:
            check_threads.append(threading.get_ident())
            return original_is_file(path)

        monkeypatch.setattr(main.settings, 'prod_mode_enabled', True, raising=False)
        monkeypatch.setattr(main, 'frontend_build_dir', tmp_path)
        monkeypatch.setattr(main, '_FRONTEND_ASSET_CACHE_ROOT', None)
        monkeypatch.setattr(main, '_cached_frontend_response', lambda _path: None)
        monkeypatch.setattr(type(page), 'is_file', is_file)

        response = await main.serve_static_or_index('login')

        assert isinstance(response, FileResponse)
        assert response.path == str(page)
        assert check_threads and all(thread_id != loop_thread for thread_id in check_threads)

    @pytest.mark.asyncio
    async def test_slow_request_snapshot_is_offloaded_and_coalesced(self, monkeypatch) -> None:
        import main

        loop_thread = threading.get_ident()
        snapshot_started = threading.Event()
        release_snapshot = threading.Event()
        database_calls: list[int] = []
        stack_calls: list[int] = []

        def database_snapshot() -> dict[str, object]:
            database_calls.append(threading.get_ident())
            snapshot_started.set()
            if not release_snapshot.wait(timeout=5):
                raise TimeoutError('test did not release the diagnostic snapshot')
            return {'settings_checkedout': 2}

        def thread_snapshot() -> dict[str, object]:
            stack_calls.append(threading.get_ident())
            return {'api_blocking_threads': ['api-blocking_0:route.py:10:handler']}

        monkeypatch.setattr(main, 'database_pool_snapshot', database_snapshot)
        monkeypatch.setattr(main, '_api_thread_snapshot', thread_snapshot)
        monkeypatch.setattr(main, '_api_process_snapshot_refreshing', False)
        monkeypatch.setattr(
            main,
            '_api_process_snapshot_cache',
            (time.monotonic() - 10, {'settings_checkedout': 0, 'api_blocking_threads': []}),
        )

        try:
            snapshots = await asyncio.wait_for(
                asyncio.gather(*(main._api_observability_snapshot() for _ in range(20))),
                timeout=0.2,
            )
            assert all(snapshot['settings_checkedout'] == 0 for snapshot in snapshots)
            started = await asyncio.to_thread(snapshot_started.wait, 2)
            assert started
        finally:
            release_snapshot.set()

        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            with main._API_PROCESS_SNAPSHOT_LOCK:
                cache = main._api_process_snapshot_cache
            if cache is not None and cache[1].get('settings_checkedout') == 2:
                break
            await asyncio.sleep(0.01)

        assert cache is not None and cache[1]['settings_checkedout'] == 2
        assert database_calls and all(thread_id != loop_thread for thread_id in database_calls)
        assert stack_calls and all(thread_id != loop_thread for thread_id in stack_calls)
        assert len(database_calls) == 1
        assert len(stack_calls) == 1
        assert all(snapshot['settings_checkedout'] == 0 for snapshot in snapshots)
        assert all('anyio_waiting' in snapshot for snapshot in snapshots)
