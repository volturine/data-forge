"""Null count profiling operation."""

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class NullCountParams(OperationParams):
    pass


class NullCountHandler(OperationHandler):
    @property
    def name(self) -> str:
        return 'null_count'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        NullCountParams.model_validate(params)
        return lf.select(pl.all().null_count())
