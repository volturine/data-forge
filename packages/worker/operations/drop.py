"""Drop columns operation."""

import polars as pl

from runtime.domain.compute.base import OperationParams


class DropParams(OperationParams):
    columns: list[str]


def drop(lf: pl.LazyFrame, params: DropParams, **_) -> pl.LazyFrame:
    return lf.drop(params.columns)
