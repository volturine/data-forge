from unittest.mock import MagicMock, patch

from runtime.compute_utils import apply_steps, resolve_applied_target
from runtime.polars_compute import _build_pipeline_details


def test_apply_steps_skips_disabled_and_relinks():
    steps = [
        {
            "id": "s1",
            "type": "filter",
            "config": {"conditions": [{"column": "col", "operator": ">", "value": 1}]},
            "depends_on": [],
        },
        {
            "id": "s2",
            "type": "notification",
            "config": {},
            "depends_on": ["s1"],
            "is_applied": False,
        },
        {
            "id": "s3",
            "type": "select",
            "config": {"columns": ["col"]},
            "depends_on": ["s2"],
        },
    ]

    applied = apply_steps(steps)
    assert [step["id"] for step in applied] == ["s1", "s3"]
    assert applied[1].get("depends_on") == ["s1"]


def test_resolve_applied_target_returns_parent_when_disabled():
    steps = [
        {"id": "s1", "type": "filter", "config": {}, "depends_on": []},
        {
            "id": "s2",
            "type": "select",
            "config": {},
            "depends_on": ["s1"],
            "is_applied": False,
        },
        {"id": "s3", "type": "sort", "config": {}, "depends_on": ["s2"]},
    ]

    target = resolve_applied_target(steps, "s2")
    assert target == "s1"


def test_disabled_step_ancestor_walk_keeps_missing_and_cycle_behavior():
    steps = [
        {"id": "s1", "type": "filter", "config": {}, "depends_on": ["missing"]},
        {"id": "s2", "type": "select", "config": {}, "depends_on": ["s3"], "is_applied": False},
        {"id": "s3", "type": "sort", "config": {}, "depends_on": ["s2"], "is_applied": False},
        {"id": "s4", "type": "unique", "config": {}, "depends_on": ["s2"]},
    ]

    applied = apply_steps(steps)
    assert [step["id"] for step in applied] == ["s1", "s4"]
    assert applied[0]["depends_on"] == []
    assert applied[1]["depends_on"] == []
    assert resolve_applied_target(steps, "s2") == "source"
    assert resolve_applied_target(steps, "missing") == "source"
    assert resolve_applied_target(steps, "s4") == "s4"


@patch("runtime.polars_compute.load_datasource")
@patch("runtime.polars_compute.apply_step")
def test_build_pipeline_skips_disabled_step(mock_apply_step: MagicMock, mock_load: MagicMock):
    fake_lf = MagicMock()
    mock_load.return_value = fake_lf
    mock_apply_step.return_value = fake_lf

    steps: list[dict] = [
        {
            "id": "s1",
            "type": "filter",
            "config": {"conditions": [{"column": "col", "operator": ">", "value": 1}]},
            "depends_on": [],
        },
        {
            "id": "s2",
            "type": "notification",
            "config": {},
            "depends_on": ["s1"],
            "is_applied": False,
        },
        {
            "id": "s3",
            "type": "select",
            "config": {"columns": ["col"]},
            "depends_on": ["s2"],
        },
    ]

    result, _timings, _read_duration_ms = _build_pipeline_details({}, steps, "job-1")
    assert result == fake_lf
    assert mock_apply_step.call_count == 2
    called_ops = [call.args[1].operation for call in mock_apply_step.call_args_list]
    assert called_ops == ["filter", "select"]
