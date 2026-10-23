import dataclasses

import pytest

from dataforge_protocol import enums_pb2
from operations.step_converter import (
    BackendStep,
    FrontendStep,
    convert_step_format,
)


def test_direct_frontend_step_with_unknown_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown operation 'typo'"):
        convert_step_format(FrontendStep(id="step-1", type="typo"))


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
        step.operation = "filter"


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
                "operator": enums_pb2.FILTER_OPERATOR_GREATER_THAN,
                "value": 30,
                "value_type": enums_pb2.FILTER_VALUE_TYPE_NUMBER,
            }
        ],
        "logic": enums_pb2.FILTER_LOGIC_AND,
    }


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


@pytest.mark.parametrize(
    ("mapping", "match"),
    [
        pytest.param(
            {"id": "step-1", "type": "filter", "config": {"conditions": [], "logic": "AND", "no_such_field": True}},
            "no_such_field",
            id="test_frontend_step_from_mapping_rejects_unknown_protocol_config_field",
        ),
        pytest.param(
            {"id": "step-1", "type": "filter", "config": {"limit": {"n": 5}}},
            "does not match step type",
            id="test_frontend_step_from_mapping_rejects_mismatched_step_config_oneof",
        ),
        pytest.param({"id": "step-1"}, "Step must have a type field", id="test_frontend_step_from_mapping_rejects_missing_type"),
        pytest.param(
            {"id": "step-1", "type": "typo", "config": {}},
            "Unknown step type 'typo'",
            id="test_frontend_step_from_mapping_rejects_unknown_step_type",
        ),
        pytest.param(
            {"id": "step-1", "type": "filter", "config": {}, "surprise": True},
            "unknown field",
            id="test_frontend_step_from_mapping_rejects_unknown_fields",
        ),
        pytest.param(
            {"id": "step-1", "type": "filter", "config": []},
            "Step config must be an object",
            id="test_frontend_step_from_mapping_rejects_invalid_config_shape",
        ),
        pytest.param(
            {"id": "step-1", "type": "filter", "config": {}, "depends_on": [None]},
            "depends_on must be a list",
            id="test_frontend_step_from_mapping_rejects_invalid_depends_on_shape",
        ),
    ],
)
def test_frontend_step_from_mapping_rejects_invalid_mappings(mapping: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        FrontendStep.from_mapping(mapping)
