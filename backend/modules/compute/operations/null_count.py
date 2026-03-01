"""Null count profiling operation."""

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class NullCountParams(OperationParams):
    pass


class NullCountHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        NullCountParams.model_validate(params)
        return lf.select(pl.all().null_count())
