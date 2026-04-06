from typing import Any

import polars as pl
import pytest
from pydantic import ValidationError

from modules.compute.operations.expression import parse_expression
from modules.compute.operations.fill_null import FillNullHandler
from modules.compute.operations.filter import FilterHandler
from modules.compute.operations.groupby import GroupByHandler
from modules.compute.operations.join import JoinHandler
from modules.compute.operations.pivot import PivotHandler
from modules.compute.operations.select import SelectHandler
from modules.compute.operations.sort import SortHandler
from modules.compute.operations.strings import StringTransformHandler, StringTransformMethod
from modules.compute.operations.timeseries import TimeComponent, TimeseriesHandler, TimeseriesOperationType
from modules.compute.operations.union import UnionByNameHandler
from modules.compute.operations.with_columns import WithColumnsExprType, WithColumnsHandler


def _frame() -> pl.LazyFrame:
    frame = pl.DataFrame(
        {
            'name': ['Alice', 'Bob', 'Charlie'],
            'age': [30, 25, 40],
            'group': ['a', 'a', 'b'],
        },
    )
    return frame.with_columns(
        pl.datetime(2024, 1, 1).alias('date'),
        pl.datetime(2024, 1, 2).alias('date2'),
    ).lazy()


def test_filter_handler():
    handler = FilterHandler()
    lf = handler(
        _frame(),
        {'conditions': [{'column': 'age', 'operator': '>', 'value': 30, 'value_type': 'number'}], 'logic': 'AND'},
    )
    assert lf.collect().height == 1


def test_filter_handler_string():
    handler = FilterHandler()
    lf = handler(
        _frame(),
        {'conditions': [{'column': 'name', 'operator': 'contains', 'value': 'Ali', 'value_type': 'string'}], 'logic': 'AND'},
    )
    assert lf.collect().height == 1


def test_filter_handler_null():
    handler = FilterHandler()
    lf = handler(
        pl.DataFrame({'a': [1, None, 3]}).lazy(),
        {'conditions': [{'column': 'a', 'operator': 'is_not_null', 'value': None, 'value_type': 'string'}], 'logic': 'AND'},
    )
    assert lf.collect().height == 2


def test_filter_handler_column_comparison():
    handler = FilterHandler()
    lf = handler(
        _frame(),
        {
            'conditions': [{'column': 'date', 'operator': '<', 'value': None, 'value_type': 'column', 'compare_column': 'date2'}],
            'logic': 'AND',
        },
    )
    assert lf.collect().height == 3


def test_filter_handler_contains_list_or():
    handler = FilterHandler()
    lf = handler(
        _frame(),
        {
            'conditions': [
                {
                    'column': 'name',
                    'operator': 'contains',
                    'value': ['Ali', 'Bob'],
                    'value_type': 'string',
                },
            ],
            'logic': 'AND',
        },
    )
    assert lf.collect().height == 2


def test_filter_handler_equals_list_or():
    handler = FilterHandler()
    lf = handler(
        _frame(),
        {
            'conditions': [
                {
                    'column': 'group',
                    'operator': '=',
                    'value': ['a', 'b'],
                    'value_type': 'string',
                },
            ],
            'logic': 'AND',
        },
    )
    assert lf.collect().height == 3


def test_filter_handler_not_contains_list_and():
    handler = FilterHandler()
    lf = handler(
        _frame(),
        {
            'conditions': [
                {
                    'column': 'name',
                    'operator': 'not_contains',
                    'value': ['Ali', 'Bob'],
                    'value_type': 'string',
                },
            ],
            'logic': 'AND',
        },
    )
    assert lf.collect()['name'].to_list() == ['Charlie']


def test_filter_handler_in_list():
    handler = FilterHandler()
    lf = handler(
        _frame(),
        {
            'conditions': [
                {
                    'column': 'group',
                    'operator': 'in',
                    'value': ['a'],
                    'value_type': 'string',
                },
            ],
            'logic': 'AND',
        },
    )
    assert lf.collect().height == 2


def test_filter_handler_not_in_list():
    handler = FilterHandler()
    lf = handler(
        _frame(),
        {
            'conditions': [
                {
                    'column': 'group',
                    'operator': 'not_in',
                    'value': ['a'],
                    'value_type': 'string',
                },
            ],
            'logic': 'AND',
        },
    )
    assert lf.collect()['group'].to_list() == ['b']


def test_filter_handler_empty_regex():
    handler = FilterHandler()
    lf = handler(
        _frame(),
        {
            'conditions': [
                {
                    'column': 'name',
                    'operator': 'regex',
                    'value': '',
                    'value_type': 'string',
                },
            ],
            'logic': 'AND',
        },
    )
    assert lf.collect().height == 0


def test_filter_handler_placeholder_conditions_are_noop() -> None:
    handler = FilterHandler()

    result = handler(
        _frame(),
        {
            'conditions': [
                {
                    'column': '',
                    'operator': '=',
                    'value': '',
                    'value_type': 'string',
                },
            ],
            'logic': 'AND',
        },
    ).collect()

    assert result['name'].to_list() == ['Alice', 'Bob', 'Charlie']


def test_filter_handler_ignores_placeholder_conditions_when_valid_ones_exist() -> None:
    handler = FilterHandler()

    result = handler(
        _frame(),
        {
            'conditions': [
                {
                    'column': '',
                    'operator': '=',
                    'value': '',
                    'value_type': 'string',
                },
                {
                    'column': 'age',
                    'operator': '>',
                    'value': 30,
                    'value_type': 'number',
                },
            ],
            'logic': 'AND',
        },
    ).collect()

    assert result['name'].to_list() == ['Charlie']


def test_groupby_handler():
    handler = GroupByHandler()
    lf = handler(
        _frame(),
        {'group_by': ['group'], 'aggregations': [{'column': 'age', 'function': 'sum'}]},
    )
    result = lf.collect().sort('group')
    assert result['age_sum'].to_list() == [55, 40]


def test_timeseries_extract():
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {'column': 'date', 'operation_type': 'extract', 'new_column': 'year', 'component': 'year'},
    )
    assert lf.collect()['year'].to_list() == [2024, 2024, 2024]


def test_timeseries_offset_add():
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {
            'column': 'date',
            'operation_type': 'offset',
            'direction': 'add',
            'new_column': 'shifted',
            'unit': 'days',
            'value': 1,
        },
    )
    assert lf.collect()['shifted'][0].day == 2


def test_timeseries_timestamp():
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {'column': 'date', 'operation_type': 'timestamp', 'new_column': 'ts', 'unit': 'us'},
    )
    result = lf.collect()['ts'].to_list()
    assert all(isinstance(v, int) for v in result)
    assert len(result) == 3


def test_timeseries_subtract():
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {
            'column': 'date',
            'operation_type': 'subtract',
            'new_column': 'earlier',
            'unit': 'days',
            'value': 1,
        },
    )
    assert lf.collect()['earlier'][0].day == 31


def test_timeseries_diff():
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {
            'column': 'date',
            'operation_type': 'diff',
            'new_column': 'delta',
            'column2': 'date2',
        },
    )
    result = lf.collect()
    assert 'delta' in result.columns


def test_timeseries_months_offset():
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {
            'column': 'date',
            'operation_type': 'add',
            'new_column': 'shifted',
            'unit': 'months',
            'value': 2,
        },
    )
    assert lf.collect()['shifted'][0].month == 3


def test_timeseries_truncate():
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {
            'column': 'date',
            'operation_type': 'truncate',
            'new_column': 'truncated',
            'unit': 'days',
        },
    )
    result = lf.collect()['truncated'][0]
    assert result.hour == 0
    assert result.minute == 0


def test_timeseries_round():
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {
            'column': 'date',
            'operation_type': 'round',
            'new_column': 'rounded',
            'unit': 'hours',
        },
    )
    result = lf.collect()
    assert 'rounded' in result.columns
    assert result['rounded'][0].minute == 0


def test_timeseries_extract_dayofweek():
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {'column': 'date', 'operation_type': 'extract', 'new_column': 'dow', 'component': 'dayofweek'},
    )
    result = lf.collect()['dow'].to_list()
    assert all(isinstance(v, int) for v in result)


def test_timeseries_unsupported_operation():
    handler = TimeseriesHandler()
    with pytest.raises(ValidationError, match='operation_type'):
        handler(
            _frame(),
            {'column': 'date', 'operation_type': 'bogus', 'new_column': 'x'},
        ).collect()


def test_timeseries_accepts_enum_fields() -> None:
    handler = TimeseriesHandler()
    lf = handler(
        _frame(),
        {
            'column': 'date',
            'operation_type': TimeseriesOperationType.EXTRACT,
            'new_column': 'dow',
            'component': TimeComponent.DAYOFWEEK,
        },
    )
    result = lf.collect()['dow'].to_list()
    assert all(isinstance(v, int) for v in result)


def test_timeseries_add_missing_value():
    handler = TimeseriesHandler()
    with pytest.raises(ValueError, match='requires numeric value'):
        handler(
            _frame(),
            {'column': 'date', 'operation_type': 'add', 'new_column': 'x', 'unit': 'days'},
        ).collect()


def test_timeseries_add_missing_unit():
    handler = TimeseriesHandler()
    with pytest.raises(ValueError, match='requires unit'):
        handler(
            _frame(),
            {'column': 'date', 'operation_type': 'add', 'new_column': 'x', 'value': 1},
        ).collect()


def test_timeseries_diff_missing_column2():
    handler = TimeseriesHandler()
    with pytest.raises(ValueError, match='requires column2'):
        handler(
            _frame(),
            {'column': 'date', 'operation_type': 'diff', 'new_column': 'x'},
        ).collect()


def test_timeseries_truncate_missing_unit():
    handler = TimeseriesHandler()
    with pytest.raises(ValueError, match='requires unit'):
        handler(
            _frame(),
            {'column': 'date', 'operation_type': 'truncate', 'new_column': 'x'},
        ).collect()


def test_string_transform_uppercase():
    handler = StringTransformHandler()
    lf = handler(_frame(), {'column': 'name', 'method': 'uppercase', 'new_column': 'name_upper'})
    assert lf.collect()['name_upper'].to_list()[0] == 'ALICE'


def test_string_transform_accepts_enum_method() -> None:
    handler = StringTransformHandler()
    lf = handler(
        _frame(),
        {'column': 'name', 'method': StringTransformMethod.UPPERCASE, 'new_column': 'name_upper'},
    )
    assert lf.collect()['name_upper'].to_list()[0] == 'ALICE'


def test_fill_null_literal():
    handler = FillNullHandler()
    lf = handler(
        pl.DataFrame({'a': [1, None]}).lazy(),
        {'strategy': 'literal', 'value': 0, 'value_type': 'Int64'},
    )
    assert lf.collect()['a'].to_list() == [1, 0]


def test_join_handler_inner_correctness():
    handler = JoinHandler()
    left = pl.DataFrame({'id': [1, 2], 'val': ['a', 'b']}).lazy()
    right = pl.DataFrame({'id': [2, 3], 'val2': ['x', 'y']}).lazy()
    lf = handler(
        left,
        {
            'join_columns': [{'left_column': 'id', 'right_column': 'id'}],
            'how': 'inner',
            'right_source': 'right',
        },
        right_lf=right,
    )
    result = lf.collect()
    assert result.height == 1
    assert result['val'].to_list() == ['b']
    assert result['val2'].to_list() == ['x']


def test_with_columns_zero_arg_udf_uses_row_count(monkeypatch: pytest.MonkeyPatch):
    handler = WithColumnsHandler()
    lf = pl.DataFrame({'id': [1, 2]}).lazy()

    called = {'int_range': 0, 'lit': 0}
    original_int_range = pl.int_range
    original_lit = pl.lit

    def track_int_range(*args: Any, **kwargs: Any) -> pl.Expr:
        called['int_range'] += 1
        return original_int_range(*args, **kwargs)

    def track_lit(*args: Any, **kwargs: Any) -> pl.Expr:
        called['lit'] += 1
        return original_lit(*args, **kwargs)

    monkeypatch.setattr(pl, 'int_range', track_int_range)
    monkeypatch.setattr(pl, 'lit', track_lit)

    result = handler(
        lf,
        {
            'expressions': [
                {
                    'name': 'udf_col',
                    'type': 'udf',
                    'code': 'def udf():\n    return 1',
                },
            ],
        },
    )

    assert result is not None
    assert called['int_range'] == 1
    assert called['lit'] == 0


def test_with_columns_accepts_enum_expression_type() -> None:
    handler = WithColumnsHandler()
    lf = handler(
        pl.DataFrame({'id': [1]}).lazy(),
        {'expressions': [{'name': 'copy_id', 'type': WithColumnsExprType.COLUMN, 'column': 'id'}]},
    )
    assert lf.collect()['copy_id'].to_list() == [1]


def test_expression_rejects_dunder_escape() -> None:
    with pytest.raises(ValueError, match='forbidden dunder access'):
        parse_expression('pl.col("age").__class__')


def test_with_columns_rejects_reflection_escape() -> None:
    handler = WithColumnsHandler()
    with pytest.raises(ValueError, match='forbidden pattern'):
        handler(
            pl.DataFrame({'id': [1]}).lazy(),
            {'expressions': [{'name': 'bad', 'type': 'udf', 'code': 'def udf():\n    return globals()'}]},
        )


def test_with_columns_rejects_aliased_globals_escape() -> None:
    handler = WithColumnsHandler()
    with pytest.raises(NameError, match='globals'):
        handler(
            pl.DataFrame({'id': [1]}).lazy(),
            {'expressions': [{'name': 'bad', 'type': 'udf', 'code': 'global g\ng = globals\ndef udf():\n    return len(g())'}]},
        )


def test_union_by_name_handler():
    handler = UnionByNameHandler()
    left = pl.DataFrame({'id': [1]}).lazy()
    right = pl.DataFrame({'id': [2]}).lazy()
    lf = handler(left, {'sources': ['right'], 'allow_missing': True}, right_sources={'right': right})
    assert lf.collect().height == 2


def test_pivot_handler():
    handler = PivotHandler()
    lf = handler(
        pl.DataFrame({'idx': ['a', 'a'], 'col': ['x', 'y'], 'val': [1, 2]}).lazy(),
        {
            'index': ['idx'],
            'columns': 'col',
            'values': 'val',
            'aggregate_function': 'first',
            'on_columns': ['x', 'y'],
        },
    )
    result = lf.collect()
    assert 'x' in result.columns


def test_pivot_handler_auto_discovers_on_columns_for_small_cardinality():
    handler = PivotHandler()
    lf = handler(
        pl.DataFrame({'idx': ['a', 'a'], 'col': ['x', 'y'], 'val': [1, 2]}).lazy(),
        {
            'index': ['idx'],
            'columns': 'col',
            'values': 'val',
            'aggregate_function': 'first',
        },
    )
    result = lf.collect()
    assert result.columns == ['idx', 'x', 'y']


def test_pivot_handler_rejects_unbounded_auto_discovery(monkeypatch: pytest.MonkeyPatch):
    handler = PivotHandler()
    monkeypatch.setattr('modules.compute.operations.pivot._MAX_AUTO_PIVOT_VALUES', 2)
    with pytest.raises(ValueError, match='requires explicit on_columns'):
        handler(
            pl.DataFrame({'idx': ['a', 'a', 'a'], 'col': ['x', 'y', 'z'], 'val': [1, 2, 3]}).lazy(),
            {
                'index': ['idx'],
                'columns': 'col',
                'values': 'val',
                'aggregate_function': 'first',
            },
        )


def test_select_and_sort_handlers():
    select = SelectHandler()
    sort = SortHandler()
    lf = select(_frame(), {'columns': ['age']})
    lf = sort(lf, {'columns': ['age'], 'descending': [True]})
    assert lf.collect()['age'].to_list()[0] == 40


def test_select_handler_cast_map():
    handler = SelectHandler()
    lf = handler(
        pl.DataFrame({'age': ['30', '25'], 'name': ['Alice', 'Bob']}).lazy(),
        {'columns': ['age', 'name'], 'cast_map': {'age': 'Int64'}},
    )
    result = lf.collect()
    assert result.schema['age'] == pl.Int64()
    assert result['age'].to_list() == [30, 25]


def test_select_handler_cast_map_invalid_type():
    handler = SelectHandler()
    with pytest.raises(ValidationError, match='cast_map'):
        handler(
            pl.DataFrame({'age': ['30']}).lazy(),
            {'columns': ['age'], 'cast_map': {'age': 'Nope'}},
        ).collect()


def test_select_handler_cast_map_non_selected_column():
    handler = SelectHandler()
    with pytest.raises(ValueError, match='cast_map keys must reference selected columns'):
        handler(
            pl.DataFrame({'age': ['30'], 'name': ['Alice']}).lazy(),
            {'columns': ['age'], 'cast_map': {'name': 'String'}},
        ).collect()
