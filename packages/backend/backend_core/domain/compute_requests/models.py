from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from google.protobuf import json_format, struct_pb2

from dataforge_protocol import compute_pb2, enums_pb2


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


def dict_to_struct(payload: dict[str, object] | None) -> struct_pb2.Struct:
    normalized = _normalize_struct_encode_value(payload or {})
    encoded = json.loads(json.dumps(normalized, allow_nan=False, separators=(',', ':'), sort_keys=True))
    value = struct_pb2.Struct()
    value.update(encoded)
    return value


def struct_to_dict(payload: struct_pb2.Struct) -> dict[str, object]:
    decoded = _normalize_struct_decode_value(json_format.MessageToDict(payload, preserving_proto_field_name=True))
    if not isinstance(decoded, dict):
        raise ValueError('protobuf Struct payload must decode to an object')
    return cast(dict[str, object], decoded)


def _proto_enum_suffix(enum_type: Any, prefix: str, value: int) -> str:
    enum_name = enum_type.Name(value)
    suffix = enum_name.removeprefix(f'{prefix}_')
    if suffix == 'UNSPECIFIED' or suffix == enum_name:
        raise ValueError(f'Unsupported {prefix} enum value: {enum_name}')
    return suffix


def _validate_proto_enum(enum_type: Any, prefix: str, value: int) -> Any:
    _proto_enum_suffix(enum_type, prefix, value)
    return value


def compute_request_kind_name(kind: enums_pb2.ComputeRequestKind) -> str:
    return _proto_enum_suffix(enums_pb2.ComputeRequestKind, 'COMPUTE_REQUEST_KIND', kind).lower()


def compute_request_status_name(status: enums_pb2.ComputeRequestStatus) -> str:
    return _proto_enum_suffix(enums_pb2.ComputeRequestStatus, 'COMPUTE_REQUEST_STATUS', status).lower()


def kind_to_proto(kind: enums_pb2.ComputeRequestKind) -> Any:
    return _validate_proto_enum(enums_pb2.ComputeRequestKind, 'COMPUTE_REQUEST_KIND', kind)


def status_to_proto(status: enums_pb2.ComputeRequestStatus) -> Any:
    return _validate_proto_enum(enums_pb2.ComputeRequestStatus, 'COMPUTE_REQUEST_STATUS', status)


def kind_from_proto(value: int) -> enums_pb2.ComputeRequestKind:
    return _validate_proto_enum(enums_pb2.ComputeRequestKind, 'COMPUTE_REQUEST_KIND', value)


def status_from_proto(value: int) -> enums_pb2.ComputeRequestStatus:
    return _validate_proto_enum(enums_pb2.ComputeRequestStatus, 'COMPUTE_REQUEST_STATUS', value)


def _required_payload_str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{key} is required')
    return value


def _engine_identity_from_payload(payload: dict[str, object]) -> compute_pb2.EngineIdentity:
    scope = payload.get('scope')
    reuse_policy = payload.get('reuse_policy')
    if scope == 'analysis_interactive':
        identity = compute_pb2.EngineIdentity(scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE, analysis_id=_required_payload_str(payload, 'analysis_id'))
    elif scope == 'datasource_preview':
        identity = compute_pb2.EngineIdentity(scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW, datasource_id=_required_payload_str(payload, 'datasource_id'))
    elif scope == 'build':
        identity = compute_pb2.EngineIdentity(scope=enums_pb2.ENGINE_SCOPE_BUILD, build_id=_required_payload_str(payload, 'build_id'))
    else:
        raise ValueError('engine identity scope is invalid')
    if reuse_policy == 'shared':
        identity.reuse_policy = enums_pb2.ENGINE_REUSE_POLICY_SHARED
    elif reuse_policy == 'exclusive':
        identity.reuse_policy = enums_pb2.ENGINE_REUSE_POLICY_EXCLUSIVE
    else:
        raise ValueError('engine identity reuse_policy is invalid')
    return identity


def _read_int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    return None


def _resource_config_from_payload(payload: object) -> compute_pb2.EngineResourceConfig | None:
    if not isinstance(payload, dict):
        return None
    config = compute_pb2.EngineResourceConfig()
    for key in ('max_threads', 'max_memory_mb', 'streaming_chunk_size'):
        value = _read_int(payload, key)
        if value is not None:
            setattr(config, key, value)
    return config


def _lifecycle_command(payload: dict[str, object]) -> compute_pb2.EngineLifecycleCommand:
    command = compute_pb2.EngineLifecycleCommand(engine_identity=_engine_identity_from_payload(_required_payload_dict(payload, 'engine_identity')))
    resource_config = _resource_config_from_payload(payload.get('resource_config'))
    if resource_config is not None:
        command.resource_config.CopyFrom(resource_config)
    return command


def _required_payload_dict(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f'{key} is required')
    return cast(dict[str, object], value)


def _command_from_payload(kind: enums_pb2.ComputeRequestKind, payload: dict[str, object]) -> compute_pb2.ComputeCommand:
    command = compute_pb2.ComputeCommand()
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_SPAWN_ENGINE:
        command.spawn_engine.CopyFrom(_lifecycle_command(payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_CONFIGURE_ENGINE:
        command.configure_engine.CopyFrom(_lifecycle_command(payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE:
        command.shutdown_engine.CopyFrom(_lifecycle_command(payload))
    elif kind in {
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_ICEBERG_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS,
        enums_pb2.COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS,
    }:
        command.datasource_request.CopyFrom(dict_to_struct(payload))
    return command


def command_envelope(
    *,
    kind: enums_pb2.ComputeRequestKind,
    request_id: str,
    payload: dict[str, object],
) -> compute_pb2.ComputeCommandEnvelope:
    envelope = compute_pb2.ComputeCommandEnvelope(
        kind=kind_to_proto(kind),
        version=1,
        idempotency_key=request_id,
        correlation_id=request_id,
    )
    envelope.payload.CopyFrom(dict_to_struct(payload))
    envelope.command.CopyFrom(_command_from_payload(kind, payload))
    return envelope


def response_envelope(
    *,
    kind: enums_pb2.ComputeRequestKind,
    request_id: str,
    status: enums_pb2.ComputeRequestStatus,
    payload: dict[str, object] | None,
    error_message: str | None = None,
) -> compute_pb2.ComputeResponseEnvelope:
    envelope = compute_pb2.ComputeResponseEnvelope(
        kind=kind_to_proto(kind),
        version=1,
        correlation_id=request_id,
        status=status_to_proto(status),
    )
    envelope.payload.CopyFrom(dict_to_struct(payload or {}))
    envelope.response.dynamic_response.CopyFrom(dict_to_struct(payload or {}))
    if error_message is not None:
        envelope.error_message = error_message
    return envelope


def envelope_to_json(envelope: compute_pb2.ComputeCommandEnvelope | compute_pb2.ComputeResponseEnvelope) -> dict[str, object]:
    decoded = json_format.MessageToDict(envelope, preserving_proto_field_name=True)
    return cast(dict[str, object], decoded)


def command_envelope_from_json(payload: dict[str, object]) -> compute_pb2.ComputeCommandEnvelope:
    return cast(compute_pb2.ComputeCommandEnvelope, json_format.ParseDict(payload, compute_pb2.ComputeCommandEnvelope()))


def response_envelope_from_json(payload: dict[str, object]) -> compute_pb2.ComputeResponseEnvelope:
    return cast(compute_pb2.ComputeResponseEnvelope, json_format.ParseDict(payload, compute_pb2.ComputeResponseEnvelope()))


def command_payload(envelope: compute_pb2.ComputeCommandEnvelope) -> dict[str, object]:
    return struct_to_dict(envelope.payload)


def response_payload(envelope: compute_pb2.ComputeResponseEnvelope) -> dict[str, object]:
    return struct_to_dict(envelope.payload)
