import asyncio
import logging
import os
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from contracts.runtime import ipc as runtime_ipc
from contracts.runtime.ipc import RuntimeListenerKind
from contracts.runtime_workers.models import RuntimeWorkerKind
from core import build_runs_service as build_run_service
from core import runtime_workers_service as runtime_worker_service
from core.config import settings
from core.database import (
    get_settings_db,
    init_db,
    register_settings_bootstrap_hook,
    register_settings_cache_invalidator,
    run_db,
    run_settings_db,
    supports_distributed_runtime,
)
from core.exceptions import AppError
from core.http import close_clients
from core.logging import RequestLoggingMiddleware, configure_logging
from core.namespace import (
    list_namespaces,
    namespace_paths,
    reset_namespace,
    set_namespace_context,
)
from core.namespaces_service import register_namespace
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlmodel import Session, text

from api import router
from backend_core.error_handlers import (
    app_error_handler,
    generic_error_handler,
    validation_error_handler,
)
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


def _register_api_worker(worker_id: str) -> None:
    def _register(session: Session) -> None:
        runtime_worker_service.register_worker(
            session,
            worker_id=worker_id,
            kind=RuntimeWorkerKind.API,
            hostname=socket.gethostname(),
            pid=os.getpid(),
            capacity=max(settings.worker_connections, 1),
        )

    run_settings_db(_register)


def _heartbeat_api_worker(worker_id: str) -> None:
    def _heartbeat(session: Session) -> None:
        runtime_worker_service.heartbeat_worker(session, worker_id=worker_id)

    run_settings_db(_heartbeat)


def _stop_api_worker(worker_id: str) -> None:
    def _stop(session: Session) -> None:
        runtime_worker_service.mark_worker_stopped(session, worker_id=worker_id)

    run_settings_db(_stop)


# Detect Nuitka compiled binary vs running from source.
# In Nuitka-compiled code, __compiled__ is a C-level built-in constant set to True.
# In a regular Python interpreter it is not defined, raising NameError.
try:
    _NUITKA_COMPILED: bool = __compiled__  # type: ignore[name-defined]  # noqa: F821
except NameError:
    _NUITKA_COMPILED = False

frontend_build_dir = Path(__file__).parent / "frontend" / "build" if _NUITKA_COMPILED else ROOT / "packages" / "frontend" / "build"


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
    if supports_distributed_runtime():
        return workers
    raise RuntimeError("Multiple workers are not supported in the current runtime mode. Set WORKERS=1.")


def _resolve_uvicorn_limit_concurrency() -> int | None:
    if settings.worker_connections > 0:
        return settings.worker_connections
    return None


def _mark_running_builds_orphaned_across_namespaces() -> int:
    namespaces = list_namespaces()
    if not namespaces:
        namespaces = [settings.default_namespace]
    count = 0
    for namespace in namespaces:
        token = set_namespace_context(namespace)
        try:
            count += run_db(build_run_service.mark_running_builds_orphaned)
        finally:
            reset_namespace(token)
    return count


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
            session_store.sweep()
        except Exception as e:
            logger.error("Chat sweep error: %s", e, exc_info=True)


async def api_worker_heartbeat_loop(stop_event: asyncio.Event, worker_id: str, *, heartbeat_seconds: float = 5.0) -> None:
    while not stop_event.is_set():
        if await _wait_until_stopped(stop_event, heartbeat_seconds):
            return
        _heartbeat_api_worker(worker_id)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    configure_logging()
    logger.info("Starting application...")
    api_worker_id = f"api:{os.getpid()}"
    app.state.api_worker_id = api_worker_id
    from backend_core.public_schema import ensure_backend_public_tables
    from modules.auth.service import ensure_default_user

    await asyncio.to_thread(ensure_backend_public_tables)
    await asyncio.to_thread(run_settings_db, ensure_default_user)
    await asyncio.to_thread(_register_api_worker, api_worker_id)
    await asyncio.to_thread(run_db, udf_service.seed_defaults)

    # Start background cleanup task
    stop_event = asyncio.Event()
    ipc_server = await runtime_ipc.start_api_server(listener=RuntimeListenerKind.API)

    chat_sweep_task = asyncio.create_task(chat_sweep_loop(stop_event))
    api_heartbeat_task = asyncio.create_task(api_worker_heartbeat_loop(stop_event, api_worker_id))
    ipc_task = None
    if ipc_server is not None:
        ipc_task = asyncio.create_task(runtime_ipc.serve_api_notifications(ipc_server, stop_event, handle_runtime_payload))

    # Start Telegram bot only if explicitly enabled in settings
    from modules.telegram.bot import telegram_bot

    def _check_bot_enabled(session: Session) -> tuple[bool, str]:
        from backend_core.settings_store import get_resolved_telegram_settings

        del session
        resolved = get_resolved_telegram_settings()
        enabled = bool(resolved.get("enabled"))
        token = str(resolved.get("token", ""))
        return enabled, token

    enabled, token = run_settings_db(_check_bot_enabled)
    if enabled:
        telegram_bot.start(token)

    from modules.mcp.routes import get_registry

    get_registry(app)

    yield

    # Stop Telegram bot
    telegram_bot.stop()

    stop_event.set()
    shutdown_tasks = [chat_sweep_task, api_heartbeat_task]
    if ipc_task is not None:
        shutdown_tasks.append(ipc_task)
    await asyncio.gather(*shutdown_tasks)
    await runtime_ipc.stop_api_server(ipc_server, listener=RuntimeListenerKind.API)
    await close_clients()
    await asyncio.to_thread(_stop_api_worker, api_worker_id)

    logger.info("Application shutdown complete")


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

# Global exception handlers for consistent structured error responses
app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, generic_error_handler)  # type: ignore[arg-type]


@app.middleware("http")
async def namespace_middleware(request: Request, call_next) -> Response:
    raw = request.headers.get("X-Namespace")
    token = set_namespace_context(raw)
    try:
        await asyncio.to_thread(run_settings_db, register_namespace, raw)
        return await call_next(request)
    finally:
        reset_namespace(token)


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=settings.cors_origins_list,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "If-Match",
        "X-Client-Id",
        "X-Namespace",
        "X-Session-Token",
    ],
)


@app.middleware("http")
async def security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if not settings.debug:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


app.add_middleware(RequestLoggingMiddleware)

# Include API Routers (prefix already defined in api/router.py)
app.include_router(router)


@app.get("/", response_model=None)
async def root() -> FileResponse | dict[str, str]:
    index_path = frontend_build_dir / "index.html"

    if settings.prod_mode_enabled and index_path.exists():
        return FileResponse(str(index_path))

    return {"message": "Welcome to Svelte-FastAPI Template"}


# Health Check Endpoints
@app.get("/health")
async def health() -> dict[str, str]:
    """Basic liveness check - returns 200 if app is running."""
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@app.get("/health/ready")
async def readiness(session: Session = Depends(get_settings_db)) -> JSONResponse:
    """Readiness check - verifies app can handle requests.
    Checks database connectivity and filesystem.
    """
    checks = {}
    is_ready = True

    # Check database
    try:
        session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e!s}"
        is_ready = False

    # Check filesystem (data directories)
    try:
        paths = namespace_paths(settings.default_namespace)
        checks["upload_dir"] = "ok" if paths.upload_dir.exists() else "missing"
        checks["clean_dir"] = "ok" if paths.clean_dir.exists() else "missing"
        checks["exports_dir"] = "ok" if paths.exports_dir.exists() else "missing"

        if not all(d.exists() for d in [paths.upload_dir, paths.clean_dir, paths.exports_dir]):
            is_ready = False
    except Exception as e:
        checks["filesystem"] = f"error: {e!s}"
        is_ready = False

    status_code = 200 if is_ready else 503
    return JSONResponse(
        content={"status": "ready" if is_ready else "not_ready", "checks": checks},
        status_code=status_code,
    )


@app.get("/health/startup")
async def startup() -> dict[str, str]:
    """Startup probe - quick check for container startup.
    Returns 200 when app is initialized and ready to accept traffic.
    """
    try:
        _ = settings.app_name
        return {"status": "ready"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/{full_path:path}", include_in_schema=False, response_model=None)
async def serve_static_or_index(full_path: str) -> FileResponse:
    if not settings.prod_mode_enabled:
        logger.info("Frontend build not served (development mode or build missing)")
        raise HTTPException(status_code=404, detail="Frontend build not found")

    if full_path.startswith("api/") or full_path == "api":
        raise HTTPException(status_code=404, detail="Not Found")

    path = frontend_build_dir / full_path
    if path.is_file():
        return FileResponse(str(path))

    fallback_path = frontend_build_dir / "200.html"
    if fallback_path.exists():
        return FileResponse(str(fallback_path))

    index_path = frontend_build_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))

    raise HTTPException(status_code=404, detail="File not found")


if __name__ == "__main__":
    import multiprocessing

    import uvicorn

    workers = _guard_runtime_workers(_resolve_uvicorn_workers())

    # Required for multiprocessing 'spawn' context in frozen (Nuitka onefile) executables.
    multiprocessing.freeze_support()

    # In a Nuitka compiled binary there are no source files for uvicorn to watch,
    # so pass the app object directly and disable hot reload.
    # In source mode, the string form 'main:app' is required for --reload to work.
    uvicorn.run(
        app if _NUITKA_COMPILED else "main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False if _NUITKA_COMPILED else settings.debug,
        workers=workers,
        limit_concurrency=_resolve_uvicorn_limit_concurrency(),
        log_level=settings.log_level,
        access_log=settings.uvicorn_access_log,
    )
