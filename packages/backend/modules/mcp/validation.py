"""MCP input validation — JSON Schema validation and default application."""

from typing import Any

import jsonschema
import jsonschema.validators
from jsonschema import FormatChecker

_SUPPORTED_TYPES = {'object', 'array', 'string', 'number', 'integer', 'boolean', 'null'}

_SUPPORTED_KEYWORDS = {
    'type',
    'properties',
    'required',
    'enum',
    'const',
    'default',
    'anyOf',
    'oneOf',
    'allOf',
    'nullable',
    'patternProperties',
    'additionalProperties',
    'if',
    'then',
    'else',
    'not',
    'dependentRequired',
    'dependencies',
    'minimum',
    'maximum',
    'minLength',
    'maxLength',
    'pattern',
    'format',
    'items',
    'description',
    'title',
    '$schema',
    '$defs',
    '$ref',
    'definitions',
    'minItems',
    'maxItems',
    'uniqueItems',
    'exclusiveMinimum',
    'exclusiveMaximum',
    'multipleOf',
    'examples',
    'readOnly',
    'writeOnly',
    'deprecated',
    'contentEncoding',
    'contentMediaType',
    'unevaluatedProperties',
    'prefixItems',
}


def _check_schema_node(schema: Any, path: str, issues: list[str]) -> None:
    if not isinstance(schema, dict):
        return

    def child(suffix: str) -> str:
        return f'{path}.{suffix}' if path else suffix

    issues.extend(child(key) for key in schema if key not in _SUPPORTED_KEYWORDS)
    schema_type = schema.get('type')
    if isinstance(schema_type, str) and schema_type not in _SUPPORTED_TYPES:
        issues.append(child(f'type={schema_type}'))
    for keyword in ('anyOf', 'oneOf', 'allOf'):
        for i, sub in enumerate(schema.get(keyword, [])):
            _check_schema_node(sub, child(f'{keyword}[{i}]'), issues)
    for keyword in ('not', 'if', 'then', 'else'):
        if isinstance(schema.get(keyword), dict):
            _check_schema_node(schema[keyword], child(keyword), issues)
    for keyword in ('properties', 'patternProperties'):
        for prop, sub in schema.get(keyword, {}).items():
            _check_schema_node(sub, child(f'{keyword}.{prop}'), issues)
    if isinstance(schema.get('additionalProperties'), dict):
        _check_schema_node(schema['additionalProperties'], child('additionalProperties'), issues)
    items = schema.get('items')
    if isinstance(items, dict):
        _check_schema_node(items, child('items'), issues)
    elif isinstance(items, list):
        for i, sub in enumerate(items):
            _check_schema_node(sub, child(f'items[{i}]'), issues)


def check_schema_supported(schema: dict) -> list[str]:
    """Return list of unsupported paths; empty list means schema is fully supported."""
    issues: list[str] = []
    _check_schema_node(schema, '', issues)
    return issues


_ERROR_HINTS: dict[Any, str] = {
    None: 'Check input against schema.',
    'required': 'Provide all required fields.',
    'additionalProperties': 'Remove unknown fields or use documented parameter names.',
    'enum': 'Use one of the documented enum values.',
    'type': 'Use the documented JSON type for this field.',
    **dict.fromkeys(('minLength', 'maxLength', 'minimum', 'maximum', 'pattern', 'format'), 'Check schema constraints for this field.'),
}


def _build_error_message(error: jsonschema.ValidationError) -> str:
    hint = _ERROR_HINTS.get(error.validator)
    return f'{error.message}. {hint}' if hint else error.message


def apply_defaults(schema: dict, data: dict) -> dict:
    """Return a copy of data with missing properties filled from schema defaults/consts."""
    if schema.get('type') != 'object':
        return data
    result = dict(data)
    for name, prop in schema.get('properties', {}).items():
        if name in result:
            if isinstance(result[name], dict) and prop.get('type') == 'object':
                result[name] = apply_defaults(prop, result[name])
            continue
        if 'const' in prop:
            result[name] = prop['const']
            continue
        if 'default' in prop:
            result[name] = prop['default']
            continue
        if prop.get('type') == 'object':
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
                'path': '.'.join(str(p) for p in e.absolute_path) or '$',
                'message': _build_error_message(e),
                'validator': e.validator or 'unknown',
            }
            for e in raw
        ]
        return False, errors, args
    normalized = apply_defaults(schema, args)
    return True, [], normalized
