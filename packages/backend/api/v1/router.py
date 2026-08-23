from typing import Any

from fastapi import APIRouter

from modules.ai import router as ai_router
from modules.analysis.routes import router as analysis_router
from modules.analysis_versions.routes import router as analysis_versions_router
from modules.auth import router as auth_router
from modules.chat import router as chat_router
from modules.compute.routes import router as compute_router
from modules.config import router as config_router
from modules.datasource.routes import router as datasource_router
from modules.engine_runs.routes import router as engine_runs_router
from modules.healthcheck import router as healthcheck_router
from modules.locks import router as locks_router
from modules.logs import router as logs_router
from modules.mcp.routes import router as mcp_router
from modules.namespaces import router as namespaces_router
from modules.runtime_overview import router as runtime_overview_router
from modules.scheduler import router as scheduler_router
from modules.settings import router as settings_router
from modules.telegram import router as telegram_router
from modules.udf import router as udf_router

_AUTH_DEPENDENCY_NAMES = frozenset(
    {
        'get_current_user',
        'get_optional_user',
        'get_current_user_id',
        'get_optional_user_id',
        'require_analysis_revision',
        '_require_websocket_user',
    }
)


def _dependant_has_auth(dependant: Any) -> bool:
    if getattr(dependant.call, '__name__', '') in _AUTH_DEPENDENCY_NAMES:
        return True
    return any(_dependant_has_auth(sub) for sub in dependant.dependencies)


def _source_mentions_auth(call: Any) -> bool:
    try:
        import inspect

        source = inspect.getsource(call)
    except OSError, TypeError:
        return False
    return any(marker in source for marker in ('_require_websocket_user', 'get_current_user'))


def _route_has_auth(route: Any) -> bool:
    # Router-level auth lives on route.dependencies, not in the dependant tree.
    for dependency in getattr(route, 'dependencies', []):
        call = getattr(dependency, 'call', None) or getattr(dependency, 'dependency', None)
        if getattr(call, '__name__', '') in _AUTH_DEPENDENCY_NAMES:
            return True
    dependant = getattr(route, 'dependant', None)
    if dependant is None:
        return True
    if _dependant_has_auth(dependant):
        return True
    # Websocket handlers enforce auth inside the handler body.
    return _source_mentions_auth(dependant.call)


def verify_v1_auth_coverage() -> None:
    """Startup check: every /v1 route must declare authentication explicitly.

    Module routers are individually responsible for their auth semantics (some
    routes are intentionally public). This sweep exists so a future router
    added without any auth dependency fails application startup instead of
    silently serving unauthenticated requests.
    """
    unguarded: list[str] = []
    for route in router.routes:
        route_path = getattr(route, 'path', None)
        if route_path is None or '/auth/' in route_path:
            continue
        if not getattr(route, 'dependant', None):
            continue
        if _route_has_auth(route):
            continue
            methods = ','.join(sorted(getattr(route, 'methods', []) or ['WS']))
            unguarded.append(f'{methods} {route_path}')
    if unguarded:
        raise RuntimeError('API routes without authentication dependencies (fail-closed startup): ' + '; '.join(unguarded))


router = APIRouter(prefix='/v1')


router.include_router(ai_router)
router.include_router(analysis_router)
router.include_router(analysis_versions_router)
router.include_router(auth_router)
router.include_router(chat_router)
router.include_router(compute_router)
router.include_router(config_router)
router.include_router(datasource_router)
router.include_router(engine_runs_router)
router.include_router(healthcheck_router)
router.include_router(logs_router)
router.include_router(locks_router)
router.include_router(mcp_router)
router.include_router(namespaces_router)
router.include_router(runtime_overview_router)
router.include_router(settings_router)
router.include_router(telegram_router)
router.include_router(udf_router)
router.include_router(scheduler_router)
