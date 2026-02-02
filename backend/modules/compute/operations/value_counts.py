"""Value counts profiling operation."""

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class ValueCountsParams(OperationParams):
    column: str
    normalize: bool = False
    sort: bool = True


class ValueCountsHandler(OperationHandler):
    """Count unique values in a column."""

    @property
    def name(self) -> str:
        return 'value_counts'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = ValueCountsParams.model_validate(params)
        result = lf.group_by(validated.column).agg(pl.len().alias('count'))
        if validated.normalize:
            result = result.with_columns(pl.col('count') / pl.col('count').sum())
        if validated.sort:
            result = result.sort('count', descending=True)
        return result
