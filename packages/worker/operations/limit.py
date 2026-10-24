"""Limit rows operation."""

import polars as pl

from runtime.domain.compute.base import OperationParams


class LimitParams(OperationParams):
    n: int = 10


def limit(lf: pl.LazyFrame, params: LimitParams, **_) -> pl.LazyFrame:
    return lf.head(params.n)
