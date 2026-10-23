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

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from google.protobuf import json_format

from dataforge_protocol import analysis_pb2
from runtime.domain.analysis.step_types import STEP_TYPES
from runtime.domain.domain_enums import domain_token


def analysis_pipeline_to_execution_payload(pipeline: analysis_pb2.AnalysisPipelinePayload) -> dict[str, object]:
    decoded = json_format.MessageToDict(pipeline, preserving_proto_field_name=True, use_integers_for_enums=True)
    if not isinstance(decoded, dict):
        raise ValueError("analysis pipeline must decode to an object")
    payload = cast(dict[str, object], decoded)
    tabs = payload.get("tabs")
    if not isinstance(tabs, list):
        return payload
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        datasource = tab.get("datasource")
        if isinstance(datasource, dict) and isinstance(datasource.get("source_type"), int):
            datasource["source_type"] = domain_token("DataSourceType", datasource["source_type"])
        output = tab.get("output")
        if isinstance(output, dict):
            # The protobuf JSON mapping renders int64 fields as strings.
            if "build_timeout_warning_ms" in output:
                output["build_timeout_warning_ms"] = int(output["build_timeout_warning_ms"])
            for field, enum_name in (
                ("format", "ExportFormat"),
                ("datasource_type", "DataSourceType"),
                ("build_mode", "BuildMode"),
            ):
                number = output.get(field)
                if isinstance(number, int):
                    output[field] = domain_token(enum_name, number)
            notification = output.get("notification")
            if isinstance(notification, dict) and isinstance(notification.get("method"), int):
                notification["method"] = domain_token("NotificationMethod", notification["method"])
        steps = tab.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_type = step.pop("step_type", None)
            if isinstance(step_type, int):
                token = domain_token("StepType", step_type)
                step["type"] = token
                step["config"] = _unwrap_step_config(token, step.get("config"))
    return payload


def _filter_value_payload(value: object) -> object:
    if not isinstance(value, dict):
        return value
    for field_name in ("string_value", "number_value", "bool_value"):
        if set(value) == {field_name}:
            return value[field_name]
    string_values = value.get("string_values")
    if set(value) == {"string_values"} and isinstance(string_values, dict):
        values = string_values.get("values")
        if isinstance(values, list):
            return values
    return value


def _normalize_item_values(config: dict[str, object], items_key: str) -> dict[str, object]:
    items = config.get(items_key)
    if not isinstance(items, list):
        return config
    normalized_items = [{**item, "value": _filter_value_payload(item.get("value"))} if isinstance(item, dict) and "value" in item else item for item in items]
    return {**config, items_key: normalized_items}


def _normalize_protocol_value_fields(step_type: str, config: dict[str, object]) -> dict[str, object]:
    if step_type == STEP_TYPES.filter.value:
        return _normalize_item_values(config, "conditions")
    if step_type == STEP_TYPES.with_columns.value:
        return _normalize_item_values(config, "expressions")
    if step_type == STEP_TYPES.fill_null.value and "value" in config:
        return {**config, "value": _filter_value_payload(config["value"])}
    return config


def _unwrap_step_config(step_type: str, config: object) -> dict[str, object]:
    if not isinstance(config, dict):
        return {}
    field_name = next(iter(config)) if len(config) == 1 else None
    if field_name is not None and field_name in analysis_pb2.StepConfig.DESCRIPTOR.fields_by_name:
        expected_field = STEP_TYPES.normalized(step_type)
        if field_name != expected_field:
            raise ValueError(f"Step config '{field_name}' does not match step type '{step_type}'")
        nested = config[field_name]
        result = dict(nested) if isinstance(nested, dict) else {}
        return _normalize_protocol_value_fields(STEP_TYPES.normalized(step_type), result)
    result = dict(config)
    config_field = analysis_pb2.StepConfig.DESCRIPTOR.fields_by_name.get(STEP_TYPES.normalized(step_type))
    if config_field is not None and config_field.message_type is not None:
        unknown_fields = sorted(set(result) - set(config_field.message_type.fields_by_name))
        if unknown_fields:
            raise ValueError(f"Step config has unknown field(s): {', '.join(unknown_fields)}")
    return _normalize_protocol_value_fields(STEP_TYPES.normalized(step_type), result)


def _execution_step_payload(payload: Mapping[str, object]) -> dict[str, object]:
    raw_step_type = payload.get("step_type") or payload.get("type")
    if not isinstance(raw_step_type, str) or not raw_step_type.strip():
        raise ValueError("Step must have a type field")
    if not STEP_TYPES.has(raw_step_type):
        raise ValueError(f"Unknown step type '{raw_step_type}'")

    raw_config = payload.get("config")
    if raw_config is None:
        config: dict[str, object] = {}
    elif isinstance(raw_config, Mapping):
        config = dict(raw_config)
    else:
        raise ValueError("Step config must be an object")

    chart_type = STEP_TYPES.chart_type(raw_step_type)
    if chart_type is not None:
        existing_chart_type = config.get("chart_type")
        if isinstance(existing_chart_type, str) and existing_chart_type and existing_chart_type != chart_type.value:
            raise ValueError(f"chart_type '{existing_chart_type}' does not match step type '{raw_step_type}'")
        config["chart_type"] = chart_type.value
    raw_deps = payload.get("depends_on")
    if raw_deps is not None and not (isinstance(raw_deps, list) and all(isinstance(dep, str) and dep.strip() for dep in raw_deps)):
        raise ValueError("Step depends_on must be a list of step ids")

    result = dict(payload)
    result.pop("step_type", None)
    result["type"] = STEP_TYPES.normalized(raw_step_type)
    result["config"] = _unwrap_step_config(raw_step_type, config)
    return result


@dataclass(frozen=True, slots=True)
class FrontendStep:
    id: str
    type: str
    config: dict[str, object] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    is_applied: bool | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> FrontendStep:
        allowed_keys = {"id", "type", "step_type", "config", "depends_on", "is_applied"}
        unknown_keys = sorted(set(payload) - allowed_keys)
        if unknown_keys:
            raise ValueError(f"Step has unknown field(s): {', '.join(unknown_keys)}")

        protocol_payload = _execution_step_payload(payload)

        step_type = protocol_payload.get("type")
        if not isinstance(step_type, str) or not step_type.strip():
            raise ValueError("Step must have a type field")

        step_id = protocol_payload.get("id")
        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError("Step must have an id field")

        raw_config = protocol_payload.get("config")
        config = raw_config if isinstance(raw_config, dict) else {}

        raw_deps = protocol_payload.get("depends_on")
        depends_on = tuple(raw_deps) if isinstance(raw_deps, list) else ()

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


def convert_step_format(
    frontend_step: Mapping[str, object] | FrontendStep,
) -> BackendStep:
    """Convert frontend step format to backend engine format."""
    parsed = frontend_step if isinstance(frontend_step, FrontendStep) else FrontendStep.from_mapping(frontend_step)
    step_type = parsed.type
    config = parsed.config
    chart_type = STEP_TYPES.chart_type(step_type)
    if chart_type:
        config = {**config, "chart_type": chart_type}
    normalized_type = STEP_TYPES.normalized(step_type)
    if not STEP_TYPES.has(normalized_type):
        raise ValueError(f"Unknown operation '{normalized_type}'")
    raw_params = dict(config)

    # Import after operation modules initialize: datasource operations depend on
    # this converter while the registry owns executable parameter validation.
    from operations import PARAM_MODELS

    params = (
        PARAM_MODELS[normalized_type]
        .model_validate(raw_params)
        .model_dump(
            mode="json",
            exclude_none=True,
        )
    )

    name = STEP_TYPES.label(step_type)
    if step_type == STEP_TYPES.chart.value and isinstance(config.get("chart_type"), str) and config["chart_type"]:
        name = STEP_TYPES.label(f"plot_{config['chart_type']}")

    return BackendStep(
        name=name,
        operation=normalized_type,
        params=params,
    )
