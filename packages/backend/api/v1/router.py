from typing import Any

from fastapi import APIRouter, Depends
from fastapi.routing import APIWebSocketRoute, iter_route_contexts

from modules.ai import router as ai_router
from modules.analysis.routes import router as analysis_router
from modules.analysis_versions.routes import router as analysis_versions_router
from modules.auth import router as auth_router
from modules.auth.dependencies import get_current_user
from modules.chat import router as chat_router
from modules.compute.routes import router as compute_router
from modules.compute_worker_runs.routes import router as compute_worker_runs_router
from modules.config import router as config_router
from modules.datasource.routes import router as datasource_router
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
        'get_current_user_id',
        'get_lock_owner_id',
        'require_analysis_revision',
        '_require_websocket_user',
    }
)
_PUBLIC_V1_ENDPOINTS = frozenset(
    {
        ('GET', '/v1/config'),
        ('GET', '/v1/config/uuid'),
        ('GET', '/v1/namespaces'),
        ('GET', '/v1/namespaces/storage-plan'),
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
    original_route = getattr(route, 'original_route', route)
    if isinstance(original_route, APIWebSocketRoute):
        effective_route = getattr(route, '_effective_route', None)
        websocket_route = getattr(effective_route, 'starlette_route', None) or original_route
        return _source_mentions_auth(original_route.endpoint) or _dependant_requires_websocket_auth(getattr(websocket_route, 'dependant', None))

    # Router-level auth lives on route.dependencies, not in the dependant tree.
    for dependency in getattr(route, 'dependencies', []):
        call = getattr(dependency, 'call', None) or getattr(dependency, 'dependency', None)
        if getattr(call, '__name__', '') in _AUTH_DEPENDENCY_NAMES:
            return True
    dependant = getattr(route, 'dependant', None)
    if dependant is None:
        return False
    if _dependant_has_auth(dependant):
        return True
    return _source_mentions_auth(dependant.call)


def _dependant_requires_websocket_auth(dependant: Any) -> bool:
    if dependant is None:
        return False
    if getattr(dependant.call, '__name__', '') == '_require_websocket_user':
        return True
    return any(_dependant_requires_websocket_auth(sub) for sub in dependant.dependencies)


def _route_path(route: Any) -> str | None:
    path = route.path
    if path:
        return path
    effective_route = getattr(route, '_effective_route', None)
    return getattr(getattr(effective_route, 'starlette_route', None), 'path', None)


def verify_v1_auth_coverage() -> None:
    """Startup check: every /v1 route must declare authentication explicitly.

    Module routers are individually responsible for their auth semantics (some
    routes are intentionally public). This sweep exists so a future router
    added without any auth dependency fails application startup instead of
    silently serving unauthenticated requests. FastAPI keeps included routers
    as a live route tree, so inspect effective route contexts rather than
    assuming ``router.routes`` is a flattened list.
    """
    unguarded: list[str] = []
    for route in iter_route_contexts(router.routes):
        route_path = _route_path(route)
        if route_path is None:
            raise RuntimeError('API auth audit cannot resolve a path for route ' + str(route.name))
        if route_path == '/v1/auth' or route_path.startswith('/v1/auth/'):
            continue
        methods = frozenset(route.methods or {'WS'})
        if all((method, route_path) in _PUBLIC_V1_ENDPOINTS for method in methods):
            continue
        if _route_has_auth(route):
            continue
        unguarded.append(f'{",".join(sorted(methods))} {route_path}')
    if unguarded:
        raise RuntimeError('API routes without authentication dependencies (fail-closed startup): ' + '; '.join(unguarded))


router = APIRouter(prefix='/v1')

_V1_ROUTER_DEFINITIONS: tuple[tuple[APIRouter, bool], ...] = (
    (ai_router, True),
    (analysis_router, False),
    (analysis_versions_router, False),
    (auth_router, False),
    (chat_router, False),
    (compute_router, False),
    (config_router, False),
    (datasource_router, True),
    (compute_worker_runs_router, True),
    (healthcheck_router, False),
    (logs_router, True),
    (locks_router, False),
    (mcp_router, False),
    (namespaces_router, False),
    (runtime_overview_router, True),
    (settings_router, False),
    (telegram_router, True),
    (udf_router, True),
    (scheduler_router, False),
)


def _include_v1_routers(parent: APIRouter) -> None:
    for module_router, authenticated in _V1_ROUTER_DEFINITIONS:
        if authenticated:
            parent.include_router(module_router, dependencies=[Depends(get_current_user)])
        else:
            parent.include_router(module_router)


_include_v1_routers(router)
