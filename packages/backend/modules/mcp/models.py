"""MCP domain value objects."""

from __future__ import annotations

import re

from contracts.enums import DataForgeStrEnum


class MCPToolSafety(DataForgeStrEnum):
    SAFE = "safe"
    MUTATING = "mutating"


class MCPHttpMethod(DataForgeStrEnum):
    GET = "GET"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"

    @classmethod
    def from_route_method(cls, value: str) -> "MCPHttpMethod | None":
        try:
            return cls(value.upper())
        except ValueError:
            return None

    @property
    def safety(self) -> MCPToolSafety:
        if self in {self.GET, self.HEAD, self.OPTIONS}:
            return MCPToolSafety.SAFE
        return MCPToolSafety.MUTATING

    @property
    def is_mutating(self) -> bool:
        return self.safety == MCPToolSafety.MUTATING

    def requires_confirmation_for_path(self, path: str) -> bool:
        return any(self is method and re.match(pattern, path) for method, pattern in CONFIRM_REQUIRED_PATTERNS)


CONFIRM_REQUIRED_PATTERNS: tuple[tuple[MCPHttpMethod, str], ...] = (
    (MCPHttpMethod.DELETE, r"^/api/v1/datasource/"),
    (MCPHttpMethod.DELETE, r"^/api/v1/scheduler/"),
    (MCPHttpMethod.DELETE, r"^/api/v1/healthchecks/"),
    (MCPHttpMethod.DELETE, r"^/api/v1/analysis/"),
)
