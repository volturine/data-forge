import logging
from typing import Literal

import polars as pl
from pydantic import ConfigDict

from modules.compute.core.base import OperationHandler, OperationParams

logger = logging.getLogger(__name__)


class ChartParams(OperationParams):
    model_config = ConfigDict(extra='forbid')

    chart_type: Literal['bar', 'histogram', 'scatter', 'line', 'pie', 'boxplot'] = 'bar'
    x_column: str
    y_column: str | None = None
    bins: int = 10
    aggregation: Literal['sum', 'mean', 'count', 'min', 'max'] = 'sum'
    group_column: str | None = None


class ChartHandler(OperationHandler):
    @property
    def name(self) -> str:
        return 'chart'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        p = ChartParams.model_validate(params)

        if p.chart_type == 'bar':
            return self._aggregate_bar(lf, p)
        if p.chart_type == 'line':
            return self._aggregate_line(lf, p)
        if p.chart_type == 'pie':
            return self._aggregate_pie(lf, p)
        if p.chart_type == 'histogram':
            return self._build_histogram(lf, p)
        if p.chart_type == 'scatter':
            return self._build_scatter(lf, p)
        if p.chart_type == 'boxplot':
            return self._build_boxplot(lf, p)

        return lf

    def _agg_expr(self, col: str, agg: str) -> pl.Expr:
        if agg == 'sum':
            return pl.col(col).sum().alias('y')
        if agg == 'mean':
            return pl.col(col).mean().alias('y')
        if agg == 'count':
            return pl.col(col).count().alias('y')
        if agg == 'min':
            return pl.col(col).min().alias('y')
        if agg == 'max':
            return pl.col(col).max().alias('y')
        return pl.col(col).sum().alias('y')

    def _aggregate_bar(self, lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
        group_cols = [p.x_column]
        if p.group_column:
            group_cols.append(p.group_column)

        agg_expr = self._agg_expr(p.y_column, p.aggregation) if p.y_column else pl.len().alias('y')

        result = lf.group_by(group_cols).agg(agg_expr).sort(p.x_column)
        return result.rename({p.x_column: 'x'})

    def _aggregate_line(self, lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
        group_cols = [p.x_column]
        if p.group_column:
            group_cols.append(p.group_column)

        agg_expr = self._agg_expr(p.y_column, p.aggregation) if p.y_column else pl.len().alias('y')

        result = lf.group_by(group_cols).agg(agg_expr).sort(p.x_column)
        return result.rename({p.x_column: 'x'})

    def _aggregate_pie(self, lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
        agg_expr = self._agg_expr(p.y_column, p.aggregation) if p.y_column else pl.len().alias('y')

        result = lf.group_by(p.x_column).agg(agg_expr).sort('y', descending=True)
        return result.rename({p.x_column: 'label'})

    def _build_histogram(self, lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
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

        counts = []
        for i in range(bins):
            start = bin_starts[i]
            end = bin_ends[i]
            if i < bins - 1:
                count = df.filter((pl.col('value') >= start) & (pl.col('value') < end)).height
            else:
                count = df.filter((pl.col('value') >= start) & (pl.col('value') <= end)).height
            counts.append(count)

        return pl.LazyFrame(
            {
                'bin_start': bin_starts,
                'bin_end': bin_ends,
                'count': counts,
            }
        )

    def _build_scatter(self, lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
        cols = [pl.col(p.x_column).alias('x')]
        if p.y_column:
            cols.append(pl.col(p.y_column).alias('y'))
        if p.group_column:
            cols.append(pl.col(p.group_column).alias('group'))

        return lf.select(cols).limit(5000)

    def _build_boxplot(self, lf: pl.LazyFrame, p: ChartParams) -> pl.LazyFrame:
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

        return result
