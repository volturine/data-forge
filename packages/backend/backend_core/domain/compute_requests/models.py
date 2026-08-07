from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from google.protobuf import json_format, message, struct_pb2

from backend_core.domain.analysis.step_types import normalize_step_type
from dataforge_protocol import analysis_pb2, compute_pb2, datasource_pb2, enums_pb2, errors_pb2


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
    return value.strip()


def _resource_id_for_scope(payload: dict[str, object], key: str) -> str:
    resource_id = _required_payload_str(payload, 'resource_id')
    scoped_id = _required_payload_str(payload, key)
    if resource_id != scoped_id:
        raise ValueError(f'resource_id must match {key}')
    return resource_id


def _engine_identity_from_payload(payload: dict[str, object]) -> compute_pb2.EngineIdentity:
    scope = payload.get('scope')
    reuse_policy = payload.get('reuse_policy')
    if scope == 'analysis_interactive':
        resource_id = _resource_id_for_scope(payload, 'analysis_id')
        identity = compute_pb2.EngineIdentity(scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE, analysis_id=resource_id, resource_id=resource_id)
    elif scope == 'datasource_preview':
        resource_id = _resource_id_for_scope(payload, 'datasource_id')
        identity = compute_pb2.EngineIdentity(scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW, datasource_id=resource_id, resource_id=resource_id)
    elif scope == 'build':
        resource_id = _resource_id_for_scope(payload, 'build_id')
        identity = compute_pb2.EngineIdentity(scope=enums_pb2.ENGINE_SCOPE_BUILD, build_id=resource_id, resource_id=resource_id)
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
    prefixed_value = f'{_enum_prefix(enum_descriptor)}_{value}'
    if prefixed_value in enum_descriptor.values_by_name:
        return prefixed_value
    for enum_value in enum_descriptor.values:
        options = enum_value.GetOptions()
        if not options.HasExtension(cast(Any, enums_pb2.dataforge_token)):
            continue
        token = options.Extensions[cast(Any, enums_pb2.dataforge_token)]
        if token == value:
            return enum_value.name
    return value


def _enum_prefix(enum_descriptor: Any) -> str:
    chars: list[str] = []
    for index, char in enumerate(enum_descriptor.name):
        if char.isupper() and index > 0:
            chars.append('_')
        chars.append(char.upper())
    return ''.join(chars)


def _enum_number_from_token(enum_descriptor: Any, value: object, *, field_name: str) -> int:
    enum_name = _enum_name_from_token(enum_descriptor, value)
    if not isinstance(enum_name, str):
        raise ValueError(f'{field_name} must be a string enum token')
    try:
        return cast(int, enum_descriptor.values_by_name[enum_name].number)
    except KeyError as exc:
        raise ValueError(f'{field_name} is invalid') from exc


def _enum_token_from_number(enum_descriptor: Any, value: int) -> str:
    value_descriptor = enum_descriptor.values_by_number[value]
    options = value_descriptor.GetOptions()
    return cast(str, options.Extensions[cast(Any, enums_pb2.dataforge_token)])


def _message_to_payload(value: message.Message) -> dict[str, object]:
    decoded = json_format.MessageToDict(
        value,
        preserving_proto_field_name=True,
        use_integers_for_enums=True,
    )
    if not isinstance(decoded, dict):
        raise ValueError(f'{value.DESCRIPTOR.full_name} must decode to an object')
    return cast(dict[str, object], decoded)


def _restore_int64(payload: dict[str, object], key: str) -> None:
    value = payload.get(key)
    if isinstance(value, str):
        payload[key] = int(value)


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
        datasource = proto_tab.get('datasource')
        if isinstance(datasource, Mapping):
            proto_datasource = dict(datasource)
            source_type = proto_datasource.get('source_type')
            if source_type is not None:
                proto_datasource['source_type'] = _enum_number_from_token(
                    enums_pb2.DataSourceType.DESCRIPTOR,
                    source_type,
                    field_name='source_type',
                )
            proto_tab['datasource'] = proto_datasource
        output = proto_tab.get('output')
        if isinstance(output, Mapping):
            proto_output = dict(output)
            proto_output['format'] = _enum_number_from_token(
                enums_pb2.ExportFormat.DESCRIPTOR,
                proto_output.get('format'),
                field_name='format',
            )
            if proto_output.get('datasource_type') is not None:
                proto_output['datasource_type'] = _enum_number_from_token(
                    enums_pb2.DataSourceType.DESCRIPTOR,
                    proto_output['datasource_type'],
                    field_name='datasource_type',
                )
            if proto_output.get('build_mode') is not None:
                proto_output['build_mode'] = _enum_number_from_token(
                    enums_pb2.BuildMode.DESCRIPTOR,
                    proto_output['build_mode'],
                    field_name='build_mode',
                )
            timeout_warning = proto_output.get('build_timeout_warning_ms')
            if timeout_warning is None or isinstance(timeout_warning, bool) or not isinstance(timeout_warning, (int, float)) or int(timeout_warning) <= 0:
                proto_output.pop('build_timeout_warning_ms', None)
            else:
                proto_output['build_timeout_warning_ms'] = int(timeout_warning)
            notification = proto_output.get('notification')
            if isinstance(notification, Mapping):
                proto_notification = dict(notification)
                proto_notification['method'] = _enum_number_from_token(
                    enums_pb2.NotificationMethod.DESCRIPTOR,
                    proto_notification.get('method'),
                    field_name='notification.method',
                )
                proto_output['notification'] = proto_notification
            if proto_output.get('notification') is None:
                proto_output.pop('notification', None)
            proto_tab['output'] = proto_output
        steps = proto_tab.get('steps')
        if isinstance(steps, list):
            proto_steps: list[object] = []
            for step in steps:
                if not isinstance(step, Mapping):
                    proto_steps.append(step)
                    continue
                proto_step = dict(step)
                raw_step_type = proto_step.get('step_type') or proto_step.get('type')
                proto_step.pop('type', None)
                proto_step['step_type'] = _enum_number_from_token(enums_pb2.StepType.DESCRIPTOR, raw_step_type, field_name='step_type')
                proto_step['config'] = _wrap_step_config(raw_step_type, proto_step.get('config', {}))
                proto_steps.append(proto_step)
            proto_tab['steps'] = proto_steps
        proto_tabs.append(proto_tab)
    pipeline['tabs'] = proto_tabs
    return pipeline


def _parse_proto_message[ProtoMessageT: message.Message](message_type: type[ProtoMessageT], payload: dict[str, object]) -> ProtoMessageT:
    return cast(ProtoMessageT, json_format.ParseDict(payload, message_type()))


def analysis_pipeline_from_payload(payload: dict[str, object]) -> analysis_pb2.AnalysisPipelinePayload:
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
        analysis_pipeline=analysis_pipeline_from_payload(payload),
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
        analysis_pipeline=analysis_pipeline_from_payload(payload),
    )
    _set_optional_string(command, 'analysis_id', _optional_str(payload, 'analysis_id'))
    _set_optional_string(command, 'tab_id', _optional_str(payload, 'tab_id'))
    return command


def _step_row_count_command(payload: dict[str, object]) -> compute_pb2.StepRowCountCommand:
    command = compute_pb2.StepRowCountCommand(
        target_step_id=_required_payload_str(payload, 'target_step_id'),
        analysis_pipeline=analysis_pipeline_from_payload(payload),
    )
    _set_optional_string(command, 'analysis_id', _optional_str(payload, 'analysis_id'))
    _set_optional_string(command, 'tab_id', _optional_str(payload, 'tab_id'))
    return command


def _download_command(payload: dict[str, object]) -> compute_pb2.DownloadCommand:
    command = compute_pb2.DownloadCommand(
        target_step_id=_required_payload_str(payload, 'target_step_id'),
        analysis_pipeline=analysis_pipeline_from_payload(payload),
        format=_required_proto_enum(enums_pb2.ExportFormat.DESCRIPTOR, payload, 'format'),
        filename=_required_payload_str(payload, 'filename'),
    )
    _set_optional_string(command, 'analysis_id', _optional_str(payload, 'analysis_id'))
    _set_optional_string(command, 'tab_id', _optional_str(payload, 'tab_id'))
    return command


def _export_command(payload: dict[str, object]) -> compute_pb2.ExportCommand:
    command = compute_pb2.ExportCommand(
        target_step_id=_required_payload_str(payload, 'target_step_id'),
        analysis_pipeline=analysis_pipeline_from_payload(payload),
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
        create_file_payload = dict(payload)
        create_file_payload['file_type'] = _enum_number_from_token(
            enums_pb2.DataSourceFileType.DESCRIPTOR,
            create_file_payload.get('file_type'),
            field_name='file_type',
        )
        command.create_file.CopyFrom(_parse_proto_message(datasource_pb2.CreateFileDatasourceCommand, create_file_payload))
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


def command_from_payload(kind: enums_pb2.ComputeRequestKind, payload: dict[str, object]) -> compute_pb2.ComputeCommand:
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
    command: compute_pb2.ComputeCommand,
) -> compute_pb2.ComputeCommandEnvelope:
    envelope = compute_pb2.ComputeCommandEnvelope(
        kind=kind_to_proto(kind),
        version=1,
        idempotency_key=request_id,
        correlation_id=request_id,
    )
    envelope.command.CopyFrom(command)
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
        result.datasource.CopyFrom(_parse_proto_message(datasource_pb2.DataSourceRecord, _datasource_record_payload_for_proto(payload)))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA:
        result.schema.CopyFrom(_parse_proto_message(datasource_pb2.SchemaInfo, payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS:
        result.column_stats.CopyFrom(_parse_proto_message(datasource_pb2.ColumnStatsResult, payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS:
        result.snapshot_compare.CopyFrom(_parse_proto_message(datasource_pb2.SnapshotCompareResult, _snapshot_compare_payload_for_proto(payload)))
    else:
        raise ValueError(f'Unsupported datasource response kind: {compute_request_kind_name(kind)}')
    return result


def datasource_result_from_payload(kind: enums_pb2.ComputeRequestKind, payload: dict[str, object]) -> datasource_pb2.DatasourceResult:
    return _datasource_result(kind, payload)


def _datasource_record_payload_for_proto(payload: dict[str, object]) -> dict[str, object]:
    proto_payload = dict(payload)
    # Computed enrichment not stored on the persisted record.
    proto_payload.pop('last_data_update', None)
    schema_cache = proto_payload.pop('schema_cache', None)
    if isinstance(schema_cache, Mapping):
        proto_payload['schema_info'] = dict(schema_cache)
    proto_payload['source_type'] = _enum_number_from_token(
        enums_pb2.DataSourceType.DESCRIPTOR,
        proto_payload.get('source_type'),
        field_name='source_type',
    )
    proto_payload['created_by'] = _enum_number_from_token(
        enums_pb2.DataSourceCreatedBy.DESCRIPTOR,
        proto_payload.get('created_by'),
        field_name='created_by',
    )
    return proto_payload


def _snapshot_compare_payload_for_proto(payload: dict[str, object]) -> dict[str, object]:
    proto_payload = dict(payload)
    raw_schema_diff = proto_payload.get('schema_diff')
    if not isinstance(raw_schema_diff, list):
        return proto_payload
    schema_diff: list[object] = []
    for raw_diff in raw_schema_diff:
        if not isinstance(raw_diff, Mapping):
            schema_diff.append(raw_diff)
            continue
        diff = dict(raw_diff)
        diff['status'] = _enum_number_from_token(
            enums_pb2.SchemaDiffStatus.DESCRIPTOR,
            diff.get('status'),
            field_name='schema_diff.status',
        )
        schema_diff.append(diff)
    proto_payload['schema_diff'] = schema_diff
    return proto_payload


def _schema_info_payload(message: datasource_pb2.SchemaInfo) -> dict[str, object]:
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


def _response_from_payload(kind: enums_pb2.ComputeRequestKind, payload: dict[str, object]) -> compute_pb2.ComputeResponse:
    response = compute_pb2.ComputeResponse()
    if 'error' in payload:
        error_payload = dict(payload)
        error_code = error_payload.get('error_code')
        if error_code is not None:
            error_payload['error_code'] = _enum_number_from_token(
                errors_pb2.ErrorCode.DESCRIPTOR,
                error_code,
                field_name='error_code',
            )
        response.error.CopyFrom(_parse_proto_message(compute_pb2.ComputeErrorResult, error_payload))
    elif kind == enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW:
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
        enums_pb2.COMPUTE_REQUEST_KIND_SPAWN_ENGINE,
        enums_pb2.COMPUTE_REQUEST_KIND_CONFIGURE_ENGINE,
    }:
        response.engine_status.CopyFrom(_parse_proto_message(compute_pb2.EngineStatusResult, payload))
    elif kind in {
        enums_pb2.COMPUTE_REQUEST_KIND_DOWNLOAD,
        enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE,
    }:
        response.ack.CopyFrom(_parse_proto_message(compute_pb2.ComputeAckResult, payload or {'success': True}))
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
        raise ValueError(f'Unsupported compute response kind: {compute_request_kind_name(kind)}')
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
    envelope.response.CopyFrom(_response_from_payload(kind, payload or ({'error': error_message} if error_message is not None else {})))
    if error_message is not None:
        envelope.error_message = error_message
    return envelope


def response_payload(envelope: compute_pb2.ComputeResponseEnvelope) -> dict[str, object]:
    response = envelope.response
    selected = response.WhichOneof('response')
    if selected is None:
        raise ValueError('Compute response envelope is missing typed response')
    value = getattr(response, selected)
    payload = _message_to_payload(value)
    if selected == 'preview':
        payload = cast(dict[str, object], _normalize_struct_decode_value(payload))
        rows = payload.pop('rows', [])
        payload['data'] = rows
        payload.setdefault('total_rows', 0)
        _restore_int64(payload, 'total_rows')
    if selected == 'row_count':
        payload.setdefault('row_count', 0)
        _restore_int64(payload, 'row_count')
    if selected == 'error':
        error = cast(compute_pb2.ComputeErrorResult, value)
        if error.HasField('error_code'):
            payload['error_code'] = errors_pb2.ErrorCode.Name(error.error_code).removeprefix('ERROR_CODE_')
    if selected == 'ack':
        return {}
    if selected == 'datasource':
        result = cast(datasource_pb2.DatasourceResult, value)
        result_field = result.WhichOneof('result')
        if result_field is None:
            return {}
        datasource_payload = _message_to_payload(getattr(result, result_field))
        if result_field == 'schema':
            return _schema_info_payload(result.schema)
        if result_field == 'datasource':
            datasource_payload.pop('schema_info', None)
            datasource_payload['schema_cache'] = _schema_info_payload(result.datasource.schema_info) if result.datasource.HasField('schema_info') else None
            datasource_payload['source_type'] = _enum_token_from_number(enums_pb2.DataSourceType.DESCRIPTOR, result.datasource.source_type)
            datasource_payload['created_by'] = _enum_token_from_number(enums_pb2.DataSourceCreatedBy.DESCRIPTOR, result.datasource.created_by)
            config = datasource_payload.get('config')
            if isinstance(config, dict):
                datasource_payload['config'] = _normalize_struct_decode_value(config)
            for nullable_field in ('description', 'created_by_analysis_id', 'output_of_tab_id'):
                datasource_payload.setdefault(nullable_field, None)
        if result_field == 'column_stats':
            datasource_payload.setdefault('count', 0)
            datasource_payload.setdefault('null_count', 0)
            datasource_payload.setdefault('null_percentage', 0.0)
            _restore_int64(datasource_payload, 'count')
            _restore_int64(datasource_payload, 'null_count')
            histogram = datasource_payload.get('histogram')
            if isinstance(histogram, list):
                for bin_payload in histogram:
                    if isinstance(bin_payload, dict):
                        bin_payload.setdefault('start', 0.0)
                        bin_payload.setdefault('end', 0.0)
                        bin_payload.setdefault('count', 0)
                        _restore_int64(bin_payload, 'count')
        if result_field == 'snapshot_compare':
            for key in ('row_count_a', 'row_count_b', 'row_count_delta'):
                _restore_int64(datasource_payload, key)
        return datasource_payload
    return payload
