"""MCP-aware FastAPI router that captures onboarding metadata at registration."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from fastapi.routing import APIRoute

MCP_ROUTE_META = '__mcp_route_meta__'
MCP_ENDPOINT_META = '__mcp_endpoint_meta__'


def _response_model_name(route: APIRoute) -> str | None:
    model = getattr(route, 'response_model', None)
    if model is None:
        return None
    return getattr(model, '__name__', str(model))


def build_inputs(fn: Callable[..., Any]) -> list[dict[str, Any]]:
    signature = inspect.signature(fn)
    items: list[dict[str, Any]] = []
    for p in signature.parameters.values():
        if p.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
            continue
        ann = p.annotation
        ann_name = None if ann is inspect.Parameter.empty else str(ann)
        has_default = p.default is not inspect.Parameter.empty
        items.append(
            {
                'name': p.name,
                'kind': p.kind.name.lower(),
                'required': not has_default,
                'default': None if not has_default else p.default,
                'annotation': ann_name,
            },
        )
    return items


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

    doc = inspect.getdoc(root) or ''
    meta: dict[str, Any] = {
        'name': mcp_tool_id or getattr(root, '__name__', getattr(endpoint, '__name__', 'tool')),
        'docstring': doc,
        'inputs': build_inputs(root),
    }
    if mcp_confirm_required is not None:
        meta['confirm_required'] = mcp_confirm_required

    setattr(root, MCP_ENDPOINT_META, dict(meta))
    setattr(endpoint, MCP_ENDPOINT_META, dict(meta))


def _get_endpoint_meta(endpoint: Callable[..., Any]) -> dict[str, Any] | None:
    fn = inspect.unwrap(endpoint)
    endpoint_meta = getattr(endpoint, MCP_ENDPOINT_META, None)
    if isinstance(endpoint_meta, dict):
        return dict(endpoint_meta)
    root_meta = getattr(fn, MCP_ENDPOINT_META, None)
    if isinstance(root_meta, dict):
        return dict(root_meta)
    return None


def build_mcp_route_meta(route: APIRoute) -> dict[str, Any] | None:
    """Build MCP onboarding metadata from router config and endpoint details."""
    onboard = _get_endpoint_meta(route.endpoint)
    if not isinstance(onboard, dict):
        return None
    meta = dict(onboard)
    if 'name' not in meta:
        meta['name'] = getattr(route.endpoint, '__name__', route.name)
    response_model = _response_model_name(route)
    if response_model is not None:
        meta['response_model'] = response_model
    return meta


def attach_mcp_route_meta(route: APIRoute) -> dict[str, Any] | None:
    """Attach onboarding metadata directly on the APIRoute."""
    meta = build_mcp_route_meta(route)
    if meta is None:
        return None
    setattr(route, MCP_ROUTE_META, meta)
    return meta


def get_mcp_route_meta(route: APIRoute) -> dict[str, Any] | None:
    """Return MCP onboarding metadata attached at registration time."""
    route_meta = getattr(route, MCP_ROUTE_META, None)
    if isinstance(route_meta, dict):
        return route_meta
    return None


class MCPRouter(APIRouter):
    """APIRouter that captures MCP onboarding metadata during route registration."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault('route_class', MCPRoute)
        super().__init__(*args, **kwargs)

    def add_api_route(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        mcp = bool(kwargs.pop('mcp', False))
        mcp_confirm_required = kwargs.pop('mcp_confirm_required', None)
        mcp_tool_id = kwargs.pop('mcp_tool_id', None)
        set_mcp_endpoint_meta(
            endpoint,
            mcp=mcp,
            mcp_confirm_required=mcp_confirm_required,
            mcp_tool_id=mcp_tool_id,
        )
        super().add_api_route(path, endpoint, **kwargs)
        route = self.routes[-1] if self.routes else None
        if not isinstance(route, APIRoute):
            return
        attach_mcp_route_meta(route)

    def _route_decorator(
        self,
        path: str,
        *,
        methods: list[str],
        mcp: bool,
        mcp_confirm_required: bool | None,
        mcp_tool_id: str | None,
        **kwargs: Any,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorate(endpoint: Callable[..., Any]) -> Callable[..., Any]:
            route_kwargs = dict(kwargs)
            route_kwargs['methods'] = methods
            route_kwargs['mcp'] = mcp
            route_kwargs['mcp_confirm_required'] = mcp_confirm_required
            route_kwargs['mcp_tool_id'] = mcp_tool_id
            self.add_api_route(
                path,
                endpoint,
                **route_kwargs,
            )
            return endpoint

        return decorate

    def api_route(  # type: ignore[override]
        self,
        path: str,
        *,
        mcp: bool = False,
        mcp_confirm_required: bool | None = None,
        mcp_tool_id: str | None = None,
        **kwargs: Any,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        methods = kwargs.pop('methods', ['GET'])
        method_list = [m.upper() for m in methods]
        return self._route_decorator(
            path,
            methods=method_list,
            mcp=mcp,
            mcp_confirm_required=mcp_confirm_required,
            mcp_tool_id=mcp_tool_id,
            **kwargs,
        )

    def get(  # type: ignore[override]
        self,
        path: str,
        *,
        mcp: bool = False,
        mcp_confirm_required: bool | None = None,
        mcp_tool_id: str | None = None,
        **kwargs: Any,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._route_decorator(
            path,
            methods=['GET'],
            mcp=mcp,
            mcp_confirm_required=mcp_confirm_required,
            mcp_tool_id=mcp_tool_id,
            **kwargs,
        )

    def post(  # type: ignore[override]
        self,
        path: str,
        *,
        mcp: bool = False,
        mcp_confirm_required: bool | None = None,
        mcp_tool_id: str | None = None,
        **kwargs: Any,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._route_decorator(
            path,
            methods=['POST'],
            mcp=mcp,
            mcp_confirm_required=mcp_confirm_required,
            mcp_tool_id=mcp_tool_id,
            **kwargs,
        )

    def put(  # type: ignore[override]
        self,
        path: str,
        *,
        mcp: bool = False,
        mcp_confirm_required: bool | None = None,
        mcp_tool_id: str | None = None,
        **kwargs: Any,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._route_decorator(
            path,
            methods=['PUT'],
            mcp=mcp,
            mcp_confirm_required=mcp_confirm_required,
            mcp_tool_id=mcp_tool_id,
            **kwargs,
        )

    def patch(  # type: ignore[override]
        self,
        path: str,
        *,
        mcp: bool = False,
        mcp_confirm_required: bool | None = None,
        mcp_tool_id: str | None = None,
        **kwargs: Any,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._route_decorator(
            path,
            methods=['PATCH'],
            mcp=mcp,
            mcp_confirm_required=mcp_confirm_required,
            mcp_tool_id=mcp_tool_id,
            **kwargs,
        )

    def delete(  # type: ignore[override]
        self,
        path: str,
        *,
        mcp: bool = False,
        mcp_confirm_required: bool | None = None,
        mcp_tool_id: str | None = None,
        **kwargs: Any,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._route_decorator(
            path,
            methods=['DELETE'],
            mcp=mcp,
            mcp_confirm_required=mcp_confirm_required,
            mcp_tool_id=mcp_tool_id,
            **kwargs,
        )


class MCPRoute(APIRoute):
    """APIRoute variant that carries MCP onboarding metadata."""

    def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        kwargs.pop('mcp', None)
        kwargs.pop('mcp_confirm_required', None)
        kwargs.pop('mcp_tool_id', None)
        super().__init__(path, endpoint, **kwargs)
        attach_mcp_route_meta(self)
