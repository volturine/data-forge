"""MCP decorators and metadata helpers for tool onboarding."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, TypeVar, overload

from modules.mcp.router import build_inputs

F = TypeVar("F", bound=Callable)
MCP_TOOL_MARKER = "__mcp_tool__"
MCP_TOOL_META = "__mcp_tool_meta__"


def _iter_wrapped(fn: Callable) -> list[Callable]:
    seen: set[int] = set()
    current: Callable | None = fn
    stack: list[Callable] = []
    while current is not None:
        obj_id = id(current)
        if obj_id in seen:
            break
        seen.add(obj_id)
        stack.append(current)
        wrapped = getattr(current, "__wrapped__", None)
        current = wrapped if callable(wrapped) else None
    return stack


def _build_meta(fn: Callable, confirm_required: bool | None) -> dict[str, Any]:
    doc = inspect.getdoc(fn) or ""
    meta: dict[str, Any] = {
        "name": fn.__name__,
        "docstring": doc,
        "inputs": build_inputs(fn),
    }
    if confirm_required is not None:
        meta["confirm_required"] = confirm_required
    return meta


def get_mcp_tool_meta(fn: Callable) -> dict[str, Any] | None:
    """Return MCP onboarding metadata from a callable or its wrappers."""
    for item in _iter_wrapped(fn):
        meta = getattr(item, MCP_TOOL_META, None)
        if isinstance(meta, dict):
            return meta
        if getattr(item, MCP_TOOL_MARKER, False):
            return _build_meta(item, confirm_required=None)
    return None


@overload
def deterministic_tool(fn: F, /) -> F: ...


@overload
def deterministic_tool(*, confirm_required: bool | None = None) -> Callable[[F], F]: ...


def deterministic_tool(fn: F | None = None, /, *, confirm_required: bool | None = None) -> F | Callable[[F], F]:
    """Mark a route endpoint as deterministic and attach onboarding metadata."""

    def apply(target: F) -> F:
        root = inspect.unwrap(target)
        root_meta = _build_meta(root, confirm_required=confirm_required)
        target_meta = dict(root_meta)
        setattr(root, MCP_TOOL_MARKER, True)
        setattr(root, MCP_TOOL_META, root_meta)
        setattr(target, MCP_TOOL_MARKER, True)
        setattr(target, MCP_TOOL_META, target_meta)
        return target

    if fn is None:
        return apply
    return apply(fn)
