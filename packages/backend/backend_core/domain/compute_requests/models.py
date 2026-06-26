from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from google.protobuf import descriptor as proto_descriptor, json_format, message, struct_pb2

from backend_core.domain.analysis.step_types import normalize_step_type
from dataforge_protocol import analysis_pb2, compute_pb2, datasource_pb2, enums_pb2

_PROTO_INT64_FIELD_TYPES = {
    proto_descriptor.FieldDescriptor.TYPE_INT64,
    proto_descriptor.FieldDescriptor.TYPE_UINT64,
    proto_descriptor.FieldDescriptor.TYPE_SINT64,
    proto_descriptor.FieldDescriptor.TYPE_FIXED64,
    proto_descriptor.FieldDescriptor.TYPE_SFIXED64,
}


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


def _optional_payload_dict(payload: dict[str, object], key: str) -> dict[str, object] | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f'{key} must be an object')
    return cast(dict[str, object], value)


def _enum_name_from_token(enum_descriptor: Any, value: object) -> object:
    if not isinstance(value, str) or value in enum_descriptor.values_by_name:
        return value
    for enum_value in enum_descriptor.values:
        token = enum_value.GetOptions().Extensions[cast(Any, enums_pb2.dataforge_token)]
        if token == value:
            return enum_value.name
    return value


def _enum_number_from_token(enum_descriptor: Any, value: object, *, field_name: str) -> int:
    enum_name = _enum_name_from_token(enum_descriptor, value)
    if not isinstance(enum_name, str):
        raise ValueError(f'{field_name} must be a string enum token')
    try:
        return cast(int, enum_descriptor.values_by_name[enum_name].number)
    except KeyError as exc:
        raise ValueError(f'{field_name} is invalid') from exc


def _tokens_to_proto_json(value: object, message_descriptor: Any) -> object:
    if message_descriptor.full_name == 'google.protobuf.Struct':
        return value
    if message_descriptor.full_name == 'dataforge.runtime.FilterValue':
        return _filter_value_for_proto(value)
    if isinstance(value, list):
        return [_tokens_to_proto_json(item, message_descriptor) for item in value]
    if not isinstance(value, Mapping):
        return value

    result: dict[str, object] = {}
    for raw_key, raw_item in value.items():
        key = str(raw_key)
        field = message_descriptor.fields_by_name.get(key)
        if field is None:
            result[key] = raw_item
            continue
        is_map_field = field.message_type is not None and field.message_type.GetOptions().map_entry
        if field.is_repeated and not is_map_field:
            if raw_item is None:
                continue
            if not isinstance(raw_item, Sequence) or isinstance(raw_item, str | bytes | bytearray):
                raise ValueError(f'{key} must be a list')
            if field.type == proto_descriptor.FieldDescriptor.TYPE_MESSAGE:
                result[key] = [_tokens_to_proto_json(item, field.message_type) for item in raw_item]
            elif field.type == proto_descriptor.FieldDescriptor.TYPE_ENUM:
                result[key] = [_enum_name_from_token(field.enum_type, item) for item in raw_item]
            else:
                result[key] = list(raw_item)
            continue
        if field.type == proto_descriptor.FieldDescriptor.TYPE_MESSAGE:
            if raw_item is not None:
                result[key] = _tokens_to_proto_json(raw_item, field.message_type)
        elif field.type == proto_descriptor.FieldDescriptor.TYPE_ENUM:
            result[key] = _enum_name_from_token(field.enum_type, raw_item)
        else:
            result[key] = raw_item
    return result


def _enum_token(enum_descriptor: Any, value: int) -> str:
    value_descriptor = enum_descriptor.values_by_number[value]
    return cast(str, value_descriptor.GetOptions().Extensions[cast(Any, enums_pb2.dataforge_token)])


def _proto_scalar_to_payload(raw_item: object, field: Any) -> object:
    if field.type in _PROTO_INT64_FIELD_TYPES and isinstance(raw_item, str):
        return int(raw_item)
    return raw_item


def _proto_json_to_tokens(value: object, message_descriptor: Any) -> object:
    if message_descriptor.full_name == 'google.protobuf.Struct':
        return _normalize_struct_decode_value(value)
    if isinstance(value, list):
        return [_proto_json_to_tokens(item, message_descriptor) for item in value]
    if not isinstance(value, Mapping):
        return value

    result: dict[str, object] = {}
    for raw_key, raw_item in value.items():
        key = str(raw_key)
        field = message_descriptor.fields_by_name.get(key)
        if field is None:
            result[key] = raw_item
            continue
        is_map_field = field.message_type is not None and field.message_type.GetOptions().map_entry
        if field.is_repeated and not is_map_field:
            if field.type == proto_descriptor.FieldDescriptor.TYPE_MESSAGE:
                result[key] = [_proto_json_to_tokens(item, field.message_type) for item in cast(list[object], raw_item)]
            elif field.type == proto_descriptor.FieldDescriptor.TYPE_ENUM:
                result[key] = [
                    _enum_token(field.enum_type, field.enum_type.values_by_name[item].number)
                    if isinstance(item, str) and item in field.enum_type.values_by_name
                    else _enum_token(field.enum_type, item)
                    if isinstance(item, int)
                    else item
                    for item in cast(list[object], raw_item)
                ]
            else:
                result[key] = [_proto_scalar_to_payload(item, field) for item in cast(list[object], raw_item)]
            continue
        if field.type == proto_descriptor.FieldDescriptor.TYPE_MESSAGE:
            result[key] = _proto_json_to_tokens(raw_item, field.message_type)
        elif field.type == proto_descriptor.FieldDescriptor.TYPE_ENUM:
            if isinstance(raw_item, str) and raw_item in field.enum_type.values_by_name:
                result[key] = _enum_token(field.enum_type, field.enum_type.values_by_name[raw_item].number)
            elif isinstance(raw_item, int):
                result[key] = _enum_token(field.enum_type, raw_item)
            else:
                result[key] = raw_item
        else:
            result[key] = _proto_scalar_to_payload(raw_item, field)
    return result


def _message_to_payload(value: message.Message) -> dict[str, object]:
    decoded = json_format.MessageToDict(value, preserving_proto_field_name=True)
    tokenized = _proto_json_to_tokens(decoded, value.DESCRIPTOR)
    if not isinstance(tokenized, dict):
        raise ValueError(f'{value.DESCRIPTOR.full_name} must decode to an object')
    return cast(dict[str, object], tokenized)


def _filter_value_for_proto(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Mapping):
        field_names = set(analysis_pb2.FilterValue.DESCRIPTOR.fields_by_name)
        json_names = {field.json_name for field in analysis_pb2.FilterValue.DESCRIPTOR.fields}
        if not any(str(key) in field_names or str(key) in json_names for key in value):
            raise ValueError('filter value object must use a FilterValue oneof field')
        return dict(value)
    if isinstance(value, bool):
        return {'bool_value': value}
    if isinstance(value, int | float) and not isinstance(value, bool):
        return {'number_value': value}
    if isinstance(value, list):
        if not all(isinstance(item, str) for item in value):
            raise ValueError('filter list values must contain only strings')
        return {'string_values': {'values': value}}
    if isinstance(value, str):
        return {'string_value': value}
    raise ValueError(f'Unsupported filter value type: {type(value).__name__}')


def _is_wrapped_step_config(config: Mapping[str, object]) -> bool:
    if len(config) != 1:
        return False
    key = next(iter(config))
    value = config[key]
    return key in analysis_pb2.StepConfig.DESCRIPTOR.fields_by_name and isinstance(value, Mapping)


def _wrap_step_config(step_type: object, config: object) -> object:
    if not isinstance(step_type, str) or not isinstance(config, Mapping):
        return config
    normalized_step_type = normalize_step_type(step_type)
    config_fields = analysis_pb2.StepConfig.DESCRIPTOR.fields_by_name
    if _is_wrapped_step_config(cast(Mapping[str, object], config)):
        return dict(config)
    if normalized_step_type not in config_fields:
        return dict(config)
    return {normalized_step_type: dict(config)}


def _pipeline_payload_for_proto(payload: dict[str, object]) -> dict[str, object]:
    pipeline = dict(payload)
    tabs = pipeline.get('tabs')
    if not isinstance(tabs, list):
        return pipeline
    proto_tabs: list[object] = []
    for tab in tabs:
        if not isinstance(tab, Mapping):
            proto_tabs.append(tab)
            continue
        proto_tab = dict(tab)
        steps = proto_tab.get('steps')
        if isinstance(steps, list):
            proto_steps: list[object] = []
            for step in steps:
                if not isinstance(step, Mapping):
                    proto_steps.append(step)
                    continue
                proto_step = dict(step)
                raw_step_type = proto_step.get('step_type') or proto_step.get('type')
                proto_step['step_type'] = _enum_number_from_token(enums_pb2.StepType.DESCRIPTOR, raw_step_type, field_name='step_type')
                proto_step['config'] = _wrap_step_config(raw_step_type, proto_step.get('config', {}))
                proto_steps.append(proto_step)
            proto_tab['steps'] = proto_steps
        proto_tabs.append(proto_tab)
    pipeline['tabs'] = proto_tabs
    return pipeline


def _parse_proto_message[ProtoMessageT: message.Message](message_type: type[ProtoMessageT], payload: dict[str, object]) -> ProtoMessageT:
    proto_json = _tokens_to_proto_json(payload, message_type.DESCRIPTOR)
    return cast(ProtoMessageT, json_format.ParseDict(cast(dict[str, object], proto_json), message_type()))


def _analysis_pipeline_from_payload(payload: dict[str, object]) -> analysis_pb2.AnalysisPipelinePayload:
    return _parse_proto_message(analysis_pb2.AnalysisPipelinePayload, _pipeline_payload_for_proto(_required_payload_dict(payload, 'analysis_pipeline')))


def _optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f'{key} must be a string')
    return value


def _required_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f'{key} must be an integer')
    return value


def _required_proto_enum(enum_descriptor: Any, payload: dict[str, object], key: str) -> Any:
    return _enum_number_from_token(enum_descriptor, payload.get(key), field_name=key)


def _set_optional_string(message_value: message.Message, field_name: str, value: str | None) -> None:
    if value is not None:
        setattr(message_value, field_name, value)


def _step_preview_command(payload: dict[str, object]) -> compute_pb2.StepPreviewCommand:
    command = compute_pb2.StepPreviewCommand(
        target_step_id=_required_payload_str(payload, 'target_step_id'),
        analysis_pipeline=_analysis_pipeline_from_payload(payload),
        row_limit=_required_int(payload, 'row_limit'),
        page=_required_int(payload, 'page'),
    )
    _set_optional_string(command, 'analysis_id', _optional_str(payload, 'analysis_id'))
    _set_optional_string(command, 'tab_id', _optional_str(payload, 'tab_id'))
    if isinstance(payload.get('engine_identity'), dict):
        command.engine_identity.CopyFrom(_engine_identity_from_payload(_required_payload_dict(payload, 'engine_identity')))
    resource_config = _resource_config_from_payload(payload.get('resource_config'))
    if resource_config is not None:
        command.resource_config.CopyFrom(resource_config)
    return command


def _step_schema_command(payload: dict[str, object]) -> compute_pb2.StepSchemaCommand:
    command = compute_pb2.StepSchemaCommand(
        target_step_id=_required_payload_str(payload, 'target_step_id'),
        analysis_pipeline=_analysis_pipeline_from_payload(payload),
    )
    _set_optional_string(command, 'analysis_id', _optional_str(payload, 'analysis_id'))
    _set_optional_string(command, 'tab_id', _optional_str(payload, 'tab_id'))
    return command


def _step_row_count_command(payload: dict[str, object]) -> compute_pb2.StepRowCountCommand:
    command = compute_pb2.StepRowCountCommand(
        target_step_id=_required_payload_str(payload, 'target_step_id'),
        analysis_pipeline=_analysis_pipeline_from_payload(payload),
    )
    _set_optional_string(command, 'analysis_id', _optional_str(payload, 'analysis_id'))
    _set_optional_string(command, 'tab_id', _optional_str(payload, 'tab_id'))
    return command


def _download_command(payload: dict[str, object]) -> compute_pb2.DownloadCommand:
    command = compute_pb2.DownloadCommand(
        target_step_id=_required_payload_str(payload, 'target_step_id'),
        analysis_pipeline=_analysis_pipeline_from_payload(payload),
        format=_required_proto_enum(enums_pb2.ExportFormat.DESCRIPTOR, payload, 'format'),
        filename=_required_payload_str(payload, 'filename'),
    )
    _set_optional_string(command, 'analysis_id', _optional_str(payload, 'analysis_id'))
    _set_optional_string(command, 'tab_id', _optional_str(payload, 'tab_id'))
    return command


def _export_command(payload: dict[str, object]) -> compute_pb2.ExportCommand:
    command = compute_pb2.ExportCommand(
        target_step_id=_required_payload_str(payload, 'target_step_id'),
        analysis_pipeline=_analysis_pipeline_from_payload(payload),
        format=_required_proto_enum(enums_pb2.ExportFormat.DESCRIPTOR, payload, 'format'),
        filename=_required_payload_str(payload, 'filename'),
        destination=_required_proto_enum(enums_pb2.ExportDestination.DESCRIPTOR, payload, 'destination'),
    )
    _set_optional_string(command, 'analysis_id', _optional_str(payload, 'analysis_id'))
    _set_optional_string(command, 'tab_id', _optional_str(payload, 'tab_id'))
    _set_optional_string(command, 'result_id', _optional_str(payload, 'result_id'))
    iceberg_options = _optional_payload_dict(payload, 'iceberg_options')
    if iceberg_options is not None:
        command.iceberg_options.CopyFrom(_parse_proto_message(compute_pb2.IcebergExportOptions, iceberg_options))
    return command


def _datasource_command(kind: enums_pb2.ComputeRequestKind, payload: dict[str, object]) -> datasource_pb2.DatasourceCommand:
    command = datasource_pb2.DatasourceCommand()
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE:
        command.create_file.CopyFrom(_parse_proto_message(datasource_pb2.CreateFileDatasourceCommand, payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE:
        command.create_database.CopyFrom(_parse_proto_message(datasource_pb2.CreateDatabaseDatasourceCommand, payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_CREATE_ICEBERG_DATASOURCE:
        command.create_iceberg.CopyFrom(_parse_proto_message(datasource_pb2.CreateIcebergDatasourceCommand, payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE:
        command.ingest.CopyFrom(_parse_proto_message(datasource_pb2.IngestDatasourceCommand, payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA:
        command.schema.CopyFrom(_parse_proto_message(datasource_pb2.DatasourceSchemaCommand, payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS:
        command.column_stats.CopyFrom(_parse_proto_message(datasource_pb2.DatasourceColumnStatsCommand, payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS:
        command.compare_iceberg_snapshots.CopyFrom(_parse_proto_message(datasource_pb2.CompareIcebergSnapshotsCommand, payload))
    else:
        raise ValueError(f'Unsupported datasource compute request kind: {compute_request_kind_name(kind)}')
    return command


def _command_from_payload(kind: enums_pb2.ComputeRequestKind, payload: dict[str, object]) -> compute_pb2.ComputeCommand:
    command = compute_pb2.ComputeCommand()
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW:
        command.preview.CopyFrom(_step_preview_command(payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA:
        command.schema.CopyFrom(_step_schema_command(payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT:
        command.row_count.CopyFrom(_step_row_count_command(payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_DOWNLOAD:
        command.download.CopyFrom(_download_command(payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_EXPORT:
        command.export.CopyFrom(_export_command(payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_SPAWN_ENGINE:
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
        command.datasource.CopyFrom(_datasource_command(kind, payload))
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
    envelope.command.CopyFrom(_command_from_payload(kind, payload))
    return envelope


def _datasource_result(kind: enums_pb2.ComputeRequestKind, payload: dict[str, object]) -> datasource_pb2.DatasourceResult:
    result = datasource_pb2.DatasourceResult()
    if 'error' in payload:
        result.error.CopyFrom(_parse_proto_message(datasource_pb2.DatasourceErrorResult, payload))
    elif kind in {
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_ICEBERG_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE,
    }:
        result.datasource.CopyFrom(_parse_proto_message(datasource_pb2.DataSourceRecord, payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA:
        result.schema.CopyFrom(_parse_proto_message(datasource_pb2.SchemaInfo, payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS:
        result.column_stats.CopyFrom(_parse_proto_message(datasource_pb2.ColumnStatsResult, payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS:
        result.snapshot_compare.CopyFrom(_parse_proto_message(datasource_pb2.SnapshotCompareResult, payload))
    else:
        raise ValueError(f'Unsupported datasource response kind: {compute_request_kind_name(kind)}')
    return result


def datasource_result_from_payload(kind: enums_pb2.ComputeRequestKind, payload: dict[str, object]) -> datasource_pb2.DatasourceResult:
    return _datasource_result(kind, payload)


def _response_from_payload(kind: enums_pb2.ComputeRequestKind, payload: dict[str, object]) -> compute_pb2.ComputeResponse:
    response = compute_pb2.ComputeResponse()
    if kind == enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW:
        preview_payload = dict(payload)
        rows = preview_payload.pop('data', [])
        preview_payload['rows'] = rows
        response.preview.CopyFrom(_parse_proto_message(compute_pb2.StepPreviewResult, preview_payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA:
        response.schema.CopyFrom(_parse_proto_message(compute_pb2.StepSchemaResult, payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT:
        response.row_count.CopyFrom(_parse_proto_message(compute_pb2.StepRowCountResult, payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_EXPORT:
        response.export.CopyFrom(_parse_proto_message(compute_pb2.ExportResult, payload))
    elif kind in {
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_ICEBERG_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS,
        enums_pb2.COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS,
    }:
        response.datasource.CopyFrom(_datasource_result(kind, payload))
    else:
        response.dynamic_response.CopyFrom(dict_to_struct(payload))
    return response


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
    if status == enums_pb2.COMPUTE_REQUEST_STATUS_FAILED:
        envelope.response.dynamic_response.CopyFrom(dict_to_struct(payload or {}))
    else:
        envelope.response.CopyFrom(_response_from_payload(kind, payload or {}))
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
    command = envelope.command
    selected = command.WhichOneof('command')
    if selected is None:
        return struct_to_dict(envelope.payload)
    value = getattr(command, selected)
    if selected == 'datasource':
        datasource_command = cast(datasource_pb2.DatasourceCommand, value)
        datasource_field = datasource_command.WhichOneof('command')
        if datasource_field is None:
            return {}
        return _message_to_payload(getattr(datasource_command, datasource_field))
    return _message_to_payload(value)


def response_payload(envelope: compute_pb2.ComputeResponseEnvelope) -> dict[str, object]:
    response = envelope.response
    selected = response.WhichOneof('response')
    if selected is None:
        return struct_to_dict(envelope.payload)
    value = getattr(response, selected)
    payload = _message_to_payload(value)
    if selected == 'preview':
        rows = payload.pop('rows', [])
        payload['data'] = rows
        payload.setdefault('total_rows', 0)
    if selected == 'row_count':
        payload.setdefault('row_count', 0)
    if selected == 'datasource':
        result = cast(datasource_pb2.DatasourceResult, value)
        result_field = result.WhichOneof('result')
        if result_field is None:
            return {}
        datasource_payload = _message_to_payload(getattr(result, result_field))
        if result_field == 'datasource':
            for nullable_field in ('description', 'schema_cache', 'created_by_analysis_id', 'output_of_tab_id'):
                datasource_payload.setdefault(nullable_field, None)
        if result_field == 'column_stats':
            datasource_payload.setdefault('count', 0)
            datasource_payload.setdefault('null_count', 0)
            datasource_payload.setdefault('null_percentage', 0.0)
            histogram = datasource_payload.get('histogram')
            if isinstance(histogram, list):
                for bin_payload in histogram:
                    if isinstance(bin_payload, dict):
                        bin_payload.setdefault('start', 0.0)
                        bin_payload.setdefault('end', 0.0)
                        bin_payload.setdefault('count', 0)
        return datasource_payload
    return payload
