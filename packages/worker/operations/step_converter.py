"""Step Converter Module
Converts frontend pipeline step format to backend engine format.

Frontend format:
{
    "id": "uuid",
    "type": "filter",
    "config": {...},
    "depends_on": []
}

Backend format:
{
    "name": "Step Name",
    "operation": "filter",
    "params": {...}
}
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from google.protobuf import descriptor as proto_descriptor
from google.protobuf import json_format, message
from google.protobuf.json_format import ParseError
from protovalidate import ValidationError as ProtoValidationError
from protovalidate import Validator

from dataforge_protocol import analysis_pb2, enums_pb2
from operations.ai import ai_provider_name
from runtime.domain.analysis.step_types import (
    STEP_TYPES,
    ChartType,
    chart_type_for_step,
    get_step_type_label,
    is_step_type,
    normalize_step_type,
)
from runtime.domain.step_config_enums import (
    ChartAggregation,
    DeduplicateKeep,
    DisplayUnits,
    FillNullStrategy,
    FilterLogic,
    JoinHow,
    LegendPosition,
    NotificationMethod,
    PivotAggregateFunction,
    SortDirection,
)

logger = logging.getLogger(__name__)
_PROTO_VALIDATOR = Validator()
_PROTOCOL_CONFIG_DEFAULTS: dict[str, dict[str, object]] = {
    STEP_TYPES.chart.value: {
        "bins": 10,
        "aggregation": ChartAggregation.SUM.value,
        "group_sort_order": SortDirection.ASC.value,
        "stack_mode": "grouped",
        "area_opacity": 0.35,
        "sort_order": SortDirection.ASC.value,
        "y_axis_scale": "linear",
        "display_units": DisplayUnits.NONE.value,
        "decimal_places": 2,
        "legend_position": LegendPosition.RIGHT.value,
    },
    STEP_TYPES.notification.value: {"batch_size": 10},
    STEP_TYPES.ai.value: {
        "provider": ai_provider_name(enums_pb2.AI_PROVIDER_OLLAMA),
        "batch_size": 10,
        "max_retries": 3,
        "temperature": 0.7,
    },
}


def _enum_name_from_token(enum_descriptor: Any, value: object) -> object:
    if not isinstance(value, str) or value in enum_descriptor.values_by_name:
        return value
    for enum_value in enum_descriptor.values:
        options = enum_value.GetOptions()
        if options.HasExtension(cast(Any, enums_pb2.dataforge_token)) and options.Extensions[cast(Any, enums_pb2.dataforge_token)] == value:
            return enum_value.name
    return value


def _enum_token(enum_descriptor: Any, value: int) -> str:
    value_descriptor = enum_descriptor.values_by_number[value]
    return cast(str, value_descriptor.GetOptions().Extensions[cast(Any, enums_pb2.dataforge_token)])


def _filter_value_for_proto(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Mapping):
        field_names = set(analysis_pb2.FilterValue.DESCRIPTOR.fields_by_name)
        json_names = {field.json_name for field in analysis_pb2.FilterValue.DESCRIPTOR.fields}
        if not any(str(key) in field_names or str(key) in json_names for key in value):
            raise ValueError("filter value object must use a FilterValue oneof field")
        return dict(value)
    if isinstance(value, bool):
        return {"bool_value": value}
    if isinstance(value, int | float) and not isinstance(value, bool):
        return {"number_value": value}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        values = list(value)
        if not all(isinstance(item, str) for item in values):
            raise ValueError("filter list values must contain only strings")
        return {"string_values": {"values": values}}
    if isinstance(value, str):
        return {"string_value": value}
    raise ValueError(f"Unsupported filter value type: {type(value).__name__}")


def _tokens_to_proto_json(value: object, message_descriptor: Any) -> object:
    if message_descriptor.full_name == "google.protobuf.Struct":
        return value
    if message_descriptor.full_name == "dataforge.runtime.FilterValue":
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
                raise ValueError(f"{key} must be a list")
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


def _proto_json_to_tokens(value: object, message_descriptor: Any) -> object:
    if message_descriptor.full_name == "google.protobuf.Struct":
        return value
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
                result[key] = raw_item
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
            result[key] = raw_item
    return result


def _parse_proto_message[ProtoMessageT: message.Message](message_type: type[ProtoMessageT], payload: dict[str, object]) -> ProtoMessageT:
    proto_json = _tokens_to_proto_json(payload, message_type.DESCRIPTOR)
    try:
        parsed = cast(ProtoMessageT, json_format.ParseDict(cast(dict[str, object], proto_json), message_type()))
        _PROTO_VALIDATOR.validate(parsed)
        return parsed
    except ParseError as exc:
        raise ValueError(str(exc)) from exc
    except ProtoValidationError as exc:
        raise ValueError(_proto_validation_message(exc)) from exc


def _proto_validation_message(exc: ProtoValidationError) -> str:
    violations = exc.to_proto().violations
    messages: list[str] = []
    for violation in violations:
        field_path = ".".join(element.field_name for element in violation.field.elements if element.field_name)
        messages.append(f"{field_path}: {violation.message}" if field_path else violation.message)
    return "; ".join(messages) if messages else str(exc)


def _message_to_payload(value: message.Message) -> dict[str, object]:
    decoded = json_format.MessageToDict(value, preserving_proto_field_name=True)
    tokenized = _proto_json_to_tokens(decoded, value.DESCRIPTOR)
    if not isinstance(tokenized, dict):
        raise ValueError(f"{value.DESCRIPTOR.full_name} must decode to an object")
    return cast(dict[str, object], tokenized)


def _is_wrapped_step_config(config: Mapping[str, object]) -> bool:
    return _wrapped_step_config_field(config) is not None


def _wrapped_step_config_field(config: Mapping[str, object]) -> str | None:
    if len(config) != 1:
        return None
    field_name = next(iter(config))
    if field_name in analysis_pb2.StepConfig.DESCRIPTOR.fields_by_name and isinstance(config[field_name], Mapping):
        return field_name
    return None


def _step_config_descriptor(step_type: str) -> Any | None:
    normalized_step_type = normalize_step_type(step_type)
    field = analysis_pb2.StepConfig.DESCRIPTOR.fields_by_name.get(normalized_step_type)
    return field.message_type if field is not None else None


def _unwrapped_source_config(step_type: str, config: Mapping[str, object]) -> Mapping[str, object]:
    normalized_step_type = normalize_step_type(step_type)
    wrapped_field = _wrapped_step_config_field(config)
    if wrapped_field is None:
        return config
    if wrapped_field != normalized_step_type:
        raise ValueError(f"Step config field '{wrapped_field}' does not match step type '{step_type}'")
    wrapped_value = config[wrapped_field]
    return cast(Mapping[str, object], wrapped_value)


def _config_with_protocol_defaults(step_type: str, config: Mapping[str, object]) -> dict[str, object]:
    defaults = _PROTOCOL_CONFIG_DEFAULTS.get(normalize_step_type(step_type))
    if defaults is None:
        return dict(config)
    return {**defaults, **config}


def _wrap_step_config(step_type: str, config: Mapping[str, object]) -> dict[str, object]:
    normalized_step_type = normalize_step_type(step_type)
    if _is_wrapped_step_config(config):
        _unwrapped_source_config(step_type, config)
        return dict(config)
    if normalized_step_type not in analysis_pb2.StepConfig.DESCRIPTOR.fields_by_name:
        return dict(config)
    return {normalized_step_type: dict(config)}


def _field_source_key(source: Mapping[str, object], field: Any) -> str | None:
    if field.name in source:
        return cast(str, field.name)
    if field.json_name in source:
        return cast(str, field.json_name)
    return None


def _is_map_field(field: Any) -> bool:
    return field.message_type is not None and field.message_type.GetOptions().map_entry


def _enum_token_from_source(enum_descriptor: Any, value: object) -> object:
    enum_name = _enum_name_from_token(enum_descriptor, value)
    if isinstance(enum_name, str) and enum_name in enum_descriptor.values_by_name:
        return _enum_token(enum_descriptor, enum_descriptor.values_by_name[enum_name].number)
    if isinstance(enum_name, int):
        return _enum_token(enum_descriptor, enum_name)
    return value


def _preserve_explicit_default_config_fields(
    config_descriptor: Any | None,
    source_config: Mapping[str, object],
    decoded_config: dict[str, object],
) -> dict[str, object]:
    if config_descriptor is None:
        return decoded_config

    preserved = dict(decoded_config)
    for field_descriptor in config_descriptor.fields:
        source_key = _field_source_key(source_config, field_descriptor)
        if source_key is None or field_descriptor.name in preserved or field_descriptor.is_repeated or _is_map_field(field_descriptor):
            continue
        source_value = source_config[source_key]
        if field_descriptor.type == proto_descriptor.FieldDescriptor.TYPE_ENUM:
            preserved[field_descriptor.name] = _enum_token_from_source(field_descriptor.enum_type, source_value)
        elif field_descriptor.type != proto_descriptor.FieldDescriptor.TYPE_MESSAGE:
            preserved[field_descriptor.name] = source_value
    return preserved


def _unwrap_protocol_value_shapes(value: object) -> object:
    if isinstance(value, list):
        return [_unwrap_protocol_value_shapes(item) for item in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {"string_value"}:
        return value["string_value"]
    if set(value) == {"number_value"}:
        return value["number_value"]
    if set(value) == {"bool_value"}:
        return value["bool_value"]
    if set(value) == {"string_values"}:
        string_values = value["string_values"]
        if isinstance(string_values, dict) and isinstance(string_values.get("values"), list):
            return [_unwrap_protocol_value_shapes(item) for item in string_values["values"]]
    return {key: _unwrap_protocol_value_shapes(item) for key, item in value.items()}


def _unwrap_step_config(config: object) -> dict[str, object]:
    if not isinstance(config, dict) or len(config) != 1:
        unwrapped = _unwrap_protocol_value_shapes(config)
        return cast(dict[str, object], unwrapped) if isinstance(unwrapped, dict) else {}
    field_name = next(iter(config))
    if field_name in analysis_pb2.StepConfig.DESCRIPTOR.fields_by_name:
        unwrapped = _unwrap_protocol_value_shapes(config[field_name])
        return cast(dict[str, object], unwrapped) if isinstance(unwrapped, dict) else {}
    unwrapped = _unwrap_protocol_value_shapes(config)
    return cast(dict[str, object], unwrapped) if isinstance(unwrapped, dict) else {}


def _restore_service_config_shape(step_type: str, config: dict[str, object]) -> dict[str, object]:
    if step_type == STEP_TYPES.view.value and "row_limit" in config:
        restored = dict(config)
        restored["rowLimit"] = restored.pop("row_limit")
        return restored
    return config


def _protocol_step_payload(payload: Mapping[str, object]) -> dict[str, object]:
    raw_step_type = payload.get("step_type") or payload.get("type")
    if not isinstance(raw_step_type, str) or not raw_step_type.strip():
        raise ValueError("Step must have a type field")
    if not is_step_type(raw_step_type):
        raise ValueError(f"Unknown step type '{raw_step_type}'")

    raw_config = payload.get("config")
    if raw_config is None:
        config: dict[str, object] = {}
    elif isinstance(raw_config, Mapping):
        config = dict(raw_config)
    else:
        raise ValueError("Step config must be an object")

    chart_type = chart_type_for_step(raw_step_type)
    if chart_type is not None:
        existing_chart_type = config.get("chart_type")
        if isinstance(existing_chart_type, str) and existing_chart_type and existing_chart_type != chart_type.value:
            raise ValueError(f"chart_type '{existing_chart_type}' does not match step type '{raw_step_type}'")
        config["chart_type"] = chart_type.value
    config = _config_with_protocol_defaults(raw_step_type, config)

    raw_deps = payload.get("depends_on")
    if raw_deps is not None and not (isinstance(raw_deps, list) and all(isinstance(dep, str) and dep.strip() for dep in raw_deps)):
        raise ValueError("Step depends_on must be a list of step ids")

    proto_payload = dict(payload)
    proto_payload.pop("type", None)
    proto_payload["step_type"] = _enum_name_from_token(enums_pb2.StepType.DESCRIPTOR, raw_step_type)
    proto_payload["config"] = _wrap_step_config(raw_step_type, config)
    protocol_step = _parse_proto_message(analysis_pb2.AnalysisPipelineStep, cast(dict[str, object], proto_payload))
    result = _message_to_payload(protocol_step)
    protocol_step_type = result.pop("step_type", None)
    if isinstance(protocol_step_type, str):
        result["type"] = protocol_step_type
    source_config = _unwrapped_source_config(raw_step_type, config)
    unwrapped_config = _unwrap_step_config(result.get("config"))
    config_descriptor = _step_config_descriptor(raw_step_type)
    unwrapped_config = _preserve_explicit_default_config_fields(config_descriptor, source_config, unwrapped_config)
    result["config"] = _restore_service_config_shape(cast(str, result["type"]), unwrapped_config)
    return result


@dataclass(frozen=True, slots=True)
class FrontendStep:
    id: str
    type: str
    config: dict[str, object] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    is_applied: bool | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "FrontendStep":
        allowed_keys = {"id", "type", "step_type", "config", "depends_on", "is_applied"}
        unknown_keys = sorted(set(payload) - allowed_keys)
        if unknown_keys:
            raise ValueError(f"Step has unknown field(s): {', '.join(unknown_keys)}")

        protocol_payload = _protocol_step_payload(payload)

        step_type = protocol_payload.get("type")
        if not isinstance(step_type, str) or not step_type.strip():
            raise ValueError("Step must have a type field")

        step_id = protocol_payload.get("id")
        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError("Step must have an id field")

        raw_config = protocol_payload.get("config")
        if isinstance(raw_config, dict):
            config = raw_config
        else:
            config = {}

        raw_deps = protocol_payload.get("depends_on")
        if raw_deps is None:
            depends_on: tuple[str, ...] = ()
        elif isinstance(raw_deps, list) and all(isinstance(dep, str) and dep.strip() for dep in raw_deps):
            depends_on = tuple(raw_deps)
        else:
            raise ValueError("Step depends_on must be a list of step ids")

        raw_applied = protocol_payload.get("is_applied")
        if raw_applied is not None and not isinstance(raw_applied, bool):
            raise ValueError("Step is_applied must be a boolean")
        is_applied = raw_applied if isinstance(raw_applied, bool) else None

        return cls(
            id=step_id,
            type=step_type,
            config=config,
            depends_on=depends_on,
            is_applied=is_applied,
        )


@dataclass(frozen=True, slots=True)
class BackendStep:
    name: str
    operation: str
    params: dict[str, object]


def step_display_name(step_type: str, config: Mapping[str, object]) -> str:
    if step_type == STEP_TYPES.chart.value:
        chart_type = config.get("chart_type")
        if isinstance(chart_type, str) and chart_type:
            return get_step_type_label(f"plot_{chart_type}")
    return get_step_type_label(step_type)


def get_chart_type_for_step(step_type: str) -> ChartType | None:
    return chart_type_for_step(step_type)


def convert_step_format(
    frontend_step: Mapping[str, object] | FrontendStep,
) -> BackendStep:
    """Convert frontend step format to backend engine format."""
    parsed = frontend_step if isinstance(frontend_step, FrontendStep) else FrontendStep.from_mapping(frontend_step)
    step_type = parsed.type
    config = parsed.config
    chart_type = get_chart_type_for_step(step_type)
    if chart_type:
        config = {**config, "chart_type": chart_type}
    normalized_type = normalize_step_type(step_type)

    return BackendStep(
        name=step_display_name(step_type, config),
        operation=normalized_type,
        params=convert_config_to_params(normalized_type, config),
    )


def convert_filter_config(config: dict) -> dict:
    """Convert filter config from frontend format to backend format.

    Frontend: {conditions: [{column, operator, value, value_type?, compare_column?}], logic: "AND"}
    Backend: {conditions: [{column, operator, value, value_type, compare_column?}], logic: "AND"}

    Supports multiple conditions with AND/OR logic.
    Supports typed values (string, number, date, datetime, column) and NULL checks.
    """
    from operations.filter import FilterCondition

    return {
        "conditions": FilterCondition.normalize_many(config.get("conditions")),
        "logic": config.get("logic", FilterLogic.AND.value),
    }


def convert_groupby_config(config: dict) -> dict:
    """Convert groupby config from frontend to backend format."""
    return {
        "group_by": config.get("group_by", []),
        "aggregations": [
            {
                "column": agg.get("column"),
                "function": agg.get("function"),
                "alias": agg.get("alias"),
            }
            for agg in config.get("aggregations", [])
        ],
    }


def convert_join_config(config: dict) -> dict:
    """Convert join config from frontend to backend format.

    Frontend: {how, right_source, join_columns: [{left_column, right_column}], right_columns: [...], suffix}
    Backend: {right_source, join_columns, right_columns, how, suffix}
    """
    join_columns = config.get("join_columns", [])
    right_columns = config.get("right_columns", [])

    how = config.get("how", JoinHow.INNER.value)
    return {
        "right_source": config.get("right_source"),
        "join_columns": join_columns,
        "right_columns": right_columns,
        "how": how,
        "suffix": config.get("suffix", "_right"),
    }


def convert_fillnull_config(config: dict) -> dict:
    """Convert fill_null config from frontend to backend format.

    Frontend: {strategy, value, value_type, columns}
    Backend: {strategy, value, value_type, columns}

    Normalizes frontend strategy "value" to backend strategy "literal".
    """
    strategy = config.get("strategy", FillNullStrategy.LITERAL.value)
    return {
        "strategy": strategy,
        "value": config.get("value"),
        "value_type": config.get("value_type"),
        "columns": config.get("columns", []),
    }


def convert_pivot_config(config: dict) -> dict:
    """Convert pivot config from frontend to backend format.

    Frontend: {index, columns, values, aggregate_function} or {index, columns, values, aggregateFunction}
    Backend: {index, columns, values, aggregate_function}
    """
    return {
        "index": config.get("index"),
        "columns": config.get("columns"),
        "values": config.get("values"),
        "aggregate_function": config.get("aggregate_function", PivotAggregateFunction.FIRST.value),
    }


def convert_rename_config(config: dict) -> dict:
    """Convert rename config from frontend to backend format.

    Frontend: {column_mapping: {oldName: newName}}
    Backend: {mapping: {oldName: newName}}
    """
    mapping = config.get("column_mapping") or config.get("mapping", {})
    if isinstance(mapping, list):
        mapping = {item.get("from"): item.get("to") for item in mapping if item.get("from") and item.get("to")}
    return {"mapping": mapping}


def convert_sort_config(config: dict) -> dict:
    """Convert sort config from frontend to backend format.

    Frontend: [{column: 'col1', descending: false}, {column: 'col2', descending: true}]
    Backend: {columns: ['col1', 'col2'], descending: [false, true]}
    """
    if isinstance(config, list):
        columns = [rule.get("column") for rule in config if rule.get("column")]
        descending = [rule.get("descending", False) for rule in config if rule.get("column")]
        return {"columns": columns, "descending": descending}

    if "columns" in config:
        return config

    return {"columns": [], "descending": []}


def convert_deduplicate_config(config: dict) -> dict:
    """Convert deduplicate config from frontend to backend format.

    Frontend: {columns: [...], keep: 'first'}
    Backend: {subset: [...], keep: 'first'}
    """
    return {
        "subset": config.get("columns") or config.get("subset"),
        "keep": config.get("keep", DeduplicateKeep.FIRST.value),
    }


def convert_timeseries_config(config: dict) -> dict:
    """Convert timeseries config from frontend to backend format.

    Frontend: {column, operationType, newColumn, component, value, unit, column2}
    Backend: {column, operation_type, new_column, component, value, unit, column2}
    """
    return {
        "column": config.get("column"),
        "operation_type": config.get("operation_type"),
        "new_column": config.get("new_column"),
        "component": config.get("component"),
        "value": config.get("value"),
        "unit": config.get("unit"),
        "column2": config.get("column2"),
    }


def convert_string_transform_config(config: dict) -> dict:
    """Convert string_transform config from frontend to backend format.

    Frontend: {column, method, newColumn, pattern, replacement, start, end, delimiter, index, groupIndex}
    Backend: {column, method, new_column, pattern, replacement, start, end, delimiter, index, group_index}
    """
    return {
        "column": config.get("column"),
        "method": config.get("method"),
        "new_column": config.get("new_column") or config.get("column"),
        "pattern": config.get("pattern"),
        "replacement": config.get("replacement"),
        "start": config.get("start"),
        "end": config.get("end"),
        "delimiter": config.get("delimiter"),
        "index": config.get("index"),
        "group_index": config.get("group_index"),
    }


def convert_export_config(config: dict) -> dict:
    """Convert export config from frontend to backend format.

    Frontend: {format, filename, destination, iceberg_options}
    Backend: {format, filename, destination, iceberg_options}
    """
    return {
        "format": config.get("format"),
        "filename": config.get("filename"),
        "destination": config.get("destination"),
        "iceberg_options": config.get("iceberg_options"),
    }


def convert_union_by_name_config(config: dict) -> dict:
    """Convert union_by_name config from frontend to backend format.

    Frontend: {sources: [...], allow_missing: bool} or {sources: [...], allowMissing: bool}
    Backend: {sources: [...], allow_missing: bool}
    """
    return {
        "sources": config.get("sources", []),
        "allow_missing": config.get("allow_missing", True),
    }


def convert_plot_config(config: dict) -> dict:
    return {
        "chart_type": config.get("chart_type", "bar"),
        "x_column": config.get("x_column", ""),
        "y_column": config.get("y_column"),
        "bins": config.get("bins", 10),
        "aggregation": config.get("aggregation", ChartAggregation.SUM.value),
        "group_column": config.get("group_column"),
        "group_sort_by": config.get("group_sort_by"),
        "group_sort_order": config.get("group_sort_order", SortDirection.ASC.value),
        "group_sort_column": config.get("group_sort_column"),
        "stack_mode": config.get("stack_mode", "grouped"),
        "area_opacity": config.get("area_opacity", 0.35),
        "date_bucket": config.get("date_bucket"),
        "date_ordinal": config.get("date_ordinal"),
        "sort_by": config.get("sort_by"),
        "sort_order": config.get("sort_order", SortDirection.ASC.value),
        "sort_column": config.get("sort_column"),
        "x_axis_label": config.get("x_axis_label"),
        "y_axis_label": config.get("y_axis_label"),
        "y_axis_scale": config.get("y_axis_scale", "linear"),
        "y_axis_min": config.get("y_axis_min"),
        "y_axis_max": config.get("y_axis_max"),
        "display_units": config.get("display_units", DisplayUnits.NONE.value),
        "decimal_places": config.get("decimal_places", 2),
        "legend_position": config.get("legend_position", LegendPosition.RIGHT.value),
        "title": config.get("title"),
        "series_colors": config.get("series_colors", []),
        "overlays": config.get("overlays", []),
        "reference_lines": config.get("reference_lines", []),
        "pan_zoom_enabled": config.get("pan_zoom_enabled", False),
        "selection_enabled": config.get("selection_enabled", False),
        "area_selection_enabled": config.get("area_selection_enabled", False),
    }


def convert_ai_config(config: dict) -> dict:
    raw_options = config.get("request_options")
    # Parse string JSON to dict if needed (frontend sends textarea value as string)
    if isinstance(raw_options, str):
        raw_options = raw_options.strip() or None

    input_columns: list[str] = config.get("input_columns") or []

    result: dict[str, object] = {
        "provider": config.get("provider", ai_provider_name(enums_pb2.AI_PROVIDER_OLLAMA)),
        "model": config.get("model", "llama2"),
        "input_columns": input_columns,
        "output_column": config.get("output_column", "ai_result"),
        "error_column": config.get("error_column", "ai_error"),
        "prompt_template": config.get("prompt_template", "Classify this text: {{text}}"),
        "batch_size": config.get("batch_size", 10),
        "max_retries": config.get("max_retries", 3),
        "rate_limit_rpm": config.get("rate_limit_rpm"),
        "endpoint_url": config.get("endpoint_url"),
        "api_key": config.get("api_key"),
        "temperature": config.get("temperature", 0.7),
        "max_tokens": config.get("max_tokens"),
        "request_options": raw_options,
    }
    return result


def convert_notification_config(config: dict) -> dict:
    """Convert notification config — per-row UDF with column inputs."""
    input_columns: list[str] = config.get("input_columns") or []

    selected = config.get("subscriber_ids")
    recipients = config.get("recipient", "") or (",".join(str(cid) for cid in selected) if isinstance(selected, list) else "")

    return {
        "method": config.get("method", NotificationMethod.EMAIL.value),
        "recipient": recipients,
        "bot_token": config.get("bot_token", ""),
        "subscriber_ids": config.get("subscriber_ids") or [],
        "recipient_column": config.get("recipient_column", ""),
        "input_columns": input_columns,
        "output_column": config.get("output_column", "notification_status"),
        "message_template": config.get("message_template", "{{message}}"),
        "subject_template": config.get("subject_template", "Notification"),
        "batch_size": config.get("batch_size", 10),
    }


def _identity_config(config: dict) -> dict:
    return config


_CONVERTERS: dict[str, Callable[[dict], dict]] = {}


def config_converter(step_type: str) -> Callable[[Callable[[dict], dict]], Callable[[dict], dict]]:
    if not is_step_type(step_type):
        raise ValueError(f"Unknown step type '{step_type}'")

    def register(converter: Callable[[dict], dict]) -> Callable[[dict], dict]:
        _CONVERTERS[step_type] = converter
        return converter

    return register


for _step_type in (
    STEP_TYPES.datasource.value,
    STEP_TYPES.select.value,
    STEP_TYPES.drop.value,
    STEP_TYPES.unpivot.value,
    STEP_TYPES.explode.value,
    STEP_TYPES.sample.value,
    STEP_TYPES.limit.value,
    STEP_TYPES.topk.value,
    STEP_TYPES.view.value,
    STEP_TYPES.download.value,
    STEP_TYPES.expression.value,
    STEP_TYPES.with_columns.value,
):
    config_converter(_step_type)(_identity_config)


config_converter(STEP_TYPES.filter.value)(convert_filter_config)
config_converter(STEP_TYPES.groupby.value)(convert_groupby_config)
config_converter(STEP_TYPES.sort.value)(convert_sort_config)
config_converter(STEP_TYPES.rename.value)(convert_rename_config)
config_converter(STEP_TYPES.join.value)(convert_join_config)
config_converter(STEP_TYPES.deduplicate.value)(convert_deduplicate_config)
config_converter(STEP_TYPES.fill_null.value)(convert_fillnull_config)
config_converter(STEP_TYPES.pivot.value)(convert_pivot_config)
config_converter(STEP_TYPES.timeseries.value)(convert_timeseries_config)
config_converter(STEP_TYPES.string_transform.value)(convert_string_transform_config)
config_converter(STEP_TYPES.export.value)(convert_export_config)
config_converter(STEP_TYPES.union_by_name.value)(convert_union_by_name_config)
config_converter(STEP_TYPES.chart.value)(convert_plot_config)
config_converter(STEP_TYPES.ai.value)(convert_ai_config)
config_converter(STEP_TYPES.notification.value)(convert_notification_config)


def convert_config_to_params(operation: str, config: dict) -> dict:
    """Convert operation-specific config to executable params.

    Every executable operation must be registered explicitly. Falling through with
    raw config would make UI mistakes look valid until runtime, which breaks the
    pipeline builder's code-like fidelity contract.
    """
    converter = _CONVERTERS.get(operation)
    if converter is None:
        raise ValueError(f"Unknown operation '{operation}'")
    try:
        return converter(config)
    except Exception as e:
        logger.error(f"Error converting {operation} config: {e}", exc_info=True)
        raise
