"""Sort rows operation."""

import polars as pl
from pydantic import Field

from runtime.domain.compute.base import OperationHandler, OperationParams


class SortParams(OperationParams):
    columns: list[str]
    descending: list[bool] = Field(default_factory=list)
    descending_all: bool | None = None


class SortHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = SortParams.model_validate(params)
        descending: list[bool] | bool = validated.descending_all if validated.descending_all is not None else validated.descending
        return lf.sort(validated.columns, descending=descending, maintain_order=True)
