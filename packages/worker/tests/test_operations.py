from datetime import date
from typing import Any

import polars as pl
import pytest
from pydantic import ValidationError

from operations.datasource import _resolve_pipeline_datasource
from operations.deduplicate import DeduplicateHandler
from operations.expression import parse_expression
from operations.fill_null import FillNullHandler
from operations.filter import FilterHandler
from operations.groupby import GroupByHandler
from operations.join import JoinHandler
from operations.pivot import PivotHandler
from operations.sample import SampleHandler
from operations.select import SelectHandler
from operations.sort import SortHandler
from operations.strings import StringTransformHandler, StringTransformMethod
from operations.timeseries import (
    TimeComponent,
    TimeseriesHandler,
    TimeseriesOperationType,
)
from operations.topk import TopKHandler
from operations.union import UnionByNameHandler
from operations.unpivot import UnpivotHandler
from operations.with_columns import WithColumnsExprType, WithColumnsHandler
from runtime.domain.datasource.source_types import DataSourceType


def _frame() -> pl.LazyFrame:
    frame = pl.DataFrame(
        {
            "name": ["Alice", "Bob", "Charlie"],
            "age": [30, 25, 40],
            "group": ["a", "a", "b"],
        },
    )
    return frame.with_columns(
        pl.datetime(2024, 1, 1).alias("date"),
        pl.datetime(2024, 1, 2).alias("date2"),
    ).lazy()


def test_resolve_pipeline_datasource_uses_shared_analysis_source_type() -> None:
    pipeline = {"analysis_id": "analysis-1"}
    datasource = {
        "id": "ds-1",
        "analysis_tab_id": "tab-1",
        "config": {"branch": "master"},
    }

    resolved = _resolve_pipeline_datasource(pipeline, datasource)

    assert resolved == {
        "source_type": DataSourceType.ANALYSIS.value,
        "analysis_id": "analysis-1",
        "analysis_tab_id": "tab-1",
        "branch": "master",
    }


@pytest.mark.parametrize(
    ("frame", "conditions", "column", "expected"),
    [
        pytest.param(
            _frame(),
            [{"column": "age", "operator": ">", "value": 30, "value_type": "number"}],
            "name",
            ["Charlie"],
            id="test_filter_handler",
        ),
        pytest.param(
            _frame(),
            [{"column": "name", "operator": "contains", "value": "Ali", "value_type": "string"}],
            "name",
            ["Alice"],
            id="test_filter_handler_string",
        ),
        pytest.param(
            pl.DataFrame({"a": [1, None, 3]}).lazy(),
            [{"column": "a", "operator": "is_not_null", "value": None, "value_type": "string"}],
            "a",
            [1, 3],
            id="test_filter_handler_null",
        ),
        pytest.param(
            _frame(),
            [{"column": "date", "operator": "<", "value": None, "value_type": "column", "compare_column": "date2"}],
            "name",
            ["Alice", "Bob", "Charlie"],
            id="test_filter_handler_column_comparison",
        ),
        pytest.param(
            _frame(),
            [{"column": "name", "operator": "contains", "value": ["Ali", "Bob"], "value_type": "string"}],
            "name",
            ["Alice", "Bob"],
            id="test_filter_handler_contains_list_or",
        ),
        pytest.param(
            _frame(),
            [{"column": "group", "operator": "=", "value": ["a", "b"], "value_type": "string"}],
            "name",
            ["Alice", "Bob", "Charlie"],
            id="test_filter_handler_equals_list_or",
        ),
        pytest.param(
            _frame(),
            [{"column": "name", "operator": "not_contains", "value": ["Ali", "Bob"], "value_type": "string"}],
            "name",
            ["Charlie"],
            id="test_filter_handler_not_contains_list_and",
        ),
        pytest.param(
            _frame(),
            [{"column": "group", "operator": "in", "value": ["a"], "value_type": "string"}],
            "name",
            ["Alice", "Bob"],
            id="test_filter_handler_in_list",
        ),
        pytest.param(
            _frame(),
            [{"column": "group", "operator": "not_in", "value": ["a"], "value_type": "string"}],
            "group",
            ["b"],
            id="test_filter_handler_not_in_list",
        ),
        pytest.param(
            _frame(),
            [{"column": "group", "operator": "not_in", "value": [], "value_type": "string"}],
            "name",
            ["Alice", "Bob", "Charlie"],
            id="test_filter_handler_empty_list_semantics_not_in",
        ),
        pytest.param(
            _frame(),
            [{"column": "group", "operator": "in", "value": [], "value_type": "string"}],
            "name",
            [],
            id="test_filter_handler_empty_list_semantics_in",
        ),
        pytest.param(
            _frame(),
            [{"column": "name", "operator": "regex", "value": "", "value_type": "string"}],
            "name",
            [],
            id="test_filter_handler_empty_regex",
        ),
        pytest.param(
            _frame(),
            [{"column": "", "operator": "=", "value": "", "value_type": "string"}],
            "name",
            ["Alice", "Bob", "Charlie"],
            id="test_filter_handler_placeholder_conditions_are_noop",
        ),
        pytest.param(
            _frame(),
            [
                {"column": "", "operator": "=", "value": "", "value_type": "string"},
                {"column": "age", "operator": ">", "value": 30, "value_type": "number"},
            ],
            "name",
            ["Charlie"],
            id="test_filter_handler_ignores_placeholder_conditions_when_valid_ones_exist",
        ),
        pytest.param(
            _frame(),
            [{"column": "age", "operator": "==", "value": 30, "value_type": "number"}],
            "name",
            ["Alice"],
            id="test_filter_operator_definition",
        ),
    ],
)
def test_filter_handler_conditions(frame: pl.LazyFrame, conditions: list[dict], column: str, expected: list) -> None:
    handler = FilterHandler()
    result = handler(frame, {"conditions": conditions, "logic": "AND"}).collect()
    assert result[column].to_list() == expected


def test_groupby_handler():
    handler = GroupByHandler()
    lf = handler(
        _frame(),
        {"group_by": ["group"], "aggregations": [{"column": "age", "function": "sum"}]},
    )
    result = lf.collect().sort("group")
    assert result["age_sum"].to_list() == [55, 40]


def test_timeseries_extract():
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {
            "column": "date",
            "operation_type": "extract",
            "new_column": "year",
            "component": "year",
        },
    )
    assert lf.collect()["year"].to_list() == [2024, 2024, 2024]


def test_timeseries_offset_add():
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {
            "column": "date",
            "operation_type": "offset",
            "direction": "add",
            "new_column": "shifted",
            "unit": "days",
            "value": 1,
        },
    )
    assert lf.collect()["shifted"][0].day == 2


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        ("ns", 1704067200000000000),
        ("us", 1704067200000000),
        ("ms", 1704067200000),
        ("seconds", 1704067200),
        ("minutes", 28401120),
        ("hours", 473352),
        ("days", 19723),
        ("weeks", 2817),
    ],
)
def test_timeseries_timestamp_unit_magnitudes(unit: str, expected: int) -> None:
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {
            "column": "date",
            "operation_type": "timestamp",
            "new_column": "ts",
            "unit": unit,
        },
    )
    result = lf.collect()["ts"].to_list()
    assert result == [expected] * 3


def test_timeseries_timestamp_defaults_to_microseconds() -> None:
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {
            "column": "date",
            "operation_type": "timestamp",
            "new_column": "ts",
        },
    )
    result = lf.collect()["ts"].to_list()
    assert result == [1704067200000000] * 3


@pytest.mark.parametrize(
    ("params", "error", "match"),
    [
        pytest.param(
            {"column": "date", "operation_type": "timestamp", "new_column": "ts", "unit": "months"},
            ValueError,
            "Unsupported duration unit",
            id="test_timeseries_timestamp_rejects_months",
        ),
        pytest.param(
            {"column": "date", "operation_type": "bogus", "new_column": "x"},
            ValidationError,
            "operation_type",
            id="test_timeseries_unsupported_operation",
        ),
        pytest.param(
            {"column": "date", "operation_type": "add", "new_column": "x", "unit": "days"},
            ValueError,
            "requires numeric value",
            id="test_timeseries_add_missing_value",
        ),
        pytest.param(
            {"column": "date", "operation_type": "add", "new_column": "shifted", "value": 1.5, "unit": "days"},
            ValueError,
            "whole number",
            id="test_timeseries_add_rejects_fractional_value",
        ),
        pytest.param(
            {"column": "date", "operation_type": "add", "new_column": "x", "value": 1},
            ValueError,
            "requires unit",
            id="test_timeseries_add_missing_unit",
        ),
        pytest.param(
            {"column": "date", "operation_type": "diff", "new_column": "x"},
            ValueError,
            "requires column2",
            id="test_timeseries_diff_missing_column2",
        ),
        pytest.param(
            {"column": "date", "operation_type": "truncate", "new_column": "x"},
            ValueError,
            "requires unit",
            id="test_timeseries_truncate_missing_unit",
        ),
    ],
)
def test_timeseries_rejects_invalid_params(params: dict, error: type[Exception], match: str) -> None:
    handler = TimeseriesHandler()
    with pytest.raises(error, match=match):
        handler(_frame(), params).collect()


def test_timeseries_subtract():
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {
            "column": "date",
            "operation_type": "subtract",
            "new_column": "earlier",
            "unit": "days",
            "value": 1,
        },
    )
    assert lf.collect()["earlier"][0].day == 31


def test_timeseries_diff():
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {
            "column": "date",
            "operation_type": "diff",
            "new_column": "delta",
            "column2": "date2",
        },
    )
    result = lf.collect()
    assert "delta" in result.columns


def test_timeseries_months_offset():
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {
            "column": "date",
            "operation_type": "add",
            "new_column": "shifted",
            "unit": "months",
            "value": 2,
        },
    )
    assert lf.collect()["shifted"][0].month == 3


def test_timeseries_truncate():
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {
            "column": "date",
            "operation_type": "truncate",
            "new_column": "truncated",
            "unit": "days",
        },
    )
    result = lf.collect()["truncated"][0]
    assert result.hour == 0
    assert result.minute == 0


def test_timeseries_round():
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {
            "column": "date",
            "operation_type": "round",
            "new_column": "rounded",
            "unit": "hours",
        },
    )
    result = lf.collect()
    assert "rounded" in result.columns
    assert result["rounded"][0].minute == 0


def test_timeseries_extract_dayofweek():
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {
            "column": "date",
            "operation_type": "extract",
            "new_column": "dow",
            "component": "dayofweek",
        },
    )
    result = lf.collect()["dow"].to_list()
    assert all(isinstance(v, int) for v in result)


def test_timeseries_accepts_enum_fields() -> None:
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {
            "column": "date",
            "operation_type": TimeseriesOperationType.EXTRACT,
            "new_column": "dow",
            "component": TimeComponent.DAYOFWEEK,
        },
    )
    result = lf.collect()["dow"].to_list()
    assert all(isinstance(v, int) for v in result)


def test_string_transform_uppercase():
    handler = StringTransformHandler()
    lf = handler(_frame(), {"column": "name", "method": "uppercase", "new_column": "name_upper"})
    assert lf.collect()["name_upper"].to_list()[0] == "ALICE"


def test_string_transform_accepts_enum_method() -> None:
    handler = StringTransformHandler()
    lf = handler(
        _frame(),
        {
            "column": "name",
            "method": StringTransformMethod.UPPERCASE,
            "new_column": "name_upper",
        },
    )
    assert lf.collect()["name_upper"].to_list()[0] == "ALICE"


def test_string_transform_slice_uses_end_index_semantics() -> None:
    handler = StringTransformHandler()
    lf = handler(
        _frame(),
        {"column": "name", "method": "slice", "start": 1, "end": 3, "new_column": "name_slice"},
    )

    assert lf.collect()["name_slice"].to_list() == ["li", "ob", "ha"]


def test_fill_null_drop_rows():
    handler = FillNullHandler()
    frame = pl.DataFrame({"a": [1, None, 3], "b": [None, "x", "y"]}).lazy()

    assert handler(frame, {"strategy": "drop_rows"}).collect()["a"].to_list() == [3]
    assert handler(frame, {"strategy": "drop_rows", "columns": ["a"]}).collect()["a"].to_list() == [1, 3]


def test_fill_null_literal():
    handler = FillNullHandler()
    lf = handler(
        pl.DataFrame({"a": [1, None]}).lazy(),
        {"strategy": "literal", "value": 0, "value_type": "Int64"},
    )
    assert lf.collect()["a"].to_list() == [1, 0]


def test_fill_null_literal_preserves_existing_float_values():
    handler = FillNullHandler()
    result = handler(
        pl.DataFrame({"a": [1.5, None]}).lazy(),
        {"strategy": "literal", "columns": ["a"], "value": 0, "value_type": "Int64"},
    ).collect()

    assert result["a"].to_list() == [1.5, 0.0]
    assert result.dtypes == [pl.Float64]


def test_fill_null_mean_without_columns_targets_numeric_columns_only():
    handler = FillNullHandler()
    result = handler(
        pl.DataFrame(
            {
                "name": ["Alice", "Bob", "Charlie"],
                "event_date": [date(2024, 1, 15), date(2024, 3, 22), date(2024, 6, 10)],
                "amount": [100, None, 75],
            }
        ).lazy(),
        {"strategy": "mean"},
    ).collect()

    assert result["name"].to_list() == ["Alice", "Bob", "Charlie"]
    assert result["event_date"].to_list() == [
        date(2024, 1, 15),
        date(2024, 3, 22),
        date(2024, 6, 10),
    ]
    assert result["amount"].to_list() == [100.0, 87.5, 75.0]
    assert result.schema["amount"] == pl.Float64()


def test_fill_null_mean_rejects_non_numeric_selected_columns():
    handler = FillNullHandler()

    with pytest.raises(ValueError, match="Unsupported columns: name"):
        handler(
            pl.DataFrame({"name": ["Alice", None], "amount": [100, None]}).lazy(),
            {"strategy": "mean", "columns": ["name", "amount"]},
        )


def test_sample_handler_respects_non_reciprocal_fraction():
    handler = SampleHandler()
    result = handler(
        pl.DataFrame({"id": list(range(1000))}).lazy(),
        {"fraction": 0.6, "seed": 7},
    ).collect()

    assert 500 <= result.height <= 700
    assert result.height < 1000


def test_deduplicate_handler_keep_last_on_subset():
    handler = DeduplicateHandler()
    result = handler(
        pl.DataFrame(
            {
                "id": [1, 1, 2, 2],
                "value": ["first", "last", "alpha", "beta"],
                "tag": ["a", "b", "c", "d"],
            }
        ).lazy(),
        {"subset": ["id"], "keep": "last"},
    ).collect()

    assert result["id"].to_list() == [1, 2]
    assert result["value"].to_list() == ["last", "beta"]
    assert result["tag"].to_list() == ["b", "d"]


@pytest.mark.parametrize(
    ("how", "expected_height", "expected_values"),
    [
        pytest.param("inner", 1, {"val": ["b"], "val2": ["x"]}, id="test_join_handler_inner_correctness"),
        # Only the row count is pinned for the outer join, matching the original test.
        pytest.param("outer", 3, {}, id="test_join_handler_outer_uses_shared_join_how"),
    ],
)
def test_join_handler_how(how: str, expected_height: int, expected_values: dict[str, list]) -> None:
    handler = JoinHandler()
    left = pl.DataFrame({"id": [1, 2], "val": ["a", "b"]}).lazy()
    right = pl.DataFrame({"id": [2, 3], "val2": ["x", "y"]}).lazy()

    result = handler(
        left,
        {
            "join_columns": [{"left_column": "id", "right_column": "id"}],
            "how": how,
            "right_source": "right",
        },
        right_lf=right,
    ).collect()

    assert result.height == expected_height
    for column, values in expected_values.items():
        assert result[column].to_list() == values


@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param("_r", id="test_join_handler_right_columns_filters_unsuffixed_right_columns"),
        pytest.param("", id="test_join_handler_right_columns_with_empty_suffix_keeps_requested_columns"),
    ],
)
def test_join_handler_right_columns_keep_requested_columns(suffix: str) -> None:
    handler = JoinHandler()
    left = pl.DataFrame({"id": [1, 2], "left_val": ["a", "b"]}).lazy()
    right = pl.DataFrame({"id": [2, 3], "right_keep": [10, 20], "right_drop": [100, 200]}).lazy()

    result = handler(
        left,
        {
            "join_columns": [{"left_column": "id", "right_column": "id"}],
            "how": "inner",
            "right_source": "right",
            "right_columns": ["right_keep"],
            "suffix": suffix,
        },
        right_lf=right,
    ).collect()

    assert result.columns == ["id", "left_val", "right_keep"]
    assert result["right_keep"].to_list() == [10]


def test_join_handler_right_columns_reject_unknown_columns() -> None:
    handler = JoinHandler()
    left = pl.DataFrame({"id": [1, 2], "left_val": ["a", "b"]}).lazy()
    right = pl.DataFrame({"id": [2, 3], "right_keep": [10, 20]}).lazy()

    with pytest.raises(ValueError, match="unknown column"):
        handler(
            left,
            {
                "join_columns": [{"left_column": "id", "right_column": "id"}],
                "how": "inner",
                "right_source": "right",
                "right_columns": ["does_not_exist"],
            },
            right_lf=right,
        )


def test_with_columns_zero_arg_udf_uses_row_count(monkeypatch: pytest.MonkeyPatch):
    handler = WithColumnsHandler()
    lf = pl.DataFrame({"id": [1, 2]}).lazy()

    called = {"int_range": 0, "lit": 0}
    original_int_range = pl.int_range
    original_lit = pl.lit

    def track_int_range(*args: Any, **kwargs: Any) -> pl.Expr:
        called["int_range"] += 1
        return original_int_range(*args, **kwargs)

    def track_lit(*args: Any, **kwargs: Any) -> pl.Expr:
        called["lit"] += 1
        return original_lit(*args, **kwargs)

    monkeypatch.setattr(pl, "int_range", track_int_range)
    monkeypatch.setattr(pl, "lit", track_lit)

    result = handler(
        lf,
        {
            "expressions": [
                {
                    "name": "udf_col",
                    "type": "udf",
                    "code": "def udf():\n    return 1",
                },
            ],
        },
    )

    assert result is not None
    assert called["int_range"] == 1
    assert called["lit"] == 0


def test_with_columns_accepts_enum_expression_type() -> None:
    handler = WithColumnsHandler()
    lf = handler(
        pl.DataFrame({"id": [1]}).lazy(),
        {"expressions": [{"name": "copy_id", "type": WithColumnsExprType.COLUMN, "column": "id"}]},
    )
    assert lf.collect()["copy_id"].to_list() == [1]


def test_with_columns_udf_can_use_sleep_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = WithColumnsHandler()
    calls: list[float] = []

    monkeypatch.setattr(
        "operations.with_columns.time.sleep",
        calls.append,
    )

    lf = handler(
        pl.DataFrame({"id": [1, 2, 3]}).lazy(),
        {
            "expressions": [
                {
                    "name": "copy_id",
                    "type": "udf",
                    "args": ["id"],
                    "code": "def udf(value):\n    sleep(0.01)\n    return value",
                }
            ]
        },
    )

    assert lf.collect()["copy_id"].to_list() == [1, 2, 3]
    assert len(calls) >= 3
    assert all(call == 0.01 for call in calls)


def test_with_columns_library_udf_without_code_fails() -> None:
    handler = WithColumnsHandler()
    with pytest.raises(ValueError, match="missing its code"):
        handler(
            pl.DataFrame({"value": [0.0]}).lazy(),
            {
                "expressions": [
                    {
                        "name": "value_f",
                        "type": WithColumnsExprType.UDF,
                        "udf_id": "udf-1",
                        "args": ["value"],
                    }
                ]
            },
        )


def test_with_columns_protocol_udf_number_computes_the_column() -> None:
    handler = WithColumnsHandler()
    frame = handler(
        pl.DataFrame({"value": [0.0, 100.0]}).lazy(),
        {
            "expressions": [
                {
                    "name": "value_f",
                    "type": int(WithColumnsExprType.UDF),
                    "args": ["value"],
                    "code": "def udf(value):\n    return value * 9 / 5 + 32\n",
                }
            ]
        },
    ).collect()

    assert frame["value_f"].to_list() == [32.0, 212.0]


def test_expression_rejects_dunder_escape() -> None:
    with pytest.raises(ValueError, match="forbidden dunder access"):
        parse_expression('pl.col("age").__class__')


def test_expression_ast_evaluator_supports_polars_chains() -> None:
    frame = pl.DataFrame({"age": [10, 20]}).lazy()

    result = frame.select(parse_expression('pl.when(pl.col("age") >= 18).then(pl.col("age").cast(pl.Float64) * 2).otherwise(0)').alias("score")).collect()

    assert result["score"].to_list() == [0.0, 40.0]


@pytest.mark.parametrize(
    "expression",
    [
        'open("/tmp/data")',
        '(lambda value: value)(pl.col("age"))',
        '[value for value in [pl.col("age")]]',
        'pl.read_csv("/tmp/data.csv")',
    ],
)
def test_expression_ast_evaluator_rejects_non_expression_capabilities(expression: str) -> None:
    with pytest.raises(ValueError, match="not allowed|Failed to parse expression"):
        parse_expression(expression)


def test_with_columns_rejects_reflection_escape() -> None:
    handler = WithColumnsHandler()
    with pytest.raises(ValueError, match="forbidden pattern"):
        handler(
            pl.DataFrame({"id": [1]}).lazy(),
            {
                "expressions": [
                    {
                        "name": "bad",
                        "type": "udf",
                        "code": "def udf():\n    return globals()",
                    }
                ]
            },
        )


def test_with_columns_rejects_aliased_globals_escape() -> None:
    handler = WithColumnsHandler()
    with pytest.raises(NameError, match="globals"):
        handler(
            pl.DataFrame({"id": [1]}).lazy(),
            {
                "expressions": [
                    {
                        "name": "bad",
                        "type": "udf",
                        "code": "global g\ng = globals\ndef udf():\n    return len(g())",
                    }
                ]
            },
        )


def test_union_by_name_handler():
    handler = UnionByNameHandler()
    left = pl.DataFrame({"id": [1]}).lazy()
    right = pl.DataFrame({"id": [2]}).lazy()
    lf = handler(
        left,
        {"sources": ["right"], "allow_missing": True},
        right_sources={"right": right},
    )
    assert lf.collect().height == 2


def test_unpivot_handler_accepts_alias_params():
    handler = UnpivotHandler()
    result = handler(
        pl.DataFrame({"city": ["Brno"], "jan": [10], "feb": [20]}).lazy(),
        {
            "id_vars": ["city"],
            "value_vars": ["jan", "feb"],
            "variable_name": "month",
            "value_name": "sales",
        },
    ).collect()

    assert result["city"].to_list() == ["Brno", "Brno"]
    assert result["month"].to_list() == ["jan", "feb"]
    assert result["sales"].to_list() == [10, 20]


def test_topk_handler_descending_returns_largest_rows_first():
    handler = TopKHandler()
    result = handler(
        pl.DataFrame({"name": ["a", "b", "c"], "score": [10, 30, 20]}).lazy(),
        {"column": "score", "k": 2, "descending": True},
    ).collect()

    assert result["name"].to_list() == ["b", "c"]
    assert result["score"].to_list() == [30, 20]


def test_pivot_handler_count_aggregates_with_len():
    handler = PivotHandler()
    result = (
        handler(
            pl.DataFrame({"idx": ["a", "a", "b"], "col": ["x", "x", "y"], "val": [1, 2, 3]}).lazy(),
            {
                "index": ["idx"],
                "columns": "col",
                "value_columns": ["val"],
                "aggregate_function": "count",
                "on_columns": ["x", "y"],
            },
        )
        .collect()
        .sort("idx")
    )

    assert result["x"].to_list() == [2, 0]
    assert result["y"].to_list() == [0, 1]


def test_pivot_handler_auto_discovers_on_columns_for_small_cardinality():
    handler = PivotHandler()
    lf = handler(
        pl.DataFrame({"idx": ["a", "a"], "col": ["x", "y"], "val": [1, 2]}).lazy(),
        {
            "index": ["idx"],
            "columns": "col",
            "value_columns": ["val"],
            "aggregate_function": "first",
        },
    )
    result = lf.collect()
    assert result.columns == ["idx", "x", "y"]


def test_pivot_handler_aggregates_multiple_value_columns():
    handler = PivotHandler()
    lf = handler(
        pl.DataFrame(
            {
                "idx": ["a", "a", "a"],
                "col": ["x", "x", "y"],
                "sales": [1, 2, 3],
                "units": [4, 5, 6],
            }
        ).lazy(),
        {
            "index": ["idx"],
            "columns": "col",
            "value_columns": ["sales", "units"],
            "aggregate_function": "sum",
            "on_columns": ["x", "y"],
        },
    )

    result = lf.collect()
    assert result["sales_x"].to_list() == [3]
    assert result["sales_y"].to_list() == [3]
    assert result["units_x"].to_list() == [9]
    assert result["units_y"].to_list() == [6]


def test_pivot_handler_rejects_unbounded_auto_discovery(
    monkeypatch: pytest.MonkeyPatch,
):
    handler = PivotHandler()
    monkeypatch.setattr("operations.pivot._MAX_AUTO_PIVOT_VALUES", 2)
    with pytest.raises(ValueError, match="requires explicit on_columns"):
        handler(
            pl.DataFrame({"idx": ["a", "a", "a"], "col": ["x", "y", "z"], "val": [1, 2, 3]}).lazy(),
            {
                "index": ["idx"],
                "columns": "col",
                "value_columns": ["val"],
                "aggregate_function": "first",
            },
        )


def test_select_and_sort_handlers():
    select = SelectHandler()
    sort = SortHandler()
    lf = select(_frame(), {"columns": ["age"]})
    lf = sort(lf, {"columns": ["age"], "descending": [True]})
    assert lf.collect()["age"].to_list()[0] == 40


def test_select_handler_cast_map():
    handler = SelectHandler()
    lf = handler(
        pl.DataFrame({"age": ["30", "25"], "name": ["Alice", "Bob"]}).lazy(),
        {"columns": ["age", "name"], "cast_map": {"age": "Int64"}},
    )
    result = lf.collect()
    assert result.schema["age"] == pl.Int64()
    assert result["age"].to_list() == [30, 25]


def test_select_handler_cast_map_invalid_type():
    handler = SelectHandler()
    with pytest.raises(ValidationError, match="cast_map"):
        handler(
            pl.DataFrame({"age": ["30"]}).lazy(),
            {"columns": ["age"], "cast_map": {"age": "Nope"}},
        ).collect()


def test_select_handler_cast_map_non_selected_column():
    handler = SelectHandler()
    with pytest.raises(ValueError, match="cast_map keys must reference selected columns"):
        handler(
            pl.DataFrame({"age": ["30"], "name": ["Alice"]}).lazy(),
            {"columns": ["age"], "cast_map": {"name": "String"}},
        ).collect()
