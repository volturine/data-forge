import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api import router
from core.config import settings
from core.database import init_db
from modules.compute.manager import get_manager
from modules.compute.service import cleanup_jobs_for_engine

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


async def engine_cleanup_loop():
    """Periodically clean up idle engines."""
    while True:
        await asyncio.sleep(settings.engine_cleanup_interval)
        try:
            manager = get_manager()
            cleaned = manager.cleanup_idle_engines()
            if cleaned:
                for analysis_id in cleaned:
                    count = cleanup_jobs_for_engine(analysis_id)
                    logger.info(f'Cleaned up engine {analysis_id} and {count} associated jobs')
            else:
                logger.debug('No idle engines to clean up')
        except Exception as e:
            logger.error(f'Error in engine cleanup: {e}', exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info('Starting application...')
    await init_db()

    # Start background cleanup task
    cleanup_task = asyncio.create_task(engine_cleanup_loop())

    yield

    # Cancel cleanup task
    cleanup_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await cleanup_task

    # Cleanup compute processes on shutdown
    logger.info('Shutting down compute processes...')
    manager = get_manager()
    manager.shutdown_all()
    logger.info('Application shutdown complete')


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=settings.cors_origins_list,
    allow_methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    allow_headers=['Content-Type', 'Authorization'],
)

# Include API Routers with /api prefix
app.include_router(router, prefix='/api', tags=['api'])


@app.get('/')
async def root():
    return {'message': 'Welcome to Svelte-FastAPI Template'}


# Health Check Endpoints
@app.get('/health')
async def health():
    """Basic liveness check - returns 200 if app is running."""
    return {'status': 'healthy', 'service': settings.app_name, 'version': settings.app_version}


@app.get('/health/ready')
async def readiness():
    """
    Readiness check - verifies app can handle requests.
    Checks database connectivity, engine manager, and filesystem.
    """
    from core.database import async_session_maker

    checks = {}
    is_ready = True

    # Check database
    try:
        async with async_session_maker() as session:
            await session.execute('SELECT 1')
        checks['database'] = 'ok'
    except Exception as e:
        checks['database'] = f'error: {str(e)}'
        is_ready = False

    # Check engine manager
    try:
        manager = get_manager()
        engine_count = len(manager.list_engines())
        checks['engine_manager'] = 'ok'
        checks['active_engines'] = engine_count
    except Exception as e:
        checks['engine_manager'] = f'error: {str(e)}'
        is_ready = False

    # Check filesystem (data directories)
    try:
        checks['upload_dir'] = 'ok' if settings.upload_dir.exists() else 'missing'
        checks['results_dir'] = 'ok' if settings.results_dir.exists() else 'missing'
        checks['exports_dir'] = 'ok' if settings.exports_dir.exists() else 'missing'

        if not all(d.exists() for d in [settings.upload_dir, settings.results_dir, settings.exports_dir]):
            is_ready = False
    except Exception as e:
        checks['filesystem'] = f'error: {str(e)}'
        is_ready = False

    status_code = 200 if is_ready else 503
    return {'status': 'ready' if is_ready else 'not_ready', 'checks': checks}, status_code


@app.get('/health/startup')
async def startup():
    """
    Startup probe - quick check for container startup.
    Returns 200 when app is initialized and ready to accept traffic.
    """
    try:
        # Just check if we can import and access settings
        _ = settings.app_name
        return {'status': 'started'}
    except Exception as e:
        return {'status': 'starting', 'error': str(e)}, 503


# Mount static files (frontend) - This must be LAST
# Only mount if the frontend build directory exists (for Docker/production deployments)
frontend_build_dir = Path(__file__).parent.parent / 'frontend' / 'build'
if frontend_build_dir.exists():
    logger.info(f'Mounting frontend static files from {frontend_build_dir}')
    app.mount('/', StaticFiles(directory=str(frontend_build_dir), html=True), name='frontend')
else:
    logger.info('Frontend build directory not found, skipping static file serving (development mode)')


if __name__ == '__main__':
    import uvicorn

    uvicorn.run('main:app', host='0.0.0.0', port=8000, reload=True)
