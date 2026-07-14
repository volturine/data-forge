import dataclasses

import pytest

from operations.step_converter import (
    BackendStep,
    FrontendStep,
    convert_config_to_params,
    convert_step_format,
)


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
        setattr(step, "operation", "filter")


def test_convert_step_format_parses_config_through_protocol_step_config() -> None:
    step = convert_step_format(
        {
            "id": "step-1",
            "type": "filter",
            "config": {
                "conditions": [
                    {
                        "column": "age",
                        "operator": ">",
                        "value": 30,
                        "value_type": "number",
                    }
                ],
                "logic": "AND",
            },
        },
    )

    assert step.operation == "filter"
    assert step.params == {
        "conditions": [
            {
                "column": "age",
                "operator": ">",
                "value": 30,
                "value_type": "number",
            }
        ],
        "logic": "AND",
    }


def test_frontend_step_from_mapping_rejects_unknown_protocol_config_field() -> None:
    with pytest.raises(ValueError, match="no_such_field"):
        FrontendStep.from_mapping(
            {
                "id": "step-1",
                "type": "filter",
                "config": {"conditions": [], "logic": "AND", "no_such_field": True},
            }
        )


def test_convert_step_format_accepts_protocol_step_type_field() -> None:
    step = convert_step_format(
        {
            "id": "step-1",
            "step_type": "limit",
            "config": {"n": 5},
        },
    )

    assert step.operation == "limit"
    assert step.params == {"n": 5}


def test_convert_step_format_preserves_explicit_protocol_default_values() -> None:
    step = convert_step_format(
        {
            "id": "step-1",
            "type": "union_by_name",
            "config": {"sources": ["step-0"], "allow_missing": False},
        },
    )

    assert step.operation == "union_by_name"
    assert step.params == {"sources": ["step-0"], "allow_missing": False}


def test_frontend_step_from_mapping_rejects_mismatched_step_config_oneof() -> None:
    with pytest.raises(ValueError, match="does not match step type"):
        FrontendStep.from_mapping({"id": "step-1", "type": "filter", "config": {"limit": {"n": 5}}})


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
