from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from google.protobuf import json_format, struct_pb2, timestamp_pb2

from dataforge_protocol import common_pb2, enums_pb2


def _normalize_struct_decode_value(value: object) -> object:
    if isinstance(value, dict):
        return {key: _normalize_struct_decode_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_struct_decode_value(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _normalize_struct_encode_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _normalize_struct_encode_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_normalize_struct_encode_value(item) for item in value]
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def dict_to_struct(payload: dict[str, object] | None) -> common_pb2.JsonPayload:
    normalized = _normalize_struct_encode_value(payload or {})
    encoded = json.loads(json.dumps(normalized, allow_nan=False, separators=(',', ':'), sort_keys=True))
    value = struct_pb2.Struct()
    value.update(encoded)
    return common_pb2.JsonPayload(value=value)


def struct_to_dict(payload: common_pb2.JsonPayload) -> dict[str, object]:
    decoded = _normalize_struct_decode_value(json_format.MessageToDict(payload.value, preserving_proto_field_name=True))
    if not isinstance(decoded, dict):
        raise ValueError('gRPC JSON payload must decode to an object')
    return cast(dict[str, object], decoded)


def struct_field_to_dict(message: Any, field: str) -> dict[str, object] | None:
    if not message.HasField(field):
        return None
    return struct_to_dict(getattr(message, field))


def repeated_structs_to_dicts(values: Any) -> list[dict[str, object]]:
    return [struct_to_dict(value) for value in values]


def datetime_to_timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    timestamp = timestamp_pb2.Timestamp()
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    timestamp.FromDatetime(aware)
    return timestamp


def timestamp_to_datetime(value: timestamp_pb2.Timestamp) -> datetime:
    return value.ToDatetime(tzinfo=UTC)


def optional_timestamp_to_datetime(message: Any, field: str) -> datetime | None:
    if not message.HasField(field):
        return None
    return timestamp_to_datetime(getattr(message, field))


def enum_to_proto_value(prefix: str, value: str) -> Any:
    enum_name = f'{prefix}_{value.upper()}'
    return getattr(enums_pb2, enum_name)


def proto_value_to_enum_name(enum_type: Any, prefix: str, value: int) -> str:
    enum_name = enum_type.Name(value)
    suffix = enum_name.removeprefix(f'{prefix}_')
    if suffix == 'UNSPECIFIED' or suffix == enum_name:
        raise ValueError(f'Unsupported {prefix} enum value: {enum_name}')
    return suffix.lower()
