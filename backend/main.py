import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api import router
from core.config import settings
from core.database import get_db, init_db
from modules.compute.manager import get_manager
from modules.udf.seed import ensure_udf_seeds

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

frontend_build_dir = Path(__file__).parent.parent / 'frontend' / 'build'


async def engine_cleanup_loop():
    """Periodically check and clean up idle engines."""
    while True:
        await asyncio.sleep(settings.engine_pooling_interval)
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info('Starting application...')
    await init_db()
    async for session in get_db():
        await ensure_udf_seeds(session)
        break

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
async def readiness(session: AsyncSession = Depends(get_db)):
    """
    Readiness check - verifies app can handle requests.
    Checks database connectivity, engine manager, and filesystem.
    """
    from fastapi.responses import JSONResponse
    from sqlalchemy import text

    checks = {}
    is_ready = True

    # Check database
    try:
        await session.execute(text('SELECT 1'))
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
        checks['upload_dir'] = 'ok' if settings.upload_dir.exists() else 'missing'
        checks['exports_dir'] = 'ok' if settings.exports_dir.exists() else 'missing'

        if not all(d.exists() for d in [settings.upload_dir, settings.exports_dir]):
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

    index_path = frontend_build_dir / 'index.html'
    if index_path.exists():
        return FileResponse(str(index_path))

    raise HTTPException(status_code=404, detail='File not found')


if __name__ == '__main__':
    import uvicorn

    uvicorn.run('main:app', host='0.0.0.0', port=8000, reload=True)
