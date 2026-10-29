import logging
from collections.abc import Callable
from typing import cast

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from operations.enums import (
    AxisScale,
    ChartAggregation,
    ChartHeight,
    ChartWidth,
    DateBucket,
    DateOrdinal,
    DisplayUnits,
    GroupSortBy,
    LegendPosition,
    OverlayChartType,
    ReferenceAxis,
    SortBy,
    SortDirection,
    StackMode,
    YAxisPosition,
)
from runtime.domain.analysis.step_types import ChartType
from runtime.domain.compute.base import OperationParams

logger = logging.getLogger(__name__)


class OverlayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chart_type: OverlayChartType = OverlayChartType.LINE
    y_column: str
    aggregation: ChartAggregation = ChartAggregation.SUM
    y_axis_position: YAxisPosition = YAxisPosition.LEFT


class ReferenceLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    axis: ReferenceAxis
    value: float | None = None
    label: str | None = None
    color: str | None = None


class ChartParams(OperationParams):
    chart_type: ChartType = ChartType.BAR
    x_column: str
    y_column: str | None = None
    bins: int = 10
    aggregation: ChartAggregation = ChartAggregation.SUM
    group_column: str | None = None
    group_sort_by: GroupSortBy | None = None
    group_sort_order: SortDirection = SortDirection.ASC
    group_sort_column: str | None = None
    stack_mode: StackMode = StackMode.GROUPED
    area_opacity: float = 0.35
    date_bucket: DateBucket | None = None
    date_ordinal: DateOrdinal | None = None
    sort_by: SortBy | None = None
    sort_order: SortDirection = SortDirection.ASC
    sort_column: str | None = None
    x_axis_label: str | None = None
    y_axis_label: str | None = None
    y_axis_scale: AxisScale = AxisScale.LINEAR
    y_axis_min: float | None = None
    y_axis_max: float | None = None
    display_units: DisplayUnits = DisplayUnits.NONE
    decimal_places: int = 2
    legend_position: LegendPosition = LegendPosition.RIGHT
    title: str | None = None
    series_colors: list[str] = Field(default_factory=list)
    overlays: list[OverlayConfig] = Field(default_factory=list)
    reference_lines: list[ReferenceLine] = Field(default_factory=list)
    chart_height: ChartHeight = ChartHeight.MEDIUM
    chart_width: ChartWidth = ChartWidth.NORMAL
    pan_zoom_enabled: bool = False
    selection_enabled: bool = False
    area_selection_enabled: bool = False


def compute_chart_data(lf: pl.LazyFrame, params: dict) -> pl.LazyFrame:
    """Compute visualization data for a chart step.

    This is called separately from the pipeline DAG — chart steps are pass-through
    in the DAG but produce visualization data when previewed directly.
    """
    return _compute_chart(lf, ChartParams.model_validate(params))


def _compute_chart(lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
    if p.chart_type in (ChartType.BAR, ChartType.HORIZONTAL_BAR, ChartType.LINE, ChartType.AREA):
        return _aggregate_grouped(lf, p)
    if p.chart_type == ChartType.PIE:
        return _aggregate_pie(lf, p)
    if p.chart_type == ChartType.HEATGRID:
        return _aggregate_heatgrid(lf, p)
    if p.chart_type == ChartType.HISTOGRAM:
        return _build_histogram(lf, p)
    if p.chart_type == ChartType.SCATTER:
        return _build_scatter(lf, p)
    if p.chart_type == ChartType.BOXPLOT:
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
        overlay_params = params.model_copy(
            update={
                "chart_type": ChartType.require(overlay.chart_type.value),
                "y_column": overlay.y_column,
                "aggregation": overlay.aggregation,
                "group_column": None,
                "group_sort_by": None,
                "group_sort_column": None,
            },
        )
        overlay_lf = _compute_chart(lf, overlay_params)
        overlay_df = overlay_lf.slice(offset, row_limit).collect()
        datasets.append(
            {
                "chart_type": overlay.chart_type.value,
                "y_axis_position": overlay.y_axis_position.value,
                "y_column": overlay.y_column,
                "aggregation": overlay.aggregation.value,
                "data": overlay_df.to_dicts(),
            },
        )

    return datasets


# --- Chart computation functions (used by compute_chart_data) ---


_CHART_AGGREGATION_EXPRS: dict[ChartAggregation, Callable[[str], pl.Expr]] = {
    ChartAggregation.SUM: lambda column: pl.col(column).sum(),
    ChartAggregation.MEAN: lambda column: pl.col(column).mean(),
    ChartAggregation.COUNT: lambda column: pl.col(column).count(),
    ChartAggregation.MIN: lambda column: pl.col(column).min(),
    ChartAggregation.MAX: lambda column: pl.col(column).max(),
    ChartAggregation.MEDIAN: lambda column: pl.col(column).median(),
    ChartAggregation.STD: lambda column: pl.col(column).std(),
    ChartAggregation.VARIANCE: lambda column: pl.col(column).var(),
    ChartAggregation.UNIQUE_COUNT: lambda column: pl.col(column).n_unique(),
}


def _agg_expr(col: str, agg: ChartAggregation, *, alias: str = "y") -> pl.Expr:
    return _CHART_AGGREGATION_EXPRS[agg](col).alias(alias)


def _apply_sort(df: pl.LazyFrame, p: ChartParams, *, x_column: str, y_column: str) -> pl.LazyFrame:
    descending = p.sort_order == SortDirection.DESC
    if p.sort_by == SortBy.X:
        return df.sort(x_column, descending=descending)
    if p.sort_by == SortBy.Y:
        return df.sort(y_column, descending=descending)
    if p.sort_by == SortBy.CUSTOM and p.sort_column:
        return df.sort(p.sort_column, descending=descending)
    return df


def _apply_date_bucket(lf: pl.LazyFrame, column: str, p: ChartParams) -> pl.LazyFrame:
    if p.date_bucket is None and p.date_ordinal is None:
        return lf

    schema = lf.collect_schema()
    dtype = schema.get(column)
    if dtype == pl.Utf8:
        lf = lf.with_columns(pl.col(column).str.to_datetime(strict=False).alias(column))

    if p.date_bucket:
        if p.date_bucket == DateBucket.EXACT:
            return lf
        bucket_map = {
            DateBucket.YEAR: "1y",
            DateBucket.QUARTER: "1q",
            DateBucket.MONTH: "1mo",
            DateBucket.WEEK: "1w",
            DateBucket.DAY: "1d",
            DateBucket.HOUR: "1h",
        }
        return lf.with_columns(pl.col(column).dt.truncate(bucket_map[p.date_bucket]).alias(column))

    if p.date_ordinal == DateOrdinal.DAY_OF_WEEK:
        return lf.with_columns((pl.col(column).dt.weekday() - 1).alias(column))
    if p.date_ordinal == DateOrdinal.MONTH_OF_YEAR:
        return lf.with_columns(pl.col(column).dt.month().alias(column))
    if p.date_ordinal == DateOrdinal.QUARTER_OF_YEAR:
        return lf.with_columns(pl.col(column).dt.quarter().alias(column))

    return lf


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

    descending = p.group_sort_order == SortDirection.DESC
    order: pl.LazyFrame | None = None
    if p.group_sort_by == GroupSortBy.NAME:
        order = df.select(pl.col(group_key)).unique().sort(group_key, descending=descending)

    value_col: str | None = None
    if p.group_sort_by == GroupSortBy.CUSTOM and p.group_sort_column:
        value_col = p.group_sort_column
    elif p.group_sort_by == GroupSortBy.VALUE:
        value_col = "y"
    if value_col is not None and value_col not in schema:
        if order_lf is None:
            return df
        order_schema = order_lf.collect_schema()
        if group_key not in order_schema or value_col not in order_schema:
            return df
    if order is None and value_col == "y":
        order_source = df
        if order_lf is not None:
            order_source = order_lf
        order = order_source.group_by(group_key).agg(pl.col("y").first().alias("_group_value")).sort("_group_value", descending=descending).select(group_key)
    if order is None and value_col is not None and value_col != "y":
        source = df
        if value_col not in schema and order_lf is not None:
            source = order_lf
        order = source.group_by(group_key).agg(pl.col(value_col).first().alias("_group_value")).sort("_group_value", descending=descending).select(group_key)
    if order is None:
        return df

    return (
        df.with_row_index("_row_order")
        .join(order.with_row_index("_group_order"), on=group_key)
        .sort(["_group_order", "_row_order"])
        .drop(["_group_order", "_row_order"])
    )


def _aggregate_grouped(lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
    lf = _apply_date_bucket(lf, p.x_column, p)
    group_cols = [p.x_column] + ([p.group_column] if p.group_column else [])

    group_order_lf: pl.LazyFrame | None = None
    if p.group_sort_by == GroupSortBy.CUSTOM and p.group_sort_column and p.group_column:
        group_order_lf = lf.select(p.group_column, p.group_sort_column)

    agg_expr = _agg_expr(p.y_column, p.aggregation) if p.y_column else pl.len().alias("y")

    result = lf.group_by(group_cols).agg(agg_expr).rename({p.x_column: "x"})
    sorted_result = result.sort("x") if p.sort_by is None else _apply_sort(result, p, x_column="x", y_column="y")
    return _apply_group_sort(sorted_result, p, order_lf=group_order_lf)


def _aggregate_pie(lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
    lf = _apply_date_bucket(lf, p.x_column, p)
    agg_expr = _agg_expr(p.y_column, p.aggregation) if p.y_column else pl.len().alias("y")

    group_cols = [p.x_column] + ([p.group_column] if p.group_column else [])

    result = lf.group_by(group_cols).agg(agg_expr).rename({p.x_column: "label"})
    if p.group_column:
        result = result.rename({p.group_column: "group"})

    if p.sort_by == SortBy.X:
        sorted_result = result.sort("label", descending=p.sort_order == SortDirection.DESC)
    elif p.sort_by == SortBy.Y:
        sorted_result = result.sort("y", descending=p.sort_order == SortDirection.DESC)
    elif p.sort_by == SortBy.CUSTOM and p.sort_column:
        sorted_result = result.sort(p.sort_column, descending=p.sort_order == SortDirection.DESC)
    else:
        sorted_result = result.sort("y", descending=True)

    if p.group_column:
        group_order_lf = None
        if p.group_sort_by == GroupSortBy.CUSTOM and p.group_sort_column:
            group_order_lf = lf.select(
                pl.col(p.group_column).alias("group"),
                pl.col(p.group_sort_column).alias(p.group_sort_column),
            )
        elif p.group_sort_by == GroupSortBy.VALUE:
            group_order_lf = result.sort("label").select("group", "y")
        return _apply_group_sort(sorted_result, p, group_col="group", order_lf=group_order_lf)
    return sorted_result


def _build_histogram(lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
    col = p.x_column
    bins = p.bins

    df = lf.select(pl.col(col).cast(pl.Float64).alias("value")).collect()

    if df.is_empty():
        return pl.LazyFrame({"bin_start": [], "bin_end": [], "count": []})

    min_raw = df["value"].min()
    max_raw = df["value"].max()

    if min_raw is None or max_raw is None:
        return pl.LazyFrame({"bin_start": [], "bin_end": [], "count": []})

    # Column is cast to Float64 above, so min/max are always float.
    # Polars type stubs return PythonLiteral; explicit cast narrows for mypy.
    fmin = float(cast(float, min_raw))
    fmax = float(cast(float, max_raw))

    if fmin == fmax:
        return pl.LazyFrame(
            {
                "bin_start": [fmin],
                "bin_end": [fmax],
                "count": [len(df)],
            },
        )

    bin_width = (fmax - fmin) / bins

    # Single vectorized pass: bucket every row via floor arithmetic instead of
    # one O(n) filter per bin.
    binned = df.select(((pl.col("value") - fmin) / bin_width).floor().cast(pl.Int64).clip(0, bins - 1).alias("bin_index")).group_by("bin_index").len()

    index_to_count = dict(zip(binned["bin_index"].to_list(), binned["len"].to_list(), strict=True))
    counts = [int(index_to_count.get(i, 0)) for i in range(bins)]

    result = pl.LazyFrame(
        {
            "bin_start": [fmin + i * bin_width for i in range(bins)],
            "bin_end": [fmin + (i + 1) * bin_width for i in range(bins)],
            "count": counts,
        },
    )
    return _apply_sort(result, p, x_column="bin_start", y_column="count")


def _build_scatter(lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
    return lf.select(
        [pl.col(p.x_column).alias("x")]
        + ([pl.col(p.y_column).alias("y")] if p.y_column else [])
        + ([pl.col(p.group_column).alias("group")] if p.group_column else []),
    ).limit(5000)


def _build_boxplot(lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
    col = p.x_column if not p.y_column else p.y_column
    group_col = p.x_column if p.y_column else None

    stats = [
        pl.col(col).min().alias("min"),
        pl.col(col).quantile(0.25).alias("q1"),
        pl.col(col).median().alias("median"),
        pl.col(col).quantile(0.75).alias("q3"),
        pl.col(col).max().alias("max"),
    ]
    result = lf.group_by(group_col).agg(stats).sort(group_col).rename({group_col: "group"}) if group_col else lf.select(*stats, pl.lit("all").alias("group"))
    if p.sort_by == SortBy.CUSTOM and p.sort_column:
        return result.sort(p.sort_column, descending=p.sort_order == SortDirection.DESC)
    return result


def _aggregate_heatgrid(lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
    if p.y_column is None:
        return pl.LazyFrame({"x": [], "y": [], "value": []})

    value_col = p.y_column
    agg_expr = _agg_expr(value_col, p.aggregation, alias="value")

    return lf.group_by([p.x_column, value_col]).agg(agg_expr).rename({p.x_column: "x", value_col: "y"})
