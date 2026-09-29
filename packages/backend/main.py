import asyncio
import logging
import mimetypes
import os
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import anyio.to_thread
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlmodel import Session, text
from starlette.requests import ClientDisconnect

from api import include_api_routes
from backend_core import runtime_ipc
from backend_core.auth_config import settings as auth_settings
from backend_core.compute_response_recovery import response_recovery
from backend_core.config import settings
from backend_core.database import (
    database_pool_snapshot,
    init_db,
    register_settings_bootstrap_hook,
    register_settings_cache_invalidator,
    run_db,
    run_settings_db,
)
from backend_core.error_handlers import (
    app_error_handler,
    client_disconnect_handler,
    generic_error_handler,
    validation_error_handler,
)
from backend_core.exceptions import AppError
from backend_core.http import close_clients
from backend_core.logging import (
    _REQUEST_LOG_EXECUTOR,
    _REQUEST_LOG_WORKERS,
    RequestLoggingMiddleware,
    RequestTimingMiddleware,
    configure_logging_off_loop,
    flush_request_logs,
    shutdown_logging,
)
from backend_core.namespace import namespace_paths, normalize_namespace, reset_namespace, set_namespace_context
from backend_core.namespaces_service import register_namespace
from backend_core.runtime_ipc import RuntimeListenerKind
from backend_core.runtime_notifications import handle_runtime_payload
from backend_core.settings_store import (
    invalidate_resolved_settings_cache,
    seed_settings_from_env,
)
from modules.udf import service as udf_service

register_settings_bootstrap_hook(seed_settings_from_env)
register_settings_cache_invalidator(invalidate_resolved_settings_cache)

ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)

# AnyIO serves synchronous routes; asyncio.to_thread serves blocking calls in
# async routes. Size the latter to one SQLAlchemy pool and keep the implicit
# sync-handler pool small, so async auth/data paths can use the pool's capacity.
_API_BLOCKING_WORKERS = 12
_API_SYNC_HANDLER_WORKERS = 4
_API_DIAGNOSTICS_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='api-diagnostics')
_API_PROCESS_SNAPSHOT_TTL_SECONDS = 1.0
_API_PROCESS_SNAPSHOT_LOCK = threading.Lock()
_api_process_snapshot_cache: tuple[float, dict[str, object]] | None = None
_api_process_snapshot_refreshing = False


def _api_thread_budget() -> tuple[int, int]:
    """Return bounded asyncio and AnyIO worker counts for one API process.

    Most request paths are async and explicitly offload synchronous database
    work through ``asyncio.to_thread``. Each SQLAlchemy engine has its own
    bounded pool; the default executor can use one pool's capacity, while
    synchronous FastAPI handlers retain a separate small AnyIO allowance.
    """
    database_capacity = max(settings.database_pool_size + settings.database_max_overflow, 1)
    connection_limit = settings.worker_connections if settings.worker_connections > 0 else database_capacity
    request_capacity = min(connection_limit, database_capacity)
    blocking_workers = min(_API_BLOCKING_WORKERS, request_capacity)
    sync_workers = min(_API_SYNC_HANDLER_WORKERS, request_capacity)
    return blocking_workers, sync_workers


def _new_api_blocking_executor(workers: int | None = None) -> ThreadPoolExecutor:
    # ``asyncio.to_thread`` is used for short database, object-store, and
    # filesystem operations throughout the async API routes. The default
    # executor is based on host CPU count, not application capacity; in a
    # container with many visible CPUs that creates a large GIL/database
    # burst for a few dozen browser tabs. Keep one bounded budget for those
    # operations and let the async request tasks absorb the rest.
    #
    # Create this per event loop. TestClient and development reloads close
    # their loop, which also shuts down its default executor; a process-global
    # executor would then be reused after shutdown by the next lifespan.
    return ThreadPoolExecutor(
        max_workers=_api_thread_budget()[0] if workers is None else workers,
        thread_name_prefix='api-blocking',
    )


async def _prewarm_executor(executor: ThreadPoolExecutor, workers: int) -> None:
    """Start a bounded executor's threads before the API accepts traffic."""
    if workers <= 0:
        return
    if workers > executor._max_workers:
        raise ValueError(f'Cannot prewarm {workers} threads in an executor capped at {executor._max_workers}')
    barrier = threading.Barrier(workers)
    loop = asyncio.get_running_loop()
    await asyncio.gather(*(loop.run_in_executor(executor, barrier.wait, 10.0) for _ in range(workers)))


async def _prewarm_anyio_thread_pool(workers: int) -> int:
    """Start AnyIO's synchronous-handler threads before accepting traffic."""
    if workers <= 0:
        return 0

    limiter = anyio.to_thread.current_default_thread_limiter()
    if workers > limiter.total_tokens:
        raise ValueError(f'Cannot prewarm {workers} AnyIO threads with a {limiter.total_tokens}-token limiter')

    barrier = threading.Barrier(workers, timeout=10.0)
    thread_ids: set[int] = set()
    thread_ids_lock = threading.Lock()

    def occupy_thread() -> None:
        with thread_ids_lock:
            thread_ids.add(threading.get_ident())
        barrier.wait()

    await asyncio.gather(*(anyio.to_thread.run_sync(occupy_thread) for _ in range(workers)))
    return len(thread_ids)


def _api_thread_snapshot() -> dict[str, object]:
    """Inspect API worker stacks; called only on the diagnostics executor."""
    frames = sys._current_frames()
    active_threads: list[str] = []
    for thread in threading.enumerate():
        if thread.ident is None or not (thread.name == 'AnyIO worker thread' or thread.name.startswith('api-blocking_')):
            continue
        frame = frames.get(thread.ident)
        while frame is not None:
            filename = frame.f_code.co_filename.replace('\\', '/')
            if '/packages/backend/' in filename and '/.venv/' not in filename:
                active_threads.append(f'{thread.name}:{filename.rsplit("/", 1)[-1]}:{frame.f_lineno}:{frame.f_code.co_name}')
                break
            frame = frame.f_back
    return {'api_blocking_threads': active_threads[:16]}


def _api_process_snapshot() -> dict[str, object]:
    """Coalesce stack-walking diagnostics across concurrent slow requests."""
    global _api_process_snapshot_cache
    snapshot = database_pool_snapshot()
    snapshot.update(_api_thread_snapshot())
    with _API_PROCESS_SNAPSHOT_LOCK:
        _api_process_snapshot_cache = (time.monotonic(), snapshot)
    return dict(snapshot)


def _schedule_api_process_snapshot_refresh() -> None:
    global _api_process_snapshot_refreshing
    with _API_PROCESS_SNAPSHOT_LOCK:
        if _api_process_snapshot_refreshing:
            return
        _api_process_snapshot_refreshing = True

    try:
        future = _API_DIAGNOSTICS_EXECUTOR.submit(_api_process_snapshot)
    except Exception:
        with _API_PROCESS_SNAPSHOT_LOCK:
            _api_process_snapshot_refreshing = False
        logger.warning('Could not schedule API diagnostics snapshot', exc_info=True)
        return

    def finish_refresh(completed) -> None:
        global _api_process_snapshot_refreshing
        try:
            completed.result()
        except Exception:
            logger.warning('API diagnostics snapshot failed', exc_info=True)
        finally:
            with _API_PROCESS_SNAPSHOT_LOCK:
                _api_process_snapshot_refreshing = False

    future.add_done_callback(finish_refresh)


_READINESS_EXECUTOR = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix='readiness-probe',
)
_EVENT_LOOP_LAG_INTERVAL_SECONDS = 0.25
_EVENT_LOOP_LAG_WARN_SECONDS = 0.5
_EVENT_LOOP_BLOCK_SAMPLE_SECONDS = 0.1


class EventLoopBlockWatchdog:
    """Capture the API thread's stack when it stops servicing the loop.

    ``asyncio`` can report which tasks were waiting after a stall, but it cannot
    show the synchronous call that prevented the loop from running. A tiny
    daemon sampler fills that gap without adding work to the API loop. It logs
    once per distinct stall; normal scheduling and short executor waits are
    invisible.
    """

    def __init__(
        self,
        *,
        warning_seconds: float = _EVENT_LOOP_LAG_WARN_SECONDS,
        sample_seconds: float = _EVENT_LOOP_BLOCK_SAMPLE_SECONDS,
    ) -> None:
        self._warning_seconds = max(float(warning_seconds), 0.05)
        self._sample_seconds = max(float(sample_seconds), 0.05)
        self._stop_event = threading.Event()
        self._loop_thread_id: int | None = None
        self._last_tick = time.monotonic()
        self._reported_tick: float | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._loop_thread_id = threading.get_ident()
        self._last_tick = time.monotonic()
        self._thread = threading.Thread(target=self._run, name='api-event-loop-watchdog', daemon=True)
        self._thread.start()

    def tick(self) -> None:
        self._last_tick = time.monotonic()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=max(self._sample_seconds * 2, 0.2))

    def _run(self) -> None:
        while not self._stop_event.wait(self._sample_seconds):
            last_tick = self._last_tick
            if time.monotonic() - last_tick < self._warning_seconds or last_tick == self._reported_tick:
                continue
            self._reported_tick = last_tick
            thread_id = self._loop_thread_id
            frame = sys._current_frames().get(thread_id) if thread_id is not None else None
            stack = '-'
            if frame is not None:
                stack = ' | '.join(line.strip() for line in traceback.format_stack(frame, limit=12))
            logger.warning(
                'API event loop blocked pid=%s lag_ms=%.1f thread_id=%s stack=%s',
                os.getpid(),
                max(0.0, time.monotonic() - last_tick) * 1000,
                thread_id,
                stack,
            )


async def _run_namespace_middleware[T](function, *args, **kwargs) -> T:
    return await asyncio.to_thread(function, *args, **kwargs)


frontend_build_dir = ROOT / 'packages' / 'frontend' / 'build'

# The API image also serves the prerendered SPA.  Keep the small, immutable
# build in memory so a burst of browser navigations does not consume the
# shared threadpool on one FileResponse stat/open/send cycle per asset.
_FRONTEND_ASSET_CACHE: dict[str, tuple[bytes, str | None]] = {}
_FRONTEND_ASSET_CACHE_ROOT: Path | None = None
_FRONTEND_ASSET_CACHE_SOURCE: Path | None = None


def _load_frontend_asset_cache() -> None:
    global _FRONTEND_ASSET_CACHE_ROOT, _FRONTEND_ASSET_CACHE_SOURCE

    root = frontend_build_dir.resolve()
    assets: dict[str, tuple[bytes, str | None]] = {}
    if settings.prod_mode_enabled and root.is_dir():
        for path in root.rglob('*'):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            assets[relative] = (path.read_bytes(), mimetypes.guess_type(path.name)[0])

    _FRONTEND_ASSET_CACHE_ROOT = root
    _FRONTEND_ASSET_CACHE_SOURCE = frontend_build_dir
    _FRONTEND_ASSET_CACHE.clear()
    _FRONTEND_ASSET_CACHE.update(assets)
    logger.info('Loaded %s frontend assets into memory', len(assets))


def _cached_frontend_response(relative_path: str) -> Response | None:
    # The asset root is resolved once during lifespan startup. Resolving it on
    # every async request performs a synchronous filesystem call on Uvicorn's
    # event loop during a browser navigation burst.
    if _FRONTEND_ASSET_CACHE_ROOT is None or frontend_build_dir != _FRONTEND_ASSET_CACHE_SOURCE:
        return None
    cached = _FRONTEND_ASSET_CACHE.get(relative_path)
    if cached is None:
        return None
    content, media_type = cached
    headers = {'Cache-Control': 'public, max-age=31536000, immutable'} if relative_path.startswith('_app/') else {'Cache-Control': 'no-cache'}
    return Response(content=content, media_type=media_type, headers=headers)


def _resolve_uvicorn_workers() -> int:
    if settings.debug:
        return 1
    if settings.workers > 0:
        return settings.workers
    cores = os.cpu_count() or 1
    return max(1, (2 * cores) + 1)


def _guard_runtime_workers(workers: int) -> int:
    if workers <= 1:
        return workers
    if settings.distributed_runtime_enabled and settings.runtime_coordinator_target.strip():
        return workers
    raise RuntimeError(
        'Multiple workers require DISTRIBUTED_RUNTIME_ENABLED=true, RUNTIME_COORDINATOR_TARGET, '
        'and a dedicated runtime_coordinator.py process; '
        'the API workers must not own runtime gRPC or lifecycle state.'
    )


def _resolve_uvicorn_limit_concurrency() -> int | None:
    if settings.worker_connections > 0:
        return settings.worker_connections
    return None


def _configure_sync_thread_capacity() -> int:
    """Align AnyIO's sync-handler limiter with the API DB-work budget.

    Starlette runs synchronous route handlers and ``run_in_threadpool`` calls
    through AnyIO's default limiter, which is 40 tokens regardless of
    ``WORKER_CONNECTIONS``. Bound it together with the asyncio default
    executor; both can run synchronous DB work, so neither consumes the full
    database pool independently.
    """
    _blocking_workers, target = _api_thread_budget()
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = target
    return int(limiter.total_tokens)


async def _provision_default_namespace_credentials() -> None:
    """Ensure the default namespace has engine credentials at startup.

    The object store may still be coming up during a cold container start,
    so retry briefly before failing the launch.
    """
    from backend_core.namespace_credentials_service import NamespaceCredentialError, provision_namespace_engine_credentials

    attempts = 5
    for attempt in range(1, attempts + 1):
        try:
            await asyncio.to_thread(run_settings_db, provision_namespace_engine_credentials, settings.default_namespace)
            return
        except NamespaceCredentialError:
            if attempt == attempts:
                raise
            await asyncio.sleep(2.0)


async def _wait_until_stopped(stop_event: asyncio.Event, delay_seconds: float) -> bool:
    stop_task = asyncio.create_task(stop_event.wait())
    delay_task = asyncio.create_task(asyncio.sleep(delay_seconds))
    done, pending = await asyncio.wait({stop_task, delay_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    return stop_task in done


async def chat_sweep_loop(stop_event: asyncio.Event) -> None:
    """Periodically sweep expired chat sessions."""
    from modules.chat.sessions import session_store

    while not stop_event.is_set():
        if await _wait_until_stopped(stop_event, 300):
            break
        try:
            await asyncio.to_thread(session_store.sweep)
        except Exception as e:
            logger.error('Chat sweep error: %s', e, exc_info=True)


async def event_loop_lag_loop(
    stop_event: asyncio.Event,
    *,
    interval_seconds: float = _EVENT_LOOP_LAG_INTERVAL_SECONDS,
    warning_seconds: float = _EVENT_LOOP_LAG_WARN_SECONDS,
    watchdog: EventLoopBlockWatchdog | None = None,
) -> None:
    """Log event-loop stalls that can trip Uvicorn's child health ping."""
    loop = asyncio.get_running_loop()
    interval = max(float(interval_seconds), 0.05)
    warning = max(float(warning_seconds), interval)
    while not stop_event.is_set():
        try:
            if watchdog is not None:
                watchdog.tick()
            started = loop.time()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            lag = max(0.0, loop.time() - started - interval)
            if lag >= warning:
                logger.warning(
                    'API event loop lag detected pid=%s lag_ms=%.1f interval_ms=%.1f',
                    os.getpid(),
                    lag * 1000,
                    interval * 1000,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            # Diagnostics must never silently disappear after one unusual task
            # state (for example a task finishing between all_tasks() and
            # get_stack()). Keep the monitor alive and let the next interval
            # produce a fresh signal.
            logger.exception('API event-loop lag monitor iteration failed')
            await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Validate the external coordinator contract here rather than only in the
    # __main__ block: launching via `uvicorn main:app --workers N` bypasses
    # __main__ entirely.
    _guard_runtime_workers(_resolve_uvicorn_workers())
    sync_handler_workers = _configure_sync_thread_capacity()
    # ``asyncio.to_thread`` otherwise creates a host-sized default executor.
    # Use the same bounded budget as synchronous route handlers so durable
    # request polling, object-store work, and filesystem cleanup cannot create
    # an unbounded second control plane beside AnyIO's limiter.
    loop = asyncio.get_running_loop()
    api_blocking_workers, _ = _api_thread_budget()
    api_blocking_executor = _new_api_blocking_executor(api_blocking_workers)
    loop.set_default_executor(api_blocking_executor)
    # ThreadPoolExecutor creates threads on its first submissions. Doing that
    # lazily during a burst blocks the submitting event loop in Thread.start().
    # Prime the request-path pools while startup is still closed to traffic.
    from backend_core.websocket import _WEBSOCKET_SERIALIZATION_EXECUTOR
    from modules.compute.executor_client import _COMPUTE_SERIALIZATION_EXECUTOR

    request_log_prewarm = _prewarm_executor(_REQUEST_LOG_EXECUTOR, _REQUEST_LOG_WORKERS) if settings.log_requests_enabled else asyncio.sleep(0)

    await asyncio.gather(
        _prewarm_executor(api_blocking_executor, api_blocking_workers),
        _prewarm_executor(_API_DIAGNOSTICS_EXECUTOR, 1),
        _prewarm_executor(_READINESS_EXECUTOR, 1),
        _prewarm_executor(_COMPUTE_SERIALIZATION_EXECUTOR, 4),
        _prewarm_executor(_WEBSOCKET_SERIALIZATION_EXECUTOR, 2),
        request_log_prewarm,
    )
    # Fail closed at boot if any /v1 route was added without authentication.
    from api.v1.router import verify_v1_auth_coverage

    verify_v1_auth_coverage()
    # A production deployment silently writing uploads to /tmp is never correct.
    if settings.prod_mode_enabled and str(settings.data_dir).startswith(tempfile.gettempdir()):
        raise RuntimeError('DATA_DIR must be set to a persistent location in production')
    await init_db()
    # Frontend asset serving is on the API process in the containerized
    # deployment. Load it before accepting requests so the first browser burst
    # cannot serialize on filesystem access or the default AnyIO threadpool.
    await asyncio.to_thread(_load_frontend_asset_cache)
    await configure_logging_off_loop()
    logger.info('Starting application...')
    # This is an observability identity only. API children do not register as
    # runtime workers and never own runtime leases, gRPC listeners, or engine
    # lifecycle state.
    app.state.api_worker_id = f'api:{os.getpid()}'
    from backend_core.public_schema import ensure_backend_public_tables
    from modules.auth.service import ensure_default_user

    await asyncio.to_thread(ensure_backend_public_tables)
    await asyncio.to_thread(run_settings_db, ensure_default_user)
    await _provision_default_namespace_credentials()
    await asyncio.to_thread(run_db, udf_service.seed_defaults)

    # Start background cleanup task
    stop_event = asyncio.Event()
    event_loop_watchdog = EventLoopBlockWatchdog()
    event_loop_watchdog.start()
    ipc_server = await runtime_ipc.start_api_server(listener=RuntimeListenerKind.API)

    chat_sweep_task = asyncio.create_task(chat_sweep_loop(stop_event))
    event_loop_lag_task = asyncio.create_task(
        event_loop_lag_loop(stop_event, watchdog=event_loop_watchdog),
        name='api-event-loop-lag',
    )
    compute_response_recovery_task = asyncio.create_task(response_recovery.run(stop_event))
    ipc_task = asyncio.create_task(runtime_ipc.serve_api_notifications(ipc_server, stop_event, handle_runtime_payload))

    # Start Telegram bot only if explicitly enabled in settings
    from modules.telegram.bot import telegram_bot

    def _check_bot_enabled(session: Session) -> tuple[bool, str]:
        from backend_core.settings_store import get_resolved_telegram_settings

        del session
        resolved = get_resolved_telegram_settings()
        enabled = bool(resolved.get('enabled'))
        token = str(resolved.get('token', ''))
        return enabled, token

    enabled, token = await asyncio.to_thread(run_settings_db, _check_bot_enabled)
    if enabled:
        telegram_bot.start(token)

    from modules.mcp.routes import get_registry

    await asyncio.to_thread(get_registry, app)
    warmed_anyio_threads = await _prewarm_anyio_thread_pool(sync_handler_workers)
    logger.info('Prewarmed AnyIO synchronous-handler threads=%s', warmed_anyio_threads)

    try:
        yield
    finally:
        try:
            telegram_bot.stop()
        finally:
            stop_event.set()
            event_loop_watchdog.stop()
            shutdown_tasks = [
                chat_sweep_task,
                event_loop_lag_task,
                compute_response_recovery_task,
                ipc_task,
            ]
            try:
                await asyncio.gather(*shutdown_tasks)
                await runtime_ipc.stop_api_server(ipc_server, listener=RuntimeListenerKind.API)
                await close_clients()
            finally:
                logger.info('Application shutdown complete')
                await asyncio.to_thread(flush_request_logs)
                await asyncio.to_thread(shutdown_logging)


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

# Global exception handlers for consistent structured error responses
app.add_exception_handler(AppError, cast(Any, app_error_handler))
app.add_exception_handler(RequestValidationError, cast(Any, validation_error_handler))
app.add_exception_handler(ClientDisconnect, cast(Any, client_disconnect_handler))
app.add_exception_handler(Exception, generic_error_handler)

# Namespaces already known to this process; avoids a DB roundtrip per request.
_KNOWN_NAMESPACES: set[str] = set()

_ASGIScope = MutableMapping[str, Any]
_ASGIReceive = Callable[[], Awaitable[dict[str, Any]]]
_ASGISend = Callable[[dict[str, Any]], Awaitable[None]]
_ASGIApp = Callable[[_ASGIScope, _ASGIReceive, _ASGISend], Awaitable[None]]


def _namespace_registered(session: Session, name: str) -> bool:
    if name == settings.default_namespace:
        return True
    from backend_core.persistence.namespaces.models import RuntimeNamespace

    return session.get(RuntimeNamespace, name) is not None


def _has_valid_session(request: Request) -> bool:
    from modules.auth.service import validate_session

    token = request.cookies.get('session_token') or request.headers.get('X-Session-Token')
    if not token:
        return False

    def _check(session: Session) -> bool:
        return validate_session(session, token) is not None

    return run_settings_db(_check)


def _scope_header(scope: _ASGIScope, name: bytes) -> str | None:
    for header_name, header_value in scope.get('headers', []):
        if header_name.lower() == name:
            return header_value.decode('latin-1')
    return None


class NamespaceMiddleware:
    """Select a tenant without allocating a Starlette BaseHTTPMiddleware task."""

    def __init__(self, app: _ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: _ASGIScope, receive: _ASGIReceive, send: _ASGISend) -> None:
        if scope.get('type') != 'http':
            await self.app(scope, receive, send)
            return

        # Namespace selection belongs to API calls. Frontend documents/assets
        # and health probes are process-global and must not pay for a settings
        # database lookup during a browser cold-start burst.
        path = str(scope.get('path', ''))
        is_api_request = path == '/api' or path.startswith('/api/')
        is_health_request = path == '/health' or path.startswith('/health/')
        if not is_api_request and not is_health_request:
            await self.app(scope, receive, send)
            return
        # Authentication and public configuration are control-plane endpoints.
        # They remain available while tenant data requests are busy.
        if path == '/api/v1/config' or path.startswith('/api/v1/auth/'):
            await self.app(scope, receive, send)
            return

        raw = _scope_header(scope, b'x-namespace')
        token = set_namespace_context(raw)
        try:
            if not auth_settings.auth_required:
                await _run_namespace_middleware(run_settings_db, register_namespace, raw)
                await self.app(scope, receive, send)
                return
            normalized = normalize_namespace(raw)
            known = normalized == settings.default_namespace or normalized in _KNOWN_NAMESPACES
            if not known:
                known = await _run_namespace_middleware(run_settings_db, _namespace_registered, normalized)
                if known:
                    _KNOWN_NAMESPACES.add(normalized)
            request = Request(scope, receive)
            if not known and not await _run_namespace_middleware(_has_valid_session, request):
                await JSONResponse(status_code=403, content={'detail': f'Unknown namespace: {normalized}'})(scope, receive, send)
                return
            if not known:
                await _run_namespace_middleware(run_settings_db, register_namespace, raw)
                _KNOWN_NAMESPACES.add(normalized)
            await self.app(scope, receive, send)
        finally:
            reset_namespace(token)


app.add_middleware(NamespaceMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=settings.cors_origins_list,
    allow_methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    allow_headers=[
        'Content-Type',
        'Authorization',
        'If-Match',
        'X-Client-Id',
        'X-Namespace',
        'X-Session-Token',
    ],
)


class SecurityHeadersMiddleware:
    """Add response headers without the task-heavy BaseHTTPMiddleware adapter."""

    def __init__(self, app: _ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: _ASGIScope, receive: _ASGIReceive, send: _ASGISend) -> None:
        if scope.get('type') != 'http':
            await self.app(scope, receive, send)
            return

        values = {
            b'x-content-type-options': b'nosniff',
            b'x-frame-options': b'DENY',
            b'x-xss-protection': b'0',
            b'referrer-policy': b'strict-origin-when-cross-origin',
            b'permissions-policy': b'camera=(), microphone=(), geolocation=()',
        }
        if not settings.debug:
            values[b'strict-transport-security'] = b'max-age=63072000; includeSubDomains'

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message.get('type') != 'http.response.start':
                await send(message)
                return
            headers = [(name, value) for name, value in message.get('headers', []) if name.lower() not in values]
            headers.extend(values.items())
            await send({**message, 'headers': headers})

        await self.app(scope, receive, send_with_headers)


app.add_middleware(SecurityHeadersMiddleware)


if settings.log_requests_enabled:
    app.add_middleware(RequestLoggingMiddleware)


async def _api_observability_snapshot() -> dict[str, object]:
    limiter = anyio.to_thread.current_default_thread_limiter()
    statistics = limiter.statistics()
    with _API_PROCESS_SNAPSHOT_LOCK:
        cached = _api_process_snapshot_cache
    if cached is None or time.monotonic() - cached[0] >= _API_PROCESS_SNAPSHOT_TTL_SECONDS:
        _schedule_api_process_snapshot_refresh()
    snapshot = {} if cached is None else dict(cached[1])
    snapshot.update(
        {
            'anyio_tokens': statistics.total_tokens,
            'anyio_borrowed': statistics.borrowed_tokens,
            'anyio_waiting': statistics.tasks_waiting,
        }
    )
    return snapshot


app.add_middleware(
    RequestTimingMiddleware,
    slow_request_seconds=5.0,
    pool_snapshot=_api_observability_snapshot,
)

# Register the API modules directly to avoid redundant preserved router levels.
include_api_routes(app)


@app.get('/', response_model=None)
async def root() -> Response | dict[str, str]:
    index_path = frontend_build_dir / 'index.html'

    if settings.prod_mode_enabled:
        cached = _cached_frontend_response('index.html')
        if cached is not None:
            return cached
        if await asyncio.to_thread(index_path.is_file):
            return FileResponse(str(index_path))

    return {
        'message': settings.app_name,
        'version': settings.app_version,
        'docs': '/docs',
    }


# Health Check Endpoints
@app.get('/health')
async def health() -> dict[str, str]:
    """Basic liveness check - returns 200 if app is running."""
    return {
        'status': 'healthy',
        'service': settings.app_name,
        'version': settings.app_version,
    }


def _readiness_checks() -> tuple[dict[str, str], bool]:
    """Run blocking readiness checks outside both the event loop and AnyIO pool."""
    checks = {}
    is_ready = True

    # Check database
    try:
        run_settings_db(lambda session: session.execute(text('SELECT 1')))
        checks['database'] = 'ok'
    except Exception as e:
        logger.warning('Database readiness check failed: %s', e)
        checks['database'] = 'error'
        is_ready = False

    # Local DATA_DIR remains for process-local scratch; product data lives in object storage.
    try:
        paths = namespace_paths(settings.default_namespace)
        checks['data_dir'] = 'ok' if paths.base_dir.exists() else 'missing'
        if not paths.base_dir.exists():
            is_ready = False
    except Exception as e:
        logger.warning('Data dir readiness check failed: %s', e)
        checks['data_dir'] = 'error'
        is_ready = False

    # Fail fast when the S3-compatible object store is unreachable or misconfigured.
    # Probes the store directly (not via the worker data plane) so API readiness
    # does not depend on workers having started yet.
    try:
        from backend_core.object_store_probe import probe_object_store

        probe_object_store(namespace=settings.default_namespace)
        checks['object_store'] = 'ok'
    except Exception as e:
        checks['object_store'] = f'error: {e!s}'
        is_ready = False

    return checks, is_ready


@app.get('/health/ready')
async def readiness() -> JSONResponse:
    """Readiness check - verifies app can handle requests.

    The database and object-store probes are deliberately isolated in a
    single executor. Health-check bursts therefore cannot occupy the shared
    AnyIO worker pool used by sync dependencies and routes.
    """
    loop = asyncio.get_running_loop()
    checks, is_ready = await loop.run_in_executor(_READINESS_EXECUTOR, _readiness_checks)
    status_code = 200 if is_ready else 503
    return JSONResponse(
        content={'status': 'ready' if is_ready else 'not_ready', 'checks': checks},
        status_code=status_code,
    )


@app.get('/health/startup')
async def startup() -> dict[str, str]:
    """Startup probe - quick check for container startup.
    Returns 200 when app is initialized and ready to accept traffic.
    """
    try:
        _ = settings.app_name
        return {'status': 'ready'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@app.get('/{full_path:path}', include_in_schema=False, response_model=None)
async def serve_static_or_index(full_path: str) -> Response:
    if not settings.prod_mode_enabled:
        logger.info('Frontend build not served (development mode or build missing)')
        raise HTTPException(status_code=404, detail='Frontend build not found')

    if full_path.startswith('api/') or full_path == 'api':
        raise HTTPException(status_code=404, detail='Not Found')

    # Production assets are loaded into memory during lifespan startup. Keep
    # the hot path entirely in memory; only the cold fallback below touches the
    # filesystem. Reject traversal before constructing a fallback path.
    relative_path = full_path.strip('/')
    if any(part in {'', '.', '..'} for part in relative_path.split('/')):
        raise HTTPException(status_code=404, detail='File not found')
    cached = _cached_frontend_response(relative_path)
    if cached is not None:
        return cached

    # adapter-static emits prerendered route documents as extensionless
    # ``<route>.html`` files. Resolve those before falling back to 200.html;
    # otherwise direct navigation to an auth route renders the empty SPA shell.
    if relative_path and not relative_path.endswith('.html'):
        cached = _cached_frontend_response(f'{relative_path}.html')
        if cached is not None:
            return cached
        prerendered_path = frontend_build_dir / f'{relative_path}.html'
        if await asyncio.to_thread(prerendered_path.is_file):
            return FileResponse(str(prerendered_path))

    # This branch is only for tests/development or a cache miss after a
    # filesystem change. It is intentionally not part of the normal E2E path.
    path = frontend_build_dir / relative_path
    if await asyncio.to_thread(path.is_file):
        return FileResponse(str(path))

    fallback_path = frontend_build_dir / '200.html'
    if await asyncio.to_thread(fallback_path.is_file):
        cached = _cached_frontend_response('200.html')
        if cached is not None:
            return cached
        return FileResponse(str(fallback_path))

    index_path = frontend_build_dir / 'index.html'
    if await asyncio.to_thread(index_path.is_file):
        cached = _cached_frontend_response('index.html')
        if cached is not None:
            return cached
        return FileResponse(str(index_path))

    raise HTTPException(status_code=404, detail='File not found')


def _run_api_server() -> None:
    import uvicorn

    workers = _guard_runtime_workers(_resolve_uvicorn_workers())

    # String form 'main:app' is required for --reload to work.
    uvicorn.run(
        'main:app',
        host=os.environ.get('HOST', '0.0.0.0'),
        port=settings.port,
        reload=settings.debug,
        workers=workers,
        limit_concurrency=_resolve_uvicorn_limit_concurrency(),
        log_level=settings.log_level,
        access_log=settings.uvicorn_access_log,
        # The API's WebSockets carry small JSON control/status messages.
        # Uvicorn's per-message deflate decode is synchronous on the API loop;
        # the 50-tab trace showed it blocking that loop under concurrent frames.
        ws_per_message_deflate=False,
    )


if __name__ == '__main__':
    _run_api_server()
