from contracts.analysis.step_types import (
    chart_type_for_step,
    get_step_timing_key,
    is_chart_step_type,
    is_plot_alias_step_type,
    normalize_step_type,
)


def test_chart_alias_helpers_are_explicit() -> None:
    assert is_plot_alias_step_type("plot_scatter")
    assert not is_plot_alias_step_type("chart")
    assert chart_type_for_step("plot_scatter") == "scatter"
    assert chart_type_for_step("chart") is None


def test_chart_step_normalization() -> None:
    assert is_chart_step_type("chart")
    assert is_chart_step_type("plot_bar")
    assert not is_chart_step_type("filter")
    assert normalize_step_type("plot_bar") == "chart"
    assert normalize_step_type("filter") == "filter"


def test_step_timing_key_labels_repeated_steps() -> None:
    assert get_step_timing_key("filter") == ("filter", "Filter")
    assert get_step_timing_key("filter_2") == ("filter", "Filter 2")
