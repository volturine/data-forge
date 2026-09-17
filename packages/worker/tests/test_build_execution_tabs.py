import pytest

from runtime import compute_service


def _pipeline(tab_specs: list[dict], tab_id: str | None = "tab-2") -> dict:
    tabs = [{"id": spec["id"], "name": spec["id"], **spec} for spec in tab_specs]
    pipeline: dict = {"analysis_id": "analysis-1", "tabs": tabs}
    if tab_id is not None:
        pipeline["tab_id"] = tab_id
    return pipeline


def test_build_executes_only_the_selected_tab():
    pipeline = _pipeline([{"id": "tab-1"}, {"id": "tab-2"}], tab_id="tab-2")

    assert compute_service._build_execution_tabs(pipeline) == [{"id": "tab-2", "name": "tab-2"}]


def test_build_does_not_include_upstream_tabs():
    pipeline = _pipeline(
        [
            {"id": "tab-1", "output": {"result_id": "out-1"}},
            {"id": "tab-2", "datasource": {"id": "out-1"}},
        ],
        tab_id="tab-2",
    )

    executed = compute_service._build_execution_tabs(pipeline)

    assert [tab["id"] for tab in executed] == ["tab-2"]


def test_build_without_tab_id_raises():
    pipeline = _pipeline([{"id": "tab-1"}], tab_id=None)

    with pytest.raises(ValueError, match="missing tab_id"):
        compute_service._build_execution_tabs(pipeline)


def test_build_with_unknown_tab_id_raises():
    pipeline = _pipeline([{"id": "tab-1"}], tab_id="missing")

    with pytest.raises(ValueError, match="missing tab missing"):
        compute_service._build_execution_tabs(pipeline)


def test_count_total_build_steps():
    pipeline = _pipeline(
        [{"id": "tab-2", "steps": [{"id": "s1"}, {"id": "s2"}], "output": {"filename": "b.parquet"}}],
        tab_id="tab-2",
    )

    # Per tab: read + steps + write. tab-2: 2 + 2.
    assert compute_service._count_total_build_steps(pipeline["tabs"]) == 4
