"""MCP domain value objects."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, computed_field

from backend_core.domain.enums import DataForgeStrEnum


class MCPToolSafety(DataForgeStrEnum):
    SAFE = 'safe'
    MUTATING = 'mutating'


class MCPHttpMethod(DataForgeStrEnum):
    GET = 'GET'
    HEAD = 'HEAD'
    OPTIONS = 'OPTIONS'
    POST = 'POST'
    PUT = 'PUT'
    PATCH = 'PATCH'
    DELETE = 'DELETE'

    @classmethod
    def from_route_method(cls, value: str) -> MCPHttpMethod | None:
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
            'tool_id': self.id,
            'supported': not unsupported,
            'issues': [{'path': path, 'message': 'unsupported schema'} for path in unsupported],
        }

    def pending_response(self, token: str, args: dict[str, Any]) -> dict[str, Any]:
        return {
            'status': 'pending',
            'token': token,
            'tool_id': self.id,
            'method': self.method.value,
            'path': self.path,
            'args': args,
            'confirm_required': self.confirm_required,
        }

    def executed_response(self, result: dict[str, Any]) -> dict[str, Any]:
        return {'status': 'executed', 'result': result}

    def validation_error_response(
        self,
        errors: list[dict[str, Any]],
        args: dict[str, Any],
        *,
        include_tool_id: bool = False,
    ) -> dict[str, Any]:
        payload = {
            'status': 'validation_error',
            'valid': False,
            'errors': errors,
            'args': args,
        }
        if include_tool_id:
            payload['tool_id'] = self.id
        return payload

    def path_param_error_response(self, message: str, args: dict[str, Any]) -> dict[str, Any]:
        return self.validation_error_response(
            [{'path': '$', 'message': message, 'validator': 'path_params'}],
            args,
            include_tool_id=True,
        )

    def openai_tool(self) -> dict[str, Any]:
        from modules.mcp.tool_output import format_output_hint

        description = self.description
        if hint := format_output_hint(self.output_schema):
            description = f'{description}\n{hint}'
        return {
            'type': 'function',
            'function': {
                'name': self.id,
                'description': description,
                'parameters': self.input_schema,
            },
        }
