"""Limit rows operation."""

import polars as pl
from contracts.compute.base import OperationHandler, OperationParams


class LimitParams(OperationParams):
    n: int = 10


class LimitHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = LimitParams.model_validate(params)
        return lf.head(validated.n)
