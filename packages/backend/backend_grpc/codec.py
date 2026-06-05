from __future__ import annotations

import json
from typing import Any, cast

from backend_grpc.generated import common_pb2


def dict_to_struct(payload: dict[str, object] | None) -> common_pb2.JsonPayload:
    return common_pb2.JsonPayload(value_json=json.dumps(payload or {}, allow_nan=False, separators=(',', ':'), sort_keys=True))


def struct_to_dict(payload: common_pb2.JsonPayload) -> dict[str, object]:
    decoded = json.loads(payload.value_json or '{}')
    if not isinstance(decoded, dict):
        raise ValueError('gRPC JSON payload must decode to an object')
    return cast(dict[str, object], decoded)


def struct_field_to_dict(message: Any, field: str) -> dict[str, object] | None:
    if not message.HasField(field):
        return None
    return struct_to_dict(getattr(message, field))


def repeated_structs_to_dicts(values: Any) -> list[dict[str, object]]:
    return [struct_to_dict(value) for value in values]
