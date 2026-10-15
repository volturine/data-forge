"""MCP-aware FastAPI router that captures onboarding metadata at registration."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from fastapi.routing import APIRoute

MCP_ROUTE_META = '__mcp_route_meta__'
MCP_ENDPOINT_META = '__mcp_endpoint_meta__'

type _RouteDecorator = Callable[[Callable[..., Any]], Callable[..., Any]]


def set_mcp_endpoint_meta(
    endpoint: Callable[..., Any],
    *,
    mcp: bool,
    mcp_confirm_required: bool | None,
    mcp_tool_id: str | None,
) -> None:
    root = inspect.unwrap(endpoint)
    if not mcp:
        setattr(endpoint, MCP_ENDPOINT_META, None)
        setattr(root, MCP_ENDPOINT_META, None)
        return

    meta = {
        'name': mcp_tool_id if mcp_tool_id is not None else getattr(root, '__name__', getattr(endpoint, '__name__', 'tool')),
        'docstring': inspect.getdoc(root) or '',
    }
    if mcp_confirm_required is not None:
        meta['confirm_required'] = mcp_confirm_required

    setattr(root, MCP_ENDPOINT_META, dict(meta))
    setattr(endpoint, MCP_ENDPOINT_META, dict(meta))


def attach_mcp_route_meta(route: APIRoute) -> None:
    """Attach onboarding metadata from the endpoint directly on the APIRoute."""
    endpoint_meta = getattr(route.endpoint, MCP_ENDPOINT_META, None)
    if not isinstance(endpoint_meta, dict):
        endpoint_meta = getattr(inspect.unwrap(route.endpoint), MCP_ENDPOINT_META, None)
    if not isinstance(endpoint_meta, dict):
        return
    meta = dict(endpoint_meta)
    if route.response_model is not None:
        meta['response_model'] = getattr(route.response_model, '__name__', str(route.response_model))
    setattr(route, MCP_ROUTE_META, meta)


def get_mcp_route_meta(route: APIRoute) -> dict[str, Any] | None:
    """Return MCP onboarding metadata attached at registration time."""
    route_meta = getattr(route, MCP_ROUTE_META, None)
    return route_meta if isinstance(route_meta, dict) else None


class MCPRouter(APIRouter):
    """APIRouter that captures MCP onboarding metadata during route registration."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault('route_class', MCPRoute)
        super().__init__(*args, **kwargs)

    def add_api_route(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        set_mcp_endpoint_meta(
            endpoint,
            mcp=bool(kwargs.pop('mcp', False)),
            mcp_confirm_required=kwargs.pop('mcp_confirm_required', None),
            mcp_tool_id=kwargs.pop('mcp_tool_id', None),
        )
        # MCPRoute attaches the route metadata while it is constructed.
        super().add_api_route(path, endpoint, **kwargs)

    def api_route(  # type: ignore[override]
        self,
        path: str,
        *,
        mcp: bool = False,
        mcp_confirm_required: bool | None = None,
        mcp_tool_id: str | None = None,
        **kwargs: Any,
    ) -> _RouteDecorator:
        methods = [method.upper() for method in kwargs.pop('methods', ['GET'])]

        def decorate(endpoint: Callable[..., Any]) -> Callable[..., Any]:
            self.add_api_route(
                path,
                endpoint,
                methods=methods,
                mcp=mcp,
                mcp_confirm_required=mcp_confirm_required,
                mcp_tool_id=mcp_tool_id,
                **kwargs,
            )
            return endpoint

        return decorate

    def get(self, path: str, **kwargs: Any) -> _RouteDecorator:  # type: ignore[override]
        return self.api_route(path, methods=['GET'], **kwargs)

    def post(self, path: str, **kwargs: Any) -> _RouteDecorator:  # type: ignore[override]
        return self.api_route(path, methods=['POST'], **kwargs)

    def put(self, path: str, **kwargs: Any) -> _RouteDecorator:  # type: ignore[override]
        return self.api_route(path, methods=['PUT'], **kwargs)

    def patch(self, path: str, **kwargs: Any) -> _RouteDecorator:  # type: ignore[override]
        return self.api_route(path, methods=['PATCH'], **kwargs)

    def delete(self, path: str, **kwargs: Any) -> _RouteDecorator:  # type: ignore[override]
        return self.api_route(path, methods=['DELETE'], **kwargs)


class MCPRoute(APIRoute):
    """APIRoute variant that carries MCP onboarding metadata."""

    def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        super().__init__(path, endpoint, **kwargs)
        attach_mcp_route_meta(self)
