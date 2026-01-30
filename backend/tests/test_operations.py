import polars as pl

from modules.compute.operations.fill_null import FillNullHandler
from modules.compute.operations.filter import FilterHandler
from modules.compute.operations.groupby import GroupByHandler
from modules.compute.operations.join import JoinHandler
from modules.compute.operations.pivot import PivotHandler
from modules.compute.operations.select import SelectHandler
from modules.compute.operations.sort import SortHandler
from modules.compute.operations.strings import StringTransformHandler
from modules.compute.operations.timeseries import TimeseriesHandler
from modules.compute.operations.union import UnionByNameHandler


def _frame() -> pl.LazyFrame:
    frame = pl.DataFrame(
        {
            'name': ['Alice', 'Bob', 'Charlie'],
            'age': [30, 25, 40],
            'group': ['a', 'a', 'b'],
        }
    )
    return frame.with_columns(
        pl.datetime(2024, 1, 1).alias('date'),
        pl.datetime(2024, 1, 2).alias('date2'),
    ).lazy()


def test_filter_handler():
    handler = FilterHandler()
    lf = handler(
        _frame(),
        {'conditions': [{'column': 'age', 'operator': '>', 'value': 30}], 'logic': 'AND'},
    )
    assert lf.collect().height == 1


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


def test_string_transform_uppercase():
    handler = StringTransformHandler()
    lf = handler(_frame(), {'column': 'name', 'method': 'uppercase', 'new_column': 'name_upper'})
    assert lf.collect()['name_upper'].to_list()[0] == 'ALICE'


def test_fill_null_literal():
    handler = FillNullHandler()
    lf = handler(
        pl.DataFrame({'a': [1, None]}).lazy(),
        {'strategy': 'literal', 'value': 0, 'value_type': 'Int64'},
    )
    assert lf.collect()['a'].to_list() == [1, 0]


def test_join_handler_inner():
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
    assert lf.collect().height == 1


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


def test_select_and_sort_handlers():
    select = SelectHandler()
    sort = SortHandler()
    lf = select(_frame(), {'columns': ['age']})
    lf = sort(lf, {'columns': ['age'], 'descending': [True]})
    assert lf.collect()['age'].to_list()[0] == 40
