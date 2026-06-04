import dataclasses

import pytest

from operations.step_converter import (
    BackendStep,
    FrontendStep,
    convert_config_to_params,
    convert_filter_config,
    convert_groupby_config,
    convert_rename_config,
    convert_step_format,
)


def test_convert_groupby_config_uses_group_by() -> None:
    result = convert_groupby_config(
        {
            "group_by": ["team"],
            "aggregations": [{"column": "score", "function": "sum", "alias": "total"}],
        },
    )
    assert result["group_by"] == ["team"]
    assert result["aggregations"] == [{"column": "score", "function": "sum", "alias": "total"}]


def test_convert_groupby_config_defaults_group_by_to_empty() -> None:
    result = convert_groupby_config(
        {
            "aggregations": [{"column": "score", "function": "sum"}],
        },
    )
    assert result["group_by"] == []
    assert result["aggregations"] == [{"column": "score", "function": "sum", "alias": None}]


def test_convert_rename_config_accepts_column_mapping_and_mapping() -> None:
    by_column_mapping = convert_rename_config({"column_mapping": {"old": "new"}})
    by_mapping = convert_rename_config({"mapping": {"old": "new"}})

    assert by_column_mapping == {"mapping": {"old": "new"}}
    assert by_mapping == {"mapping": {"old": "new"}}


def test_convert_filter_config_ignores_blank_placeholder_conditions() -> None:
    result = convert_filter_config(
        {
            "conditions": [
                {
                    "column": "",
                    "operator": "=",
                    "value": "",
                    "value_type": "string",
                },
            ],
            "logic": "AND",
        },
    )

    assert result == {"conditions": [], "logic": "AND"}


def test_convert_filter_config_keeps_valid_conditions_when_placeholders_present() -> None:
    result = convert_filter_config(
        {
            "conditions": [
                {
                    "column": "",
                    "operator": "=",
                    "value": "",
                    "value_type": "string",
                },
                {
                    "column": "age",
                    "operator": ">",
                    "value": 30,
                    "value_type": "number",
                },
            ],
            "logic": "AND",
        },
    )

    assert result == {
        "conditions": [
            {
                "column": "age",
                "operator": ">",
                "value": 30,
                "value_type": "number",
            },
        ],
        "logic": "AND",
    }


def test_convert_config_to_params_rejects_unregistered_operations() -> None:
    with pytest.raises(ValueError, match="Unknown operation 'typo'"):
        convert_config_to_params("typo", {})


def test_convert_step_format_returns_frozen_backend_step_dataclass() -> None:
    step = convert_step_format(
        {
            "id": "step-1",
            "type": "plot_scatter",
            "config": {"x_column": "age", "y_column": "score"},
            "depends_on": ["step-0"],
            "is_applied": True,
        },
    )

    assert isinstance(step, BackendStep)
    assert dataclasses.is_dataclass(step)
    assert step.name == "Scatter Plot"
    assert step.operation == "chart"
    assert step.params["chart_type"] == "scatter"

    with pytest.raises(dataclasses.FrozenInstanceError):
        step.operation = "filter"  # type: ignore[misc]


def test_frontend_step_from_mapping_rejects_missing_type() -> None:
    with pytest.raises(ValueError, match="Step must have a type field"):
        FrontendStep.from_mapping({"id": "step-1"})


def test_frontend_step_from_mapping_rejects_unknown_step_type() -> None:
    with pytest.raises(ValueError, match="Unknown step type 'typo'"):
        FrontendStep.from_mapping({"id": "step-1", "type": "typo", "config": {}})


def test_frontend_step_from_mapping_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="unknown field"):
        FrontendStep.from_mapping({"id": "step-1", "type": "filter", "config": {}, "surprise": True})


def test_frontend_step_from_mapping_rejects_invalid_config_shape() -> None:
    with pytest.raises(ValueError, match="Step config must be an object"):
        FrontendStep.from_mapping({"id": "step-1", "type": "filter", "config": []})


def test_frontend_step_from_mapping_rejects_invalid_depends_on_shape() -> None:
    with pytest.raises(ValueError, match="depends_on must be a list"):
        FrontendStep.from_mapping({"id": "step-1", "type": "filter", "config": {}, "depends_on": [None]})
