"""Limit rows operation."""

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class LimitParams(OperationParams):
    n: int = 10


class LimitHandler(OperationHandler):
    @property
    def name(self) -> str:
        return 'limit'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = LimitParams.model_validate(params)
        return lf.head(validated.n)
