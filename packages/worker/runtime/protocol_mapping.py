from datetime import datetime
from typing import Any, cast

from google.protobuf import json_format, struct_pb2, timestamp_pb2

from dataforge_protocol import datasource_pb2, enums_pb2


def struct_to_dict(payload: struct_pb2.Struct) -> dict[str, object]:
    decoded = json_format.MessageToDict(payload, preserving_proto_field_name=True)
    if not isinstance(decoded, dict):
        raise ValueError("gRPC JSON payload must decode to an object")
    return cast(dict[str, object], decoded)


def optional_struct_to_dict(message: Any, field: str) -> dict[str, object] | None:
    return struct_to_dict(getattr(message, field)) if message.HasField(field) else None


def datetime_to_timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(value)
    return timestamp


def optional_timestamp_to_datetime(message: Any, field: str) -> datetime | None:
    return getattr(message, field).ToDatetime() if message.HasField(field) else None


def enum_to_proto_value(prefix: str, value: str) -> Any:
    return getattr(enums_pb2, f"{prefix}_{value.upper()}")


def proto_value_to_enum_name(enum_type: Any, prefix: str, value: int) -> str:
    enum_name = enum_type.Name(value)
    suffix = enum_name.removeprefix(f"{prefix}_")
    if suffix in {"UNSPECIFIED", enum_name}:
        raise ValueError(f"Unsupported {prefix} enum value: {enum_name}")
    return suffix.lower()


def schema_info_proto(payload: dict[str, object]) -> datasource_pb2.SchemaInfo:
    schema = datasource_pb2.SchemaInfo()
    raw_columns = payload.get("columns")
    if raw_columns is not None:
        if not isinstance(raw_columns, list):
            raise ValueError("schema columns must be a list")
        for raw_column in raw_columns:
            if not isinstance(raw_column, dict):
                raise ValueError("schema column must be an object")
            name = raw_column.get("name")
            dtype = raw_column.get("dtype")
            nullable = raw_column.get("nullable")
            if not isinstance(name, str) or not isinstance(dtype, str) or not isinstance(nullable, bool):
                raise ValueError("schema column requires name, dtype, and nullable")
            column = schema.columns.add(name=name, dtype=dtype, nullable=nullable)
            for key in ("sample_value", "description"):
                value = raw_column.get(key)
                if value is not None:
                    if not isinstance(value, str):
                        raise ValueError(f"schema column {key} must be a string")
                    setattr(column, key, value)
    row_count = payload.get("row_count")
    if row_count is not None:
        if isinstance(row_count, bool) or not isinstance(row_count, int):
            raise ValueError("row_count must be an integer")
        schema.row_count = row_count
    sheet_names = payload.get("sheet_names")
    if sheet_names is not None:
        if not isinstance(sheet_names, list) or not all(isinstance(item, str) for item in sheet_names):
            raise ValueError("schema sheet_names must be a list of strings")
        schema.sheet_names.extend(sheet_names)
    return schema


def schema_info_payload(value: datasource_pb2.SchemaInfo) -> dict[str, object]:
    columns: list[dict[str, object]] = []
    for column in value.columns:
        item: dict[str, object] = {"name": column.name, "dtype": column.dtype, "nullable": column.nullable}
        if column.HasField("sample_value"):
            item["sample_value"] = column.sample_value
        if column.HasField("description"):
            item["description"] = column.description
        columns.append(item)
    payload: dict[str, object] = {}
    if columns:
        payload["columns"] = columns
    if value.HasField("row_count"):
        payload["row_count"] = value.row_count
    if value.sheet_names:
        payload["sheet_names"] = list(value.sheet_names)
    return payload
