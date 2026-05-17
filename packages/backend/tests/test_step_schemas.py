import pytest

from modules.analysis.step_schemas import (
    SelectConfig,
    StringTransformConfig,
    TimeSeriesConfig,
    WithColumnsExprSchema,
    get_step_catalog,
    validate_step,
)


def _enum_values(schema: dict, field_name: str) -> list[str] | None:
    properties = schema.get("properties", {})
    field_schema = properties.get(field_name, {})
    if "enum" in field_schema:
        return field_schema["enum"]
    if "anyOf" in field_schema:
        for branch in field_schema["anyOf"]:
            if "enum" in branch:
                return branch["enum"]
            ref = branch.get("$ref")
            if isinstance(ref, str):
                resolved = schema.get("$defs", {}).get(ref.split("/")[-1], {})
                if "enum" in resolved:
                    return resolved["enum"]
    ref = field_schema.get("$ref")
    if isinstance(ref, str):
        resolved = schema.get("$defs", {}).get(ref.split("/")[-1], {})
        return resolved.get("enum")
    return None


def test_select_config_includes_cast_map_schema() -> None:
    schema = SelectConfig.model_json_schema()
    props = schema.get("properties", {})
    cast_map = props.get("cast_map", {})
    additional = cast_map.get("additionalProperties", {})
    enum_values = additional.get("enum")
    if enum_values is None:
        ref = additional.get("$ref")
        if isinstance(ref, str):
            enum_values = schema.get("$defs", {}).get(ref.split("/")[-1], {}).get("enum")
    assert cast_map.get("type") == "object"
    assert enum_values == [
        "Int64",
        "Float64",
        "Boolean",
        "String",
        "Utf8",
        "Date",
        "Datetime",
    ]


def test_with_columns_and_temporal_configs_use_shared_enums() -> None:
    with_columns_schema = WithColumnsExprSchema.model_json_schema()
    assert _enum_values(with_columns_schema, "type") == ["literal", "column", "udf"]

    string_schema = StringTransformConfig.model_json_schema()
    assert _enum_values(string_schema, "method") == [
        "uppercase",
        "lowercase",
        "title",
        "strip",
        "lstrip",
        "rstrip",
        "length",
        "slice",
        "replace",
        "extract",
        "split",
        "split_take",
    ]

    timeseries_schema = TimeSeriesConfig.model_json_schema()
    assert _enum_values(timeseries_schema, "operation_type") == [
        "extract",
        "timestamp",
        "add",
        "subtract",
        "offset",
        "diff",
        "truncate",
        "round",
    ]
    assert _enum_values(timeseries_schema, "component") == [
        "year",
        "month",
        "day",
        "hour",
        "minute",
        "second",
        "quarter",
        "week",
        "dayofweek",
    ]
    assert _enum_values(timeseries_schema, "unit") == [
        "seconds",
        "minutes",
        "hours",
        "days",
        "weeks",
        "months",
    ]
    assert _enum_values(timeseries_schema, "direction") == ["add", "subtract"]


def test_step_catalog_excludes_removed_counts_steps() -> None:
    types = {item["type"] for item in get_step_catalog()}
    assert "value_counts" not in types
    assert "null_count" not in types


def test_validate_step_rejects_removed_counts_steps() -> None:
    with pytest.raises(ValueError, match="Unknown step type"):
        validate_step("value_counts", {"column": "x"})
    with pytest.raises(ValueError, match="Unknown step type"):
        validate_step("null_count", {})


def test_validate_step_rejects_unknown_config_fields() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validate_step("filter", {"conditions": [], "logic": "AND", "typo": True})


def test_validate_step_rejects_unknown_nested_config_fields() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validate_step(
            "with_columns",
            {"expressions": [{"name": "x", "type": "literal", "value": 1, "surprise": True}]},
        )
