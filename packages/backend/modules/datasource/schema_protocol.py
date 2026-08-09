"""Canonical datasource schema protocol adapters.

Datasource schemas are owned by ``dataforge_protocol.datasource_pb2.SchemaInfo``.
These helpers bridge that protocol type to and from the JSON dicts stored in
``DataSource.schema_cache`` and exposed over REST and compute response payloads.
"""

from __future__ import annotations

from typing import cast

from dataforge_protocol import datasource_pb2


def schema_info_proto(payload: dict[str, object] | None) -> datasource_pb2.SchemaInfo:
    """Build a ``SchemaInfo`` message from a schema cache payload.

    The payload is the JSON dict persisted in ``DataSource.schema_cache`` (or
    carried in compute response payloads). Missing and ``null`` optional fields
    are treated as unset; malformed entries are skipped so stale cache rows
    degrade gracefully instead of raising.
    """
    schema = datasource_pb2.SchemaInfo()
    if not isinstance(payload, dict):
        return schema
    raw_columns = payload.get('columns')
    if isinstance(raw_columns, list):
        for raw_column in raw_columns:
            if not isinstance(raw_column, dict):
                continue
            name = raw_column.get('name')
            dtype = raw_column.get('dtype')
            nullable = raw_column.get('nullable')
            if not isinstance(name, str) or not isinstance(dtype, str) or not isinstance(nullable, bool):
                continue
            column = schema.columns.add(name=name, dtype=dtype, nullable=nullable)
            for key in ('sample_value', 'description'):
                value = raw_column.get(key)
                if isinstance(value, str):
                    setattr(column, key, value)
    row_count = payload.get('row_count')
    if isinstance(row_count, int) and not isinstance(row_count, bool):
        schema.row_count = row_count
    sheet_names = payload.get('sheet_names')
    if isinstance(sheet_names, list):
        schema.sheet_names.extend(name for name in sheet_names if isinstance(name, str))
    return schema


def schema_info_payload(message: datasource_pb2.SchemaInfo) -> dict[str, object]:
    """Serialize a ``SchemaInfo`` message to a schema cache payload.

    Optional fields are omitted when unset. Descriptions are excluded by the
    callers that persist the cache (they live in ``DataSourceColumnMetadata``),
    so this helper only carries values that are present on the message.
    """
    columns: list[dict[str, object]] = []
    for column in message.columns:
        column_payload: dict[str, object] = {
            'name': column.name,
            'dtype': column.dtype,
            'nullable': column.nullable,
        }
        if column.HasField('sample_value'):
            column_payload['sample_value'] = column.sample_value
        if column.HasField('description'):
            column_payload['description'] = column.description
        columns.append(column_payload)

    payload: dict[str, object] = {}
    if columns:
        payload['columns'] = columns
    if message.HasField('row_count'):
        payload['row_count'] = message.row_count
    if message.sheet_names:
        payload['sheet_names'] = list(message.sheet_names)
    return payload


def schema_info_response_payload(message: datasource_pb2.SchemaInfo) -> dict[str, object]:
    """Serialize a ``SchemaInfo`` message to the REST response shape.

    Unlike the cache payload, every column field is present — ``sample_value``
    and ``description`` are ``null`` when unset — matching the historical
    pydantic ``SchemaInfo`` response contract consumed by the frontend.
    """
    columns = [
        {
            'name': column.name,
            'dtype': column.dtype,
            'nullable': column.nullable,
            'sample_value': column.sample_value if column.HasField('sample_value') else None,
            'description': column.description if column.HasField('description') else None,
        }
        for column in message.columns
    ]
    return cast(
        dict[str, object],
        {
            'columns': columns,
            'row_count': message.row_count if message.HasField('row_count') else None,
            'sheet_names': list(message.sheet_names) if message.sheet_names else None,
        },
    )
