"""MCP decorators — opt-in marker for deterministic tool exposure."""

from collections.abc import Callable
from typing import TypeVar

F = TypeVar('F', bound=Callable)


def deterministic_tool(fn: F) -> F:
    """Mark a route endpoint as a deterministic MCP tool."""
    fn.__mcp_tool__ = True  # type: ignore[attr-defined]
    return fn
