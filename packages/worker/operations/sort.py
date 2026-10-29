"""Sort rows operation."""

import polars as pl
from pydantic import Field

from runtime.domain.compute.base import OperationParams


class SortParams(OperationParams):
    columns: list[str]
    descending: list[bool] = Field(default_factory=list)
    descending_all: bool | None = None


def sort(lf: pl.LazyFrame, params: SortParams, **_) -> pl.LazyFrame:
    descending: list[bool] | bool = params.descending_all if params.descending_all is not None else params.descending
    return lf.sort(params.columns, descending=descending, maintain_order=True)
