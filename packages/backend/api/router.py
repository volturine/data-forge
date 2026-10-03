from typing import cast

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute, iter_route_contexts
from starlette.routing import BaseRoute, Match

from .v1.router import router as v1_router

router = APIRouter(prefix='/api')
router.include_router(v1_router)


_DISPATCH_TARGET_SCOPE_KEY = 'dataforge.route_dispatch_target'
_ROUTE_PREFIX_SEGMENTS = 3


class _ApiRouteDispatcher(BaseRoute):
    """Dispatch by path prefix while leaving FastAPI's flat routes inspectable."""

    path = None
    name = 'api-route-dispatcher'
    methods = None

    def __init__(self, routes: list[BaseRoute]) -> None:
        self._route_registry = routes
        self._indexed_route_count = -1
        self._groups: dict[tuple[str, ...], list[tuple[int, BaseRoute]]] = {}
        self._fallback: list[tuple[int, BaseRoute]] = []
        self._route_count = 0

    def _rebuild_index(self) -> None:
        groups: dict[tuple[str, ...], list[tuple[int, BaseRoute]]] = {}
        fallback: list[tuple[int, BaseRoute]] = []
        for index, route in enumerate(self._route_registry):
            if route is self:
                continue
            path = getattr(route, 'path', None)
            if not isinstance(path, str):
                continue
            static_segments: list[str] = []
            for segment in path.split('/')[1:]:
                if not segment or segment.startswith('{'):
                    break
                static_segments.append(segment)
                if len(static_segments) == _ROUTE_PREFIX_SEGMENTS:
                    break
            if not static_segments:
                fallback.append((index, route))
                continue
            groups.setdefault(tuple(static_segments), []).append((index, route))
        self._groups = groups
        self._fallback = fallback
        self._route_count = sum(len(group) for group in groups.values()) + len(fallback)
        self._indexed_route_count = len(self._route_registry)

    def _candidates(self, path: str, *, root_path: str = '') -> list[BaseRoute]:
        if self._indexed_route_count != len(self._route_registry):
            self._rebuild_index()
        if root_path and path.startswith(root_path):
            path = path[len(root_path) :] or '/'
        segments = tuple(segment for segment in path.split('/') if segment)
        indexed = list(self._fallback)
        for size in range(min(_ROUTE_PREFIX_SEGMENTS, len(segments)), 0, -1):
            indexed.extend(self._groups.get(segments[:size], ()))
        indexed.sort(key=lambda item: item[0])
        return [route for _index, route in indexed]

    def candidate_count(self, path: str, *, root_path: str = '') -> int:
        """Expose the bounded lookup size for a focused regression test."""
        return len(self._candidates(path, root_path=root_path))

    def matches(self, scope):
        path = scope.get('path', '')
        if scope.get('type') not in {'http', 'websocket'}:
            return Match.NONE, {}

        partial: tuple[BaseRoute, dict[str, object]] | None = None
        for route in self._candidates(path, root_path=scope.get('root_path', '')):
            match, child_scope = route.matches(scope)
            if match == Match.FULL:
                return match, {**child_scope, _DISPATCH_TARGET_SCOPE_KEY: route}
            if match == Match.PARTIAL and partial is None:
                partial = route, child_scope
        if partial is None:
            return Match.NONE, {}
        route, child_scope = partial
        return Match.PARTIAL, {**child_scope, _DISPATCH_TARGET_SCOPE_KEY: route}

    async def handle(self, scope, receive, send) -> None:
        route = scope.pop(_DISPATCH_TARGET_SCOPE_KEY, None)
        if not isinstance(route, BaseRoute):
            raise RuntimeError('API route dispatcher received no matched route')
        await route.handle(scope, receive, send)


def include_api_routes(app: FastAPI) -> None:
    """Expand API routes once, retaining metadata and indexed request matching."""
    first_api_route_index = len(app.router.routes)
    for route_context in iter_route_contexts(router.routes):
        path = route_context.path
        effective_route = getattr(route_context, '_effective_route', None)
        starlette_route = getattr(effective_route, 'starlette_route', None)
        path = path or getattr(starlette_route, 'path', None)
        if not path:
            raise RuntimeError(f'API route path could not be resolved for {route_context.name!r}')

        original_route = route_context.original_route
        if isinstance(original_route, APIRoute):
            route_class = cast(type[APIRoute], type(original_route))
            app.router.add_api_route(
                path,
                original_route.endpoint,
                response_model=route_context.response_model,
                status_code=route_context.status_code,
                tags=route_context.tags,
                dependencies=route_context.dependencies,
                summary=route_context.summary,
                description=route_context.description,
                response_description=route_context.response_description,
                responses=route_context.responses,
                deprecated=route_context.deprecated,
                methods=route_context.methods,
                operation_id=route_context.operation_id,
                response_model_include=route_context.response_model_include,
                response_model_exclude=route_context.response_model_exclude,
                response_model_by_alias=route_context.response_model_by_alias,
                response_model_exclude_unset=route_context.response_model_exclude_unset,
                response_model_exclude_defaults=route_context.response_model_exclude_defaults,
                response_model_exclude_none=route_context.response_model_exclude_none,
                include_in_schema=route_context.include_in_schema,
                response_class=route_context.response_class,
                name=route_context.name,
                route_class_override=route_class,
                callbacks=route_context.callbacks,
                openapi_extra=route_context.openapi_extra,
                generate_unique_id_function=route_context.generate_unique_id_function,
                strict_content_type=route_context.strict_content_type,
            )
        elif isinstance(original_route, APIWebSocketRoute):
            if starlette_route is None:
                raise RuntimeError(f'WebSocket route is missing its effective route at {path!r}')
            app.router.add_api_websocket_route(
                path,
                original_route.endpoint,
                name=starlette_route.name,
                dependencies=starlette_route.dependencies,
            )
        else:
            raise RuntimeError(f'Unsupported API route type {type(original_route).__name__} at {path!r}')

    app.router.routes.insert(first_api_route_index, _ApiRouteDispatcher(app.router.routes))
