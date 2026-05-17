"""Helpers for MCP tool output formatting."""

from __future__ import annotations

from typing import Any


def top_level_output_fields(schema: Any) -> list[str]:
    if not isinstance(schema, dict):
        return []
    if schema.get("type") == "object":
        props = schema.get("properties")
        if not isinstance(props, dict):
            return []
        return [key for key in props if isinstance(key, str)]
    if schema.get("type") == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            return []
        props = items.get("properties")
        if not isinstance(props, dict):
            return []
        return [key for key in props if isinstance(key, str)]
    return []


def format_output_hint(output: dict[str, Any] | None, field_limit: int = 8) -> str:
    if not isinstance(output, dict):
        return ""
    parts: list[str] = []
    status_code = output.get("status_code")
    if isinstance(status_code, str) and status_code:
        parts.append(f"status {status_code}")
    content_type = output.get("content_type")
    if isinstance(content_type, str) and content_type:
        parts.append(content_type)
    response_model = output.get("response_model")
    if isinstance(response_model, str) and response_model:
        parts.append(f"model {response_model}")
    fields = output.get("fields")
    if not isinstance(fields, list):
        fields = top_level_output_fields(output.get("schema"))
    named_fields = [field for field in fields if isinstance(field, str)][:field_limit]
    if named_fields:
        parts.append(f"fields: {', '.join(named_fields)}")
    if not parts:
        return ""
    return "Expected output: " + "; ".join(parts)
