"""Generate TypeScript interfaces from Pydantic step schemas.

Run from the backend directory:
    uv run python scripts/generate_ts_step_types.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# Ensure backend package is importable when running from backend/
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.analysis.step_schemas import (
    AggregationSchema,
    AIConfig,
    ChartConfig,
    DatasourceConfig,
    DeduplicateConfig,
    DownloadConfig,
    DropConfig,
    ExplodeConfig,
    ExportConfig,
    ExpressionConfig,
    FillNullConfig,
    FilterConditionSchema,
    FilterConfig,
    GroupByConfig,
    JoinColumnSchema,
    JoinConfig,
    LimitConfig,
    NotificationConfig,
    OverlaySchema,
    PivotConfig,
    ReferenceLineSchema,
    RenameConfig,
    SampleConfig,
    SelectConfig,
    SortConfig,
    StringTransformConfig,
    TimeSeriesConfig,
    TopKConfig,
    UnionByNameConfig,
    UnpivotConfig,
    ViewConfig,
    WithColumnsConfig,
    WithColumnsExprSchema,
)

OUTPUT_PATH = Path(__file__).parent.parent.parent / 'frontend' / 'src' / 'lib' / 'types' / 'step-schemas.generated.ts'

# Models to export as TypeScript interfaces (in desired output order).
# Top-level model name -> Pydantic class.
MODELS: list[tuple[str, type[BaseModel]]] = [
    ('SelectConfig', SelectConfig),
    ('DropConfig', DropConfig),
    ('FilterConditionSchema', FilterConditionSchema),
    ('FilterConfig', FilterConfig),
    ('AggregationSchema', AggregationSchema),
    ('GroupByConfig', GroupByConfig),
    ('SortConfig', SortConfig),
    ('RenameConfig', RenameConfig),
    ('ExpressionConfig', ExpressionConfig),
    ('WithColumnsExprSchema', WithColumnsExprSchema),
    ('WithColumnsConfig', WithColumnsConfig),
    ('LimitConfig', LimitConfig),
    ('SampleConfig', SampleConfig),
    ('TopKConfig', TopKConfig),
    ('DeduplicateConfig', DeduplicateConfig),
    ('FillNullConfig', FillNullConfig),
    ('UnpivotConfig', UnpivotConfig),
    ('ExplodeConfig', ExplodeConfig),
    ('PivotConfig', PivotConfig),
    ('UnionByNameConfig', UnionByNameConfig),
    ('JoinColumnSchema', JoinColumnSchema),
    ('JoinConfig', JoinConfig),
    ('ViewConfig', ViewConfig),
    ('ExportConfig', ExportConfig),
    ('DownloadConfig', DownloadConfig),
    ('OverlaySchema', OverlaySchema),
    ('ReferenceLineSchema', ReferenceLineSchema),
    ('ChartConfig', ChartConfig),
    ('NotificationConfig', NotificationConfig),
    ('AIConfig', AIConfig),
    ('DatasourceConfig', DatasourceConfig),
    ('TimeSeriesConfig', TimeSeriesConfig),
    ('StringTransformConfig', StringTransformConfig),
]


def _json_schema_type_to_ts(
    schema: dict[str, Any],
    defs: dict[str, Any],
    required_fields: set[str],
    field_name: str,
) -> str:
    """Convert a JSON Schema type definition to a TypeScript type string."""
    # $ref -> reference to a named interface
    if '$ref' in schema:
        ref_name = schema['$ref'].split('/')[-1]
        return ref_name

    # anyOf / oneOf -> union (typically for nullable fields)
    for composite_key in ('anyOf', 'oneOf'):
        if composite_key in schema:
            variants = schema[composite_key]
            ts_types: list[str] = []
            for variant in variants:
                ts_types.append(_json_schema_type_to_ts(variant, defs, required_fields, field_name))
            # Deduplicate while preserving order
            seen: list[str] = []
            for t in ts_types:
                if t not in seen:
                    seen.append(t)
            return ' | '.join(seen)

    schema_type = schema.get('type')

    # Literal / enum union
    if 'enum' in schema:
        parts: list[str] = []
        for v in schema['enum']:
            if v is None:
                parts.append('null')
            elif isinstance(v, str):
                parts.append(f"'{v}'")
            else:
                parts.append(str(v))
        return ' | '.join(parts)

    if schema_type == 'string':
        return 'string'
    if schema_type in ('integer', 'number'):
        return 'number'
    if schema_type == 'boolean':
        return 'boolean'
    if schema_type == 'null':
        return 'null'

    if schema_type == 'array':
        items = schema.get('items', {})
        item_type = _json_schema_type_to_ts(items, defs, set(), field_name) if items else 'unknown'
        return f'{item_type}[]'

    if schema_type == 'object':
        additional = schema.get('additionalProperties')
        if isinstance(additional, dict):
            val_type = _json_schema_type_to_ts(additional, defs, set(), field_name)
            return f'Record<string, {val_type}>'
        props = schema.get('properties')
        if props:
            inner_required = set(schema.get('required', []))
            parts = []
            for prop_name, prop_schema in props.items():
                prop_type = _json_schema_type_to_ts(prop_schema, defs, inner_required, prop_name)
                optional = '' if prop_name in inner_required else '?'
                parts.append(f'{prop_name}{optional}: {prop_type}')
            return '{ ' + '; '.join(parts) + ' }'
        return 'Record<string, unknown>'

    return 'unknown'


def _schema_to_ts_declaration(name: str, schema: dict[str, Any], defs: dict[str, Any]) -> str:
    """Render a JSON Schema object as a TypeScript declaration."""
    if 'enum' in schema:
        enum_type = _json_schema_type_to_ts(schema, defs, set(), name)
        return f'export type {name} = {enum_type};'

    schema_type = schema.get('type')
    if schema_type != 'object' and 'properties' not in schema:
        value_type = _json_schema_type_to_ts(schema, defs, set(), name)
        return f'export type {name} = {value_type};'

    properties: dict[str, Any] = schema.get('properties', {})
    required_fields: set[str] = set(schema.get('required', []))

    lines: list[str] = [f'export interface {name} {{']

    if not properties:
        # Empty model - allow arbitrary extra keys (matches extra='allow')
        lines.append('  [key: string]: unknown;')
    else:
        for field_name, field_schema in properties.items():
            ts_type = _json_schema_type_to_ts(field_schema, defs, required_fields, field_name)
            optional = '' if field_name in required_fields else '?'
            lines.append(f'  {field_name}{optional}: {ts_type};')

    lines.append('}')
    return '\n'.join(lines)


def _collect_refs(schema: dict[str, Any]) -> list[str]:
    """Recursively collect all $ref names from a schema."""
    refs: list[str] = []
    if '$ref' in schema:
        refs.append(schema['$ref'].split('/')[-1])
    for key in ('anyOf', 'oneOf', 'allOf'):
        for sub in schema.get(key, []):
            refs.extend(_collect_refs(sub))
    for sub in schema.get('properties', {}).values():
        refs.extend(_collect_refs(sub))
    items = schema.get('items')
    if isinstance(items, dict):
        refs.extend(_collect_refs(items))
    additional = schema.get('additionalProperties')
    if isinstance(additional, dict):
        refs.extend(_collect_refs(additional))
    return refs


def generate() -> str:
    """Generate TypeScript source for all step config models."""
    header = [
        "// This file is auto-generated. Do not edit manually. Run 'just generate-step-types' to regenerate.",
        '// Generated from backend/modules/analysis/step_schemas.py',
        '',
    ]

    # Build a global $defs map from all schemas
    all_defs: dict[str, Any] = {}
    model_schemas: list[tuple[str, dict[str, Any]]] = []
    for ts_name, model_cls in MODELS:
        schema = model_cls.model_json_schema(by_alias=True)
        all_defs.update(schema.get('$defs', {}))
        model_schemas.append((ts_name, schema))

    top_level_names: set[str] = {ts_name for ts_name, _ in MODELS}
    emitted_defs: set[str] = set()
    body: list[str] = []

    for ts_name, schema in model_schemas:
        # Emit any $defs referenced by this model that aren't themselves top-level models
        for ref_name in _collect_refs(schema):
            if ref_name in top_level_names or ref_name in emitted_defs:
                continue
            if ref_name in all_defs:
                emitted_defs.add(ref_name)
                body.append(_schema_to_ts_declaration(ref_name, all_defs[ref_name], all_defs))
                body.append('')

        body.append(_schema_to_ts_declaration(ts_name, schema, all_defs))
        body.append('')

    return '\n'.join(header + body)


def main() -> None:
    content = generate()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(content, encoding='utf-8')
    print(f'Generated {OUTPUT_PATH}')


if __name__ == '__main__':
    main()
