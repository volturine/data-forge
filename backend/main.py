import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlmodel import Session, text

from api import router
from core.config import settings
from core.database import get_db, get_settings_db, init_db
from core.logging import RequestLoggingMiddleware, configure_logging
from core.namespace import list_namespaces, namespace_paths, reset_namespace, set_namespace_context
from modules.compute.manager import get_manager
from modules.scheduler import service as scheduler_service
from modules.udf.seed import ensure_udf_seeds

logger = logging.getLogger(__name__)

frontend_build_dir = Path(__file__).parent.parent / 'frontend' / 'build'


async def engine_cleanup_loop(stop_event: asyncio.Event) -> None:
    """Periodically check and clean up idle engines."""
    while not stop_event.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=settings.engine_pooling_interval)
        if stop_event.is_set():
            break
        try:
            manager = get_manager()
            cleaned = manager.cleanup_idle_engines()
            if cleaned:
                for analysis_id in cleaned:
                    logger.info(f'Cleaned up idle engine {analysis_id}')
            else:
                logger.debug('No idle engines to clean up')
        except Exception as e:
            logger.error(f'Error in engine cleanup: {e}', exc_info=True)


async def scheduler_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=settings.scheduler_check_interval)
        if stop_event.is_set():
            break
        try:
            namespaces = list_namespaces()
            if not namespaces:
                namespaces = [settings.default_namespace]
            for name in namespaces:
                token = set_namespace_context(name)
                try:
                    for session in get_db():
                        due = scheduler_service.get_due_schedules(session)
                        if not due:
                            logger.debug('No schedules due')
                            break

                        # Build a topological order to respect analysis dependencies
                        all_analysis_ids = {str(s.analysis_id) for s in due if s.analysis_id}
                        ordered_ids: list[str] = []
                        for aid in all_analysis_ids:
                            build_order = scheduler_service.get_build_order(session, aid)
                            for oid in build_order:
                                if oid in all_analysis_ids and oid not in ordered_ids:
                                    ordered_ids.append(oid)

                        # Add any remaining IDs not in the build order
                        for aid in all_analysis_ids:
                            if aid not in ordered_ids:
                                ordered_ids.append(aid)

                        # Map schedule by analysis_id for marking
                        schedule_map: dict[str, list] = {}
                        for s in due:
                            if not s.analysis_id:
                                continue
                            schedule_map.setdefault(str(s.analysis_id), []).append(s)

                        # Build schedule-level dependency order within each analysis group.
                        # If schedule B depends_on schedule A, run A before B.
                        due_by_id = {s.id: s for s in due}
                        completed_schedule_ids: set[str] = set()

                        for aid in ordered_ids:
                            logger.info(f'Scheduler: running build for analysis {aid}')
                            schedules_for_aid = schedule_map.get(aid, [])

                            # Topological sort within this analysis's schedules
                            sorted_schedules = _topo_sort_schedules(schedules_for_aid, due_by_id)

                            for sched in sorted_schedules:
                                # If this schedule depends on another schedule that was
                                # due in this batch but has not completed, skip it.
                                if sched.depends_on and sched.depends_on not in completed_schedule_ids and sched.depends_on in due_by_id:
                                    logger.warning(
                                        f'Scheduler: skipping schedule {sched.id} — dependency {sched.depends_on} did not complete'
                                    )
                                    scheduler_service.mark_schedule_run(session, sched.id)
                                    continue

                                try:
                                    result = scheduler_service.run_analysis_build(session, aid, datasource_id=sched.datasource_id)
                                    scheduler_service.mark_schedule_run(session, sched.id)
                                    completed_schedule_ids.add(sched.id)
                                    logger.info(
                                        f'Scheduler: build complete for analysis {aid} '
                                        f'(datasource={sched.datasource_id}) — '
                                        f'{result["tabs_built"]} tab(s) built'
                                    )
                                except Exception as e:
                                    logger.error(f'Scheduler: build failed for analysis {aid}: {e}', exc_info=True)
                                    # Still mark the schedule as run to prevent retry storms
                                    scheduler_service.mark_schedule_run(session, sched.id)
                        break
                finally:
                    reset_namespace(token)
        except Exception as e:
            logger.error(f'Error in scheduler loop: {e}', exc_info=True)


def _topo_sort_schedules(
    schedules: list,
    due_by_id: Mapping[str, object],
) -> list:
    """Sort schedules respecting depends_on within a single batch."""
    id_set = {s.id for s in schedules}
    graph: dict[str, list] = {s.id: [] for s in schedules}
    in_degree: dict[str, int] = {s.id: 0 for s in schedules}

    for s in schedules:
        if s.depends_on and s.depends_on in id_set:
            graph[s.depends_on].append(s.id)
            in_degree[s.id] += 1

    queue = [sid for sid, deg in in_degree.items() if deg == 0]
    ordered: list[str] = []
    while queue:
        node = queue.pop(0)
        ordered.append(node)
        for neighbor in graph.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # Append any remaining (cycle protection)
    for s in schedules:
        if s.id not in ordered:
            ordered.append(s.id)

    by_id = {s.id: s for s in schedules}
    return [by_id[sid] for sid in ordered]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger.info('Starting application...')
    init_db()
    for session in get_db():
        ensure_udf_seeds(session)
        break

    # Start background cleanup task
    stop_event = asyncio.Event()
    cleanup_task = asyncio.create_task(engine_cleanup_loop(stop_event))
    scheduler_task = asyncio.create_task(scheduler_loop(stop_event))

    # Start Telegram bot only if explicitly enabled in settings
    from modules.telegram.bot import telegram_bot

    def _check_bot_enabled(session: Session) -> tuple[bool, str]:
        from modules.settings.models import AppSettings

        row = session.get(AppSettings, 1)
        if row and row.telegram_bot_enabled and row.telegram_bot_token:
            return True, row.telegram_bot_token
        return False, ''

    from core.database import run_db as _run_db

    enabled, token = _run_db(_check_bot_enabled)
    if enabled:
        telegram_bot.start(token)

    yield

    # Stop Telegram bot
    telegram_bot.stop()

    stop_event.set()
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(cleanup_task, timeout=5)
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(scheduler_task, timeout=5)

    # Cleanup compute processes on shutdown
    logger.info('Shutting down compute processes...')
    manager = get_manager()
    manager.shutdown_all()
    logger.info('Application shutdown complete')


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)


@app.middleware('http')
async def namespace_middleware(request: Request, call_next):
    token = set_namespace_context(request.headers.get('X-Namespace'))
    try:
        return await call_next(request)
    finally:
        reset_namespace(token)


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=settings.cors_origins_list,
    allow_methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    allow_headers=['Content-Type', 'Authorization', 'X-Namespace'],
)

app.add_middleware(RequestLoggingMiddleware)

# Include API Routers (prefix already defined in api/router.py)
app.include_router(router, tags=['api'])


@app.get('/')
async def root():
    prod_mode_enabled = os.getenv('PROD_MODE_ENABLED', 'false').lower() in ['true', '1', 'yes']
    index_path = frontend_build_dir / 'index.html'

    if prod_mode_enabled and index_path.exists():
        return FileResponse(str(index_path))

    return {'message': 'Welcome to Svelte-FastAPI Template'}


# Health Check Endpoints
@app.get('/health')
async def health():
    """Basic liveness check - returns 200 if app is running."""
    return {'status': 'healthy', 'service': settings.app_name, 'version': settings.app_version}


@app.get('/health/ready')
def readiness(session: Session = Depends(get_settings_db)):
    """
    Readiness check - verifies app can handle requests.
    Checks database connectivity, engine manager, and filesystem.
    """
    from fastapi.responses import JSONResponse

    checks = {}
    is_ready = True

    # Check database
    try:
        session.execute(text('SELECT 1'))
        checks['database'] = 'ok'
    except Exception as e:
        checks['database'] = f'error: {str(e)}'
        is_ready = False

    # Check engine manager
    try:
        manager = get_manager()
        engine_count = len(manager.list_engines())
        checks['engine_manager'] = 'ok'
        checks['active_engines'] = str(engine_count)
    except Exception as e:
        checks['engine_manager'] = f'error: {str(e)}'
        is_ready = False

    # Check filesystem (data directories)
    try:
        paths = namespace_paths(settings.default_namespace)
        checks['upload_dir'] = 'ok' if paths.upload_dir.exists() else 'missing'
        checks['clean_dir'] = 'ok' if paths.clean_dir.exists() else 'missing'
        checks['exports_dir'] = 'ok' if paths.exports_dir.exists() else 'missing'

        if not all(d.exists() for d in [paths.upload_dir, paths.clean_dir, paths.exports_dir]):
            is_ready = False
    except Exception as e:
        checks['filesystem'] = f'error: {str(e)}'
        is_ready = False

    status_code = 200 if is_ready else 503
    return JSONResponse(content={'status': 'ready' if is_ready else 'not_ready', 'checks': checks}, status_code=status_code)


@app.get('/health/startup')
async def startup():
    """
    Startup probe - quick check for container startup.
    Returns 200 when app is initialized and ready to accept traffic.
    """
    try:
        _ = settings.app_name
        return {'status': 'ready'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@app.get('/{full_path:path}', include_in_schema=False)
async def serve_static_or_index(full_path: str):
    prod_mode_enabled = os.getenv('PROD_MODE_ENABLED', 'false').lower() in ['true', '1', 'yes']
    frontend_build_dir = Path(__file__).parent.parent / 'frontend' / 'build'

    if not prod_mode_enabled:
        logger.info('Frontend build not served (development mode or build missing)')
        raise HTTPException(status_code=404, detail='Frontend build not found')

    if full_path.startswith('api/') or full_path == 'api':
        raise HTTPException(status_code=404, detail='Not Found')

    path = frontend_build_dir / full_path
    if path.is_file():
        return FileResponse(str(path))

    fallback_path = frontend_build_dir / '200.html'
    if fallback_path.exists():
        return FileResponse(str(fallback_path))

    index_path = frontend_build_dir / 'index.html'
    if index_path.exists():
        return FileResponse(str(index_path))

    raise HTTPException(status_code=404, detail='File not found')


if __name__ == '__main__':
    import uvicorn

    uvicorn.run('main:app', host='0.0.0.0', port=8000, reload=True)
