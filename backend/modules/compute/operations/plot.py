import logging
from typing import Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from modules.compute.core.base import OperationHandler, OperationParams

logger = logging.getLogger(__name__)


AggregationType = Literal[
    'sum',
    'mean',
    'count',
    'min',
    'max',
    'median',
    'std',
    'variance',
    'unique_count',
]


class OverlayConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    chart_type: Literal['line', 'area', 'bar', 'scatter'] = 'line'
    y_column: str
    aggregation: AggregationType = 'sum'
    y_axis_position: Literal['left', 'right'] = 'left'


class ReferenceLine(BaseModel):
    model_config = ConfigDict(extra='forbid')

    axis: Literal['x', 'y']
    value: float | None = None
    label: str | None = None
    color: str | None = None


class ChartParams(OperationParams):
    model_config = ConfigDict(extra='forbid')

    chart_type: Literal[
        'bar',
        'horizontal_bar',
        'area',
        'heatgrid',
        'histogram',
        'scatter',
        'line',
        'pie',
        'boxplot',
    ] = 'bar'
    x_column: str
    y_column: str | None = None
    bins: int = 10
    aggregation: AggregationType = 'sum'
    group_column: str | None = None
    group_sort_by: Literal['name', 'value', 'custom'] | None = None
    group_sort_order: Literal['asc', 'desc'] = 'asc'
    group_sort_column: str | None = None
    stack_mode: Literal['grouped', 'stacked', '100%'] = 'grouped'
    area_opacity: float = 0.35
    date_bucket: Literal['exact', 'year', 'quarter', 'month', 'week', 'day', 'hour'] | None = None
    date_ordinal: Literal['day_of_week', 'month_of_year', 'quarter_of_year'] | None = None
    sort_by: Literal['x', 'y', 'custom'] | None = None
    sort_order: Literal['asc', 'desc'] = 'asc'
    sort_column: str | None = None
    x_axis_label: str | None = None
    y_axis_label: str | None = None
    y_axis_scale: Literal['linear', 'log'] = 'linear'
    y_axis_min: float | None = None
    y_axis_max: float | None = None
    display_units: Literal['', 'K', 'M', 'B', '%'] = ''
    decimal_places: int = 2
    legend_position: Literal['top', 'bottom', 'left', 'right', 'none'] = 'right'
    title: str | None = None
    series_colors: list[str] = []
    overlays: list[OverlayConfig] = Field(default_factory=list)
    reference_lines: list[ReferenceLine] = Field(default_factory=list)
    pan_zoom_enabled: bool = False
    selection_enabled: bool = False
    area_selection_enabled: bool = False


def compute_chart_data(lf: pl.LazyFrame, params: dict) -> pl.LazyFrame:
    """Compute visualization data for a chart step.

    This is called separately from the pipeline DAG — chart steps are pass-through
    in the DAG but produce visualization data when previewed directly.
    """
    p = ChartParams.model_validate(params)

    if p.chart_type in ('bar', 'horizontal_bar'):
        return _aggregate_bar(lf, p)
    if p.chart_type in ('line', 'area'):
        return _aggregate_line(lf, p)
    if p.chart_type == 'pie':
        return _aggregate_pie(lf, p)
    if p.chart_type == 'heatgrid':
        return _aggregate_heatgrid(lf, p)
    if p.chart_type == 'histogram':
        return _build_histogram(lf, p)
    if p.chart_type == 'scatter':
        return _build_scatter(lf, p)
    if p.chart_type == 'boxplot':
        return _build_boxplot(lf, p)

    return lf


def compute_overlay_datasets(
    lf: pl.LazyFrame,
    params: ChartParams,
    *,
    row_limit: int,
    offset: int,
) -> list[dict]:
    datasets: list[dict] = []
    if not params.overlays:
        return datasets

    for overlay in params.overlays:
        overlay_params: dict[str, object] = {
            'chart_type': overlay.chart_type,
            'x_column': params.x_column,
            'y_column': overlay.y_column,
            'aggregation': overlay.aggregation,
            'bins': params.bins,
            'group_column': None,
            'group_sort_by': None,
            'group_sort_order': params.group_sort_order,
            'group_sort_column': None,
            'stack_mode': params.stack_mode,
            'area_opacity': params.area_opacity,
            'date_bucket': params.date_bucket,
            'date_ordinal': params.date_ordinal,
            'sort_by': params.sort_by,
            'sort_order': params.sort_order,
            'sort_column': params.sort_column,
        }
        overlay_lf = compute_chart_data(lf, overlay_params)
        overlay_df = overlay_lf.slice(offset, row_limit).collect()
        datasets.append(
            {
                'chart_type': overlay.chart_type,
                'y_axis_position': overlay.y_axis_position,
                'y_column': overlay.y_column,
                'aggregation': overlay.aggregation,
                'data': overlay_df.to_dicts(),
            }
        )

    return datasets


class ChartHandler(OperationHandler):
    """Chart handler — pass-through for DAG.

    Chart nodes do NOT modify the pipeline data. They exist for visualization only.
    Downstream steps receive the same data as if the chart node were not there.
    Visualization data is computed separately via compute_chart_data().
    """

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        # Validate params but return input unchanged — chart is pass-through
        ChartParams.model_validate(params)
        return lf


# --- Chart computation functions (used by compute_chart_data) ---


def _agg_expr(col: str, agg: str) -> pl.Expr:
    if agg == 'sum':
        return pl.col(col).sum().alias('y')
    if agg == 'mean':
        return pl.col(col).mean().alias('y')
    if agg == 'median':
        return pl.col(col).median().alias('y')
    if agg == 'std':
        return pl.col(col).std().alias('y')
    if agg == 'variance':
        return pl.col(col).var().alias('y')
    if agg == 'unique_count':
        return pl.col(col).n_unique().alias('y')
    if agg == 'count':
        return pl.col(col).count().alias('y')
    if agg == 'min':
        return pl.col(col).min().alias('y')
    if agg == 'max':
        return pl.col(col).max().alias('y')
    return pl.col(col).sum().alias('y')


def _apply_sort(df: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
    if p.sort_by is None:
        return df.sort('x')
    order_desc = p.sort_order == 'desc'
    if p.sort_by == 'x':
        return df.sort('x', descending=order_desc)
    if p.sort_by == 'y':
        return df.sort('y', descending=order_desc)
    if p.sort_by == 'custom' and p.sort_column:
        return df.sort(p.sort_column, descending=order_desc)
    return df


def _apply_date_bucket(lf: pl.LazyFrame, column: str, p: ChartParams) -> pl.LazyFrame:
    if p.date_bucket is None and p.date_ordinal is None:
        return lf

    schema = lf.collect_schema()
    dtype = schema.get(column)
    if dtype == pl.Utf8:
        lf = lf.with_columns(pl.col(column).str.to_datetime(strict=False).alias(column))

    if p.date_bucket:
        if p.date_bucket == 'exact':
            return lf
        bucket_map = {
            'year': '1y',
            'quarter': '1q',
            'month': '1mo',
            'week': '1w',
            'day': '1d',
            'hour': '1h',
        }
        if (duration := bucket_map.get(p.date_bucket)) is None:
            return lf
        return lf.with_columns(pl.col(column).dt.truncate(duration).alias(column))

    if p.date_ordinal == 'day_of_week':
        return lf.with_columns((pl.col(column).dt.weekday() - 1).alias(column))
    if p.date_ordinal == 'month_of_year':
        return lf.with_columns(pl.col(column).dt.month().alias(column))
    if p.date_ordinal == 'quarter_of_year':
        return lf.with_columns(pl.col(column).dt.quarter().alias(column))

    return lf


def _group_sort_value_col(p: ChartParams) -> str | None:
    if p.group_sort_by == 'custom' and p.group_sort_column:
        return p.group_sort_column
    if p.group_sort_by == 'value':
        return 'y'
    return None


def _apply_group_sort(
    df: pl.LazyFrame,
    p: ChartParams,
    group_col: str | None = None,
    order_lf: pl.LazyFrame | None = None,
) -> pl.LazyFrame:
    group_key = group_col or p.group_column
    if group_key is None:
        return df
    if p.group_sort_by is None:
        return df

    schema = df.collect_schema()
    if group_key not in schema:
        return df

    descending = p.group_sort_order == 'desc'
    order: pl.LazyFrame | None = None
    if p.group_sort_by == 'name':
        order = df.select(pl.col(group_key)).unique().sort(group_key, descending=descending)

    value_col = _group_sort_value_col(p)
    if value_col is not None and value_col not in schema:
        if order_lf is None:
            return df
        order_schema = order_lf.collect_schema()
        if group_key not in order_schema or value_col not in order_schema:
            return df
    if order is None and value_col == 'y':
        order_source = df
        if order_lf is not None:
            order_source = order_lf
        order = (
            order_source.group_by(group_key)
            .agg(pl.col('y').first().alias('_group_value'))
            .sort('_group_value', descending=descending)
            .select(group_key)
        )
    if order is None and value_col is not None and value_col != 'y':
        source = df
        if value_col not in schema and order_lf is not None:
            source = order_lf
        order = (
            source.group_by(group_key)
            .agg(pl.col(value_col).first().alias('_group_value'))
            .sort('_group_value', descending=descending)
            .select(group_key)
        )
    if order is None:
        return df

    return (
        df.with_row_index('_row_order')
        .join(order.with_row_index('_group_order'), on=group_key)
        .sort(['_group_order', '_row_order'])
        .drop(['_group_order', '_row_order'])
    )


def _aggregate_bar(lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
    lf = _apply_date_bucket(lf, p.x_column, p)
    group_cols = [p.x_column] + ([p.group_column] if p.group_column else [])

    group_order_lf: pl.LazyFrame | None = None
    if p.group_sort_by == 'custom' and p.group_sort_column and p.group_column:
        group_order_lf = lf.select(p.group_column, p.group_sort_column)

    agg_expr = _agg_expr(p.y_column, p.aggregation) if p.y_column else pl.len().alias('y')

    result = lf.group_by(group_cols).agg(agg_expr).rename({p.x_column: 'x'})
    sorted_result = _apply_sort(result, p)
    return _apply_group_sort(sorted_result, p, order_lf=group_order_lf)


def _aggregate_line(lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
    lf = _apply_date_bucket(lf, p.x_column, p)
    group_cols = [p.x_column] + ([p.group_column] if p.group_column else [])

    group_order_lf: pl.LazyFrame | None = None
    if p.group_sort_by == 'custom' and p.group_sort_column and p.group_column:
        group_order_lf = lf.select(p.group_column, p.group_sort_column)

    agg_expr = _agg_expr(p.y_column, p.aggregation) if p.y_column else pl.len().alias('y')

    result = lf.group_by(group_cols).agg(agg_expr).rename({p.x_column: 'x'})
    sorted_result = _apply_sort(result, p)
    return _apply_group_sort(sorted_result, p, order_lf=group_order_lf)


def _aggregate_pie(lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
    lf = _apply_date_bucket(lf, p.x_column, p)
    agg_expr = _agg_expr(p.y_column, p.aggregation) if p.y_column else pl.len().alias('y')

    group_cols = [p.x_column] + ([p.group_column] if p.group_column else [])

    result = lf.group_by(group_cols).agg(agg_expr).rename({p.x_column: 'label'})
    if p.group_column:
        result = result.rename({p.group_column: 'group'})

    if p.group_column:
        group_sorted = _apply_group_sort(result.rename({'label': 'x'}), p)
        result = group_sorted.rename({'x': 'label'})

    if p.sort_by == 'x':
        sorted_result = result.sort('label', descending=p.sort_order == 'desc')
    elif p.sort_by == 'y':
        sorted_result = result.sort('y', descending=p.sort_order == 'desc')
    elif p.sort_by == 'custom' and p.sort_column:
        sorted_result = result.sort(p.sort_column, descending=p.sort_order == 'desc')
    else:
        sorted_result = result.sort('y', descending=True)

    if p.group_column:
        group_order_lf = None
        if p.group_sort_by == 'custom' and p.group_sort_column:
            group_order_lf = lf.select(
                pl.col(p.group_column).alias('group'),
                pl.col(p.group_sort_column).alias(p.group_sort_column),
            )
        elif p.group_sort_by == 'value':
            group_order_lf = result.sort('label').select('group', 'y')
        return _apply_group_sort(sorted_result, p, group_col='group', order_lf=group_order_lf)
    return sorted_result


def _build_histogram(lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
    col = p.x_column
    bins = p.bins

    df = lf.select(pl.col(col).cast(pl.Float64).alias('value')).collect()

    if df.is_empty():
        return pl.LazyFrame({'bin_start': [], 'bin_end': [], 'count': []})

    min_raw = df['value'].min()
    max_raw = df['value'].max()

    if min_raw is None or max_raw is None:
        return pl.LazyFrame({'bin_start': [], 'bin_end': [], 'count': []})

    # Column is cast to Float64 above, so min/max are always float.
    # Polars type stubs return PythonLiteral; explicit cast narrows for mypy.
    fmin: float = float(min_raw)  # type: ignore[arg-type]
    fmax: float = float(max_raw)  # type: ignore[arg-type]

    if fmin == fmax:
        return pl.LazyFrame(
            {
                'bin_start': [fmin],
                'bin_end': [fmax],
                'count': [len(df)],
            }
        )

    bin_width = (fmax - fmin) / bins
    bin_starts = [fmin + i * bin_width for i in range(bins)]
    bin_ends = [fmin + (i + 1) * bin_width for i in range(bins)]

    counts = [
        df.filter((pl.col('value') >= bin_starts[i]) & (pl.col('value') < bin_ends[i])).height
        if i < bins - 1
        else df.filter((pl.col('value') >= bin_starts[i]) & (pl.col('value') <= bin_ends[i])).height
        for i in range(bins)
    ]

    result = pl.LazyFrame(
        {
            'bin_start': bin_starts,
            'bin_end': bin_ends,
            'count': counts,
        }
    )
    if p.sort_by == 'x':
        return result.sort('bin_start', descending=p.sort_order == 'desc')
    if p.sort_by == 'y':
        return result.sort('count', descending=p.sort_order == 'desc')
    if p.sort_by == 'custom' and p.sort_column:
        return result.sort(p.sort_column, descending=p.sort_order == 'desc')
    return result


def _build_scatter(lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
    return lf.select(
        [pl.col(p.x_column).alias('x')]
        + ([pl.col(p.y_column).alias('y')] if p.y_column else [])
        + ([pl.col(p.group_column).alias('group')] if p.group_column else [])
    ).limit(5000)


def _build_boxplot(lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
    col = p.x_column if not p.y_column else p.y_column
    group_col = p.x_column if p.y_column else None

    if group_col:
        result = (
            lf.group_by(group_col)
            .agg(
                pl.col(col).min().alias('min'),
                pl.col(col).quantile(0.25).alias('q1'),
                pl.col(col).median().alias('median'),
                pl.col(col).quantile(0.75).alias('q3'),
                pl.col(col).max().alias('max'),
            )
            .sort(group_col)
            .rename({group_col: 'group'})
        )
    else:
        result = lf.select(
            pl.col(col).min().alias('min'),
            pl.col(col).quantile(0.25).alias('q1'),
            pl.col(col).median().alias('median'),
            pl.col(col).quantile(0.75).alias('q3'),
            pl.col(col).max().alias('max'),
            pl.lit('all').alias('group'),
        )
    if p.sort_by == 'custom' and p.sort_column:
        return result.sort(p.sort_column, descending=p.sort_order == 'desc')
    return result


def _aggregate_heatgrid(lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
    if p.y_column is None:
        return pl.LazyFrame({'x': [], 'y': [], 'value': []})

    value_col = p.y_column
    agg_expr = _agg_expr(value_col, p.aggregation).alias('value')

    return lf.group_by([p.x_column, value_col]).agg(agg_expr).rename({p.x_column: 'x', value_col: 'y'})
