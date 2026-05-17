"""MCP input validation — JSON Schema validation and default application."""

from typing import Any

import jsonschema
import jsonschema.validators
from jsonschema import FormatChecker

_SUPPORTED_TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}

_SUPPORTED_KEYWORDS = {
    "type",
    "properties",
    "required",
    "enum",
    "const",
    "default",
    "anyOf",
    "oneOf",
    "allOf",
    "nullable",
    "patternProperties",
    "additionalProperties",
    "if",
    "then",
    "else",
    "not",
    "dependentRequired",
    "dependencies",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "items",
    "description",
    "title",
    "$schema",
    "$defs",
    "$ref",
    "definitions",
    "minItems",
    "maxItems",
    "uniqueItems",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "examples",
    "readOnly",
    "writeOnly",
    "deprecated",
    "contentEncoding",
    "contentMediaType",
    "unevaluatedProperties",
    "prefixItems",
}


def _check_schema_node(schema: Any, path: str, issues: list[str]) -> None:
    if not isinstance(schema, dict):
        return
    for key in schema:
        if key not in _SUPPORTED_KEYWORDS:
            issues.append(f"{path}.{key}" if path else key)
    schema_type = schema.get("type")
    if isinstance(schema_type, str) and schema_type not in _SUPPORTED_TYPES:
        issues.append(f"{path}.type={schema_type}" if path else f"type={schema_type}")
    for keyword in ("anyOf", "oneOf", "allOf"):
        for i, sub in enumerate(schema.get(keyword, [])):
            _check_schema_node(sub, f"{path}.{keyword}[{i}]" if path else f"{keyword}[{i}]", issues)
    for sub in (
        schema.get("not"),
        schema.get("if"),
        schema.get("then"),
        schema.get("else"),
    ):
        if isinstance(sub, dict):
            label = next(k for k in ("not", "if", "then", "else") if schema.get(k) is sub)
            _check_schema_node(sub, f"{path}.{label}" if path else label, issues)
    for prop, sub in schema.get("properties", {}).items():
        _check_schema_node(sub, f"{path}.properties.{prop}" if path else f"properties.{prop}", issues)
    for prop, sub in schema.get("patternProperties", {}).items():
        _check_schema_node(
            sub,
            f"{path}.patternProperties.{prop}" if path else f"patternProperties.{prop}",
            issues,
        )
    ap = schema.get("additionalProperties")
    if isinstance(ap, dict):
        _check_schema_node(
            ap,
            f"{path}.additionalProperties" if path else "additionalProperties",
            issues,
        )
    items = schema.get("items")
    if isinstance(items, dict):
        _check_schema_node(items, f"{path}.items" if path else "items", issues)
    elif isinstance(items, list):
        for i, sub in enumerate(items):
            _check_schema_node(sub, f"{path}.items[{i}]" if path else f"items[{i}]", issues)


def check_schema_supported(schema: dict) -> list[str]:
    """Return list of unsupported paths; empty list means schema is fully supported."""
    issues: list[str] = []
    _check_schema_node(schema, "", issues)
    return issues


def _format_error_path(error: jsonschema.ValidationError) -> str:
    parts = [str(p) for p in error.absolute_path]
    return ".".join(parts) if parts else "$"


def _build_error_message(error: jsonschema.ValidationError) -> str:
    message = error.message
    key = error.validator
    if key is None:
        return f"{message}. Check input against schema."
    if key == "required":
        return f"{message}. Provide all required fields."
    if key == "additionalProperties":
        return f"{message}. Remove unknown fields or use documented parameter names."
    if key == "enum":
        return f"{message}. Use one of the documented enum values."
    if key == "type":
        return f"{message}. Use the documented JSON type for this field."
    if key in {"minLength", "maxLength", "minimum", "maximum", "pattern", "format"}:
        return f"{message}. Check schema constraints for this field."
    return message


def apply_defaults(schema: dict, data: dict) -> dict:
    """Return a copy of data with missing properties filled from schema defaults/consts."""
    if schema.get("type") != "object":
        return data
    result = dict(data)
    for name, prop in schema.get("properties", {}).items():
        if name in result:
            if isinstance(result[name], dict) and prop.get("type") == "object":
                result[name] = apply_defaults(prop, result[name])
            continue
        if "const" in prop:
            result[name] = prop["const"]
            continue
        if "default" in prop:
            result[name] = prop["default"]
            continue
        if prop.get("type") == "object":
            result[name] = apply_defaults(prop, {})
    return result


def validate_args(schema: dict, args: dict) -> tuple[bool, list[dict[str, Any]], dict]:
    """Validate args against schema; return (valid, errors, normalized)."""
    validator_cls = jsonschema.validators.validator_for(schema)
    validator = validator_cls(schema, format_checker=FormatChecker())
    raw = list(validator.iter_errors(args))
    if raw:
        errors = [
            {
                "path": _format_error_path(e),
                "message": _build_error_message(e),
                "validator": e.validator or "unknown",
            }
            for e in raw
        ]
        return False, errors, args
    normalized = apply_defaults(schema, args)
    return True, [], normalized
