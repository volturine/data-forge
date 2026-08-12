from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from google.protobuf import json_format, struct_pb2


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_value(item) for item in value]
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, UUID):
        return str(value)
    return value


def dict_to_struct(payload: Mapping[str, object]) -> struct_pb2.Struct:
    value = _json_value(payload)
    if not isinstance(value, dict):
        raise TypeError("protobuf Struct payload must be an object")
    return json_format.ParseDict(value, struct_pb2.Struct())


def encode_json_bytes(payload: object) -> bytes:
    """Encode transport JSON without coercing integers into floats."""
    return json.dumps(_json_value(payload), separators=(",", ":")).encode()
