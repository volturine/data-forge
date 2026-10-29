"""Top-K rows operation."""

import polars as pl

from runtime.domain.compute.base import OperationParams


class TopKParams(OperationParams):
    column: str
    k: int = 10
    descending: bool = False


def topk(lf: pl.LazyFrame, params: TopKParams, **_) -> pl.LazyFrame:
    return lf.sort(params.column, descending=params.descending, maintain_order=True).head(params.k)
