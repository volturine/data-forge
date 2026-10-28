"""Explode list columns operation."""

import polars as pl
from pydantic import Field

from runtime.domain.compute.base import OperationParams


class ExplodeParams(OperationParams):
    columns: list[str] = Field(min_length=1)


def explode(lf: pl.LazyFrame, params: ExplodeParams, **_) -> pl.LazyFrame:
    return lf.explode(params.columns)
