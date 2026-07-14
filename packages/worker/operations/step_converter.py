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

from dataforge_protocol import analysis_pb2
from runtime.domain.analysis.step_types import (
    STEP_TYPES,
    ChartType,
    chart_type_for_step,
    get_step_type_label,
    is_step_type,
    normalize_step_type,
)


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


def _normalize_protocol_value_fields(step_type: str, config: dict[str, object]) -> dict[str, object]:
    if step_type == STEP_TYPES.filter.value:
        conditions = config.get("conditions")
        if not isinstance(conditions, list):
            return config
        normalized = dict(config)
        normalized["conditions"] = [
            {**condition, "value": _filter_value_payload(condition.get("value"))} if isinstance(condition, dict) and "value" in condition else condition
            for condition in conditions
        ]
        return normalized
    if step_type == STEP_TYPES.with_columns.value:
        expressions = config.get("expressions")
        if not isinstance(expressions, list):
            return config
        normalized = dict(config)
        normalized["expressions"] = [
            {**expression, "value": _filter_value_payload(expression.get("value"))} if isinstance(expression, dict) and "value" in expression else expression
            for expression in expressions
        ]
        return normalized
    if step_type == STEP_TYPES.fill_null.value and "value" in config:
        return {**config, "value": _filter_value_payload(config["value"])}
    return config


def _unwrap_step_config(step_type: str, config: object) -> dict[str, object]:
    if not isinstance(config, dict):
        return {}
    field_name = next(iter(config)) if len(config) == 1 else None
    if field_name is not None and field_name in analysis_pb2.StepConfig.DESCRIPTOR.fields_by_name:
        expected_field = normalize_step_type(step_type)
        if field_name != expected_field:
            raise ValueError(f"Step config '{field_name}' does not match step type '{step_type}'")
        nested = config[field_name]
        result = dict(nested) if isinstance(nested, dict) else {}
        return _normalize_protocol_value_fields(normalize_step_type(step_type), result)
    result = dict(config)
    config_field = analysis_pb2.StepConfig.DESCRIPTOR.fields_by_name.get(normalize_step_type(step_type))
    if config_field is not None and config_field.message_type is not None:
        unknown_fields = sorted(set(result) - set(config_field.message_type.fields_by_name))
        if unknown_fields:
            raise ValueError(f"Step config has unknown field(s): {', '.join(unknown_fields)}")
    return _normalize_protocol_value_fields(normalize_step_type(step_type), result)


def _execution_step_payload(payload: Mapping[str, object]) -> dict[str, object]:
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
    raw_deps = payload.get("depends_on")
    if raw_deps is not None and not (isinstance(raw_deps, list) and all(isinstance(dep, str) and dep.strip() for dep in raw_deps)):
        raise ValueError("Step depends_on must be a list of step ids")

    result = dict(payload)
    result.pop("step_type", None)
    result["type"] = normalize_step_type(raw_step_type)
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
    def from_mapping(cls, payload: Mapping[str, object]) -> "FrontendStep":
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
    raw_params = convert_config_to_params(normalized_type, config)

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

    return BackendStep(
        name=step_display_name(step_type, config),
        operation=normalized_type,
        params=params,
    )


def convert_config_to_params(operation: str, config: dict[str, object]) -> dict[str, object]:
    """Return canonical protocol config for worker-owned execution validation."""
    if not is_step_type(operation):
        raise ValueError(f"Unknown operation '{operation}'")
    return dict(config)
