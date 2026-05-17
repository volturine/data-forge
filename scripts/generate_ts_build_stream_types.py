"""Generate TypeScript types from backend compute runtime schemas.

Run from the backend directory:
    uv run python scripts/generate_ts_build_stream_types.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packages' / 'shared'))
sys.path.insert(0, str(ROOT / 'packages' / 'backend'))

from contracts.compute import schemas as compute_schemas  # noqa: E402
from contracts.compute.schemas import (  # noqa: E402
    ActiveBuildDetail,
    ActiveBuildSummary,
    BuildEvent,
    BuildListSnapshotMessage,
    BuildSnapshotMessage,
    BuildWebsocketErrorMessage,
)

OUTPUT_PATH = ROOT / 'packages' / 'frontend' / 'src' / 'lib' / 'types' / 'build-stream.generated.ts'

MODELS: list[tuple[str, type[BaseModel]]] = [
    ('ActiveBuildSummary', ActiveBuildSummary),
    ('ActiveBuildDetail', ActiveBuildDetail),
    ('BuildDetailSnapshot', BuildSnapshotMessage),
    ('BuildsSnapshot', BuildListSnapshotMessage),
    ('BuildWebsocketErrorMessage', BuildWebsocketErrorMessage),
]

MODEL_REGISTRY = {name: value for name, value in vars(compute_schemas).items() if isinstance(value, type) and issubclass(value, BaseModel)}


def _json_schema_type_to_ts(schema: dict[str, Any], defs: dict[str, Any]) -> str:
    if '$ref' in schema:
        return schema['$ref'].split('/')[-1]

    for composite_key in ('anyOf', 'oneOf'):
        if composite_key in schema:
            parts = [_json_schema_type_to_ts(item, defs) for item in schema[composite_key]]
            seen: list[str] = []
            for part in parts:
                if part not in seen:
                    seen.append(part)
            return ' | '.join(seen)

    if 'const' in schema:
        value = schema['const']
        if isinstance(value, str):
            return f"'{value}'"
        if value is None:
            return 'null'
        return str(value)

    if 'enum' in schema:
        enum_parts: list[str] = []
        for value in schema['enum']:
            if value is None:
                enum_parts.append('null')
                continue
            if isinstance(value, str):
                enum_parts.append(f"'{value}'")
                continue
            enum_parts.append(str(value))
        return ' | '.join(enum_parts)

    schema_type = schema.get('type')
    if schema_type == 'string':
        return 'string'
    if schema_type in {'integer', 'number'}:
        return 'number'
    if schema_type == 'boolean':
        return 'boolean'
    if schema_type == 'null':
        return 'null'

    if schema_type == 'array':
        item_type = _json_schema_type_to_ts(schema.get('items', {}), defs)
        return f'{item_type}[]'

    if schema_type == 'object':
        additional = schema.get('additionalProperties')
        if isinstance(additional, dict):
            return f'Record<string, {_json_schema_type_to_ts(additional, defs)}>'
        props = schema.get('properties')
        if not isinstance(props, dict) or not props:
            return 'Record<string, unknown>'
        required = set(schema.get('required', []))
        fields: list[str] = []
        for name, prop_schema in props.items():
            optional = '' if name in required else '?'
            fields.append(f'{name}{optional}: {_json_schema_type_to_ts(prop_schema, defs)}')
        return '{ ' + '; '.join(fields) + ' }'

    return 'unknown'


def _schema_to_ts_declaration(name: str, schema: dict[str, Any], defs: dict[str, Any]) -> str:
    if 'enum' in schema or 'const' in schema:
        return f'export type {name} = {_json_schema_type_to_ts(schema, defs)};'

    if schema.get('type') != 'object' and 'properties' not in schema:
        return f'export type {name} = {_json_schema_type_to_ts(schema, defs)};'

    properties: dict[str, Any] = schema.get('properties', {})
    model_cls = MODEL_REGISTRY.get(name)
    required = set(model_cls.model_fields) if model_cls is not None else set(schema.get('required', []))
    lines = [f'export interface {name} {{']
    if not properties:
        lines.append('  [key: string]: unknown;')
    for field_name, field_schema in properties.items():
        optional = '' if field_name in required or 'const' in field_schema else '?'
        lines.append(f'  {field_name}{optional}: {_json_schema_type_to_ts(field_schema, defs)};')
    lines.append('}')
    return '\n'.join(lines)


def _emit_ref(
    ref_name: str,
    *,
    all_defs: dict[str, Any],
    top_level_names: set[str],
    emitted_defs: set[str],
    body: list[str],
) -> None:
    if ref_name in top_level_names or ref_name in emitted_defs:
        return
    if ref_name not in all_defs:
        return
    for dep_name in _collect_refs(all_defs[ref_name]):
        _emit_ref(
            dep_name,
            all_defs=all_defs,
            top_level_names=top_level_names,
            emitted_defs=emitted_defs,
            body=body,
        )
    emitted_defs.add(ref_name)
    body.append(_schema_to_ts_declaration(ref_name, all_defs[ref_name], all_defs))
    body.append('')


def _collect_refs(schema: dict[str, Any]) -> list[str]:
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


def _event_union_source() -> tuple[dict[str, Any], dict[str, Any]]:
    schema = TypeAdapter(BuildEvent).json_schema()
    return schema, schema.get('$defs', {})


def generate() -> str:
    header = [
        "// This file is auto-generated. Do not edit manually. Run 'just generate-build-stream-types' to regenerate.",
        '// Generated from backend/modules/compute/schemas.py',
        '',
    ]

    all_defs: dict[str, Any] = {}
    model_schemas: list[tuple[str, dict[str, Any]]] = []
    event_schema, event_defs = _event_union_source()
    all_defs.update(event_defs)

    for ts_name, model_cls in MODELS:
        schema = model_cls.model_json_schema(by_alias=True)
        all_defs.update(schema.get('$defs', {}))
        model_schemas.append((ts_name, schema))

    emitted_defs: set[str] = set()
    top_level_names = {name for name, _ in MODELS} | {'BuildEvent'}
    body: list[str] = []

    for ref_name in _collect_refs(event_schema):
        _emit_ref(
            ref_name,
            all_defs=all_defs,
            top_level_names=top_level_names,
            emitted_defs=emitted_defs,
            body=body,
        )

    mapping = event_schema.get('discriminator', {}).get('mapping', {})
    event_names = [ref.split('/')[-1] for ref in mapping.values()]
    for event_name in event_names:
        for ref_name in _collect_refs(all_defs[event_name]):
            _emit_ref(
                ref_name,
                all_defs=all_defs,
                top_level_names=top_level_names,
                emitted_defs=emitted_defs,
                body=body,
            )
        if event_name in emitted_defs:
            continue
        emitted_defs.add(event_name)
        body.append(_schema_to_ts_declaration(event_name, all_defs[event_name], all_defs))
        body.append('')
    body.append(f'export type BuildEvent = {" | ".join(event_names)};')
    body.append('')

    for ts_name, schema in model_schemas:
        for ref_name in _collect_refs(schema):
            _emit_ref(
                ref_name,
                all_defs=all_defs,
                top_level_names=top_level_names,
                emitted_defs=emitted_defs,
                body=body,
            )
        body.append(_schema_to_ts_declaration(ts_name, schema, all_defs))
        body.append('')

    return '\n'.join(header + body)


def main() -> None:
    content = generate()
    check = '--check' in sys.argv[1:]
    if check:
        prettier = subprocess.run(
            ['bun', 'x', 'prettier', '--parser', 'typescript'],
            input=content,
            capture_output=True,
            text=True,
            check=True,
            cwd=OUTPUT_PATH.parents[3],
        )
        content = prettier.stdout
    existing = OUTPUT_PATH.read_text(encoding='utf-8') if OUTPUT_PATH.exists() else None
    if check:
        if existing == content:
            print(f'{OUTPUT_PATH} is up to date')
            return
        print(f'{OUTPUT_PATH} is stale. Run just generate-build-stream-types')
        raise SystemExit(1)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(content, encoding='utf-8')
    print(f'Generated {OUTPUT_PATH}')


if __name__ == '__main__':
    main()
