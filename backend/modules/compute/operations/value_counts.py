"""Value counts profiling operation."""

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class ValueCountsParams(OperationParams):
    column: str
    normalize: bool = False
    sort: bool = True


class ValueCountsHandler(OperationHandler):
    """Count unique values in a column."""

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = ValueCountsParams.model_validate(params)
        result = lf.group_by(validated.column).agg(pl.len().alias('count'))
        if validated.normalize:
            result = result.with_columns(pl.col('count') / pl.col('count').sum())
        if validated.sort:
            result = result.sort('count', descending=True)
        return result
