"""MCP domain value objects."""

from __future__ import annotations

import re
from typing import Any, cast

from contracts.enums import DataForgeStrEnum
from pydantic import BaseModel, Field, computed_field


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


class MCPToolDefinition(BaseModel):
    id: str
    method: MCPHttpMethod
    path: str
    description: str
    confirm_required: bool = False
    input_schema: dict[str, Any]
    arg_metadata: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)

    @classmethod
    def coerce(cls, value: "MCPToolDefinition | dict[str, Any]") -> "MCPToolDefinition":
        if isinstance(value, cls):
            return value
        method = MCPHttpMethod.require(value.get("method", MCPHttpMethod.GET.value))
        path_value = value.get("path")
        path = path_value if isinstance(path_value, str) else ""
        description_value = value.get("description")
        description = description_value if isinstance(description_value, str) else ""
        if not description:
            tool_id_value = value.get("id")
            description = tool_id_value if isinstance(tool_id_value, str) else f"{method.value} {path}".strip()
        input_schema_value = value.get("input_schema")
        input_schema = cast(dict[str, Any], input_schema_value) if isinstance(input_schema_value, dict) else {}
        arg_metadata_value = value.get("arg_metadata")
        arg_metadata = cast(dict[str, Any], arg_metadata_value) if isinstance(arg_metadata_value, dict) else {}
        output_schema_value = value.get("output_schema")
        output_schema = cast(dict[str, Any], output_schema_value) if isinstance(output_schema_value, dict) else None
        tags_value = value.get("tags")
        raw_tags = tags_value if isinstance(tags_value, list) else []
        return cls(
            id=str(value.get("id", "tool")),
            method=method,
            path=path,
            description=description,
            confirm_required=bool(value.get("confirm_required", False)),
            input_schema=input_schema,
            arg_metadata=arg_metadata,
            output_schema=output_schema,
            tags=[tag for tag in raw_tags if isinstance(tag, str)],
        )

    @computed_field(return_type=MCPToolSafety)
    def safety(self) -> MCPToolSafety:
        return self.method.safety

    def validate_arguments(self, args: dict[str, Any]) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
        from modules.mcp.validation import validate_args

        return validate_args(self.input_schema, args)

    def schema_support_issues(self) -> list[str]:
        from modules.mcp.validation import check_schema_supported

        return check_schema_supported(self.input_schema)

    def capability_report(self) -> dict[str, Any]:
        unsupported = self.schema_support_issues()
        return {
            "tool_id": self.id,
            "supported": not unsupported,
            "issues": [{"path": path, "message": "unsupported schema"} for path in unsupported],
        }

    def pending_response(self, token: str, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "pending",
            "token": token,
            "tool_id": self.id,
            "method": self.method.value,
            "path": self.path,
            "args": args,
            "confirm_required": self.confirm_required,
        }

    def executed_response(self, result: dict[str, Any]) -> dict[str, Any]:
        return {"status": "executed", "result": result}

    def validation_error_response(
        self,
        errors: list[dict[str, Any]],
        args: dict[str, Any],
        *,
        include_tool_id: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "status": "validation_error",
            "valid": False,
            "errors": errors,
            "args": args,
        }
        if include_tool_id:
            payload["tool_id"] = self.id
        return payload

    def path_param_error_response(self, message: str, args: dict[str, Any]) -> dict[str, Any]:
        return self.validation_error_response(
            [{"path": "$", "message": message, "validator": "path_params"}],
            args,
            include_tool_id=True,
        )

    def openai_tool(self) -> dict[str, Any]:
        from modules.mcp.tool_output import format_output_hint

        description = self.description
        if hint := format_output_hint(self.output_schema):
            description = f"{description}\n{hint}"
        return {
            "type": "function",
            "function": {
                "name": self.id,
                "description": description,
                "parameters": self.input_schema,
            },
        }

    def to_api_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def __getitem__(self, key: str) -> Any:
        return self.to_api_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_api_dict().get(key, default)


CONFIRM_REQUIRED_PATTERNS: tuple[tuple[MCPHttpMethod, str], ...] = (
    (MCPHttpMethod.DELETE, r"^/api/v1/datasource/"),
    (MCPHttpMethod.DELETE, r"^/api/v1/scheduler/"),
    (MCPHttpMethod.DELETE, r"^/api/v1/healthchecks/"),
    (MCPHttpMethod.DELETE, r"^/api/v1/analysis/"),
)
