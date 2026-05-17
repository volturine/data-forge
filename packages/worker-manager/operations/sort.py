"""Sort rows operation."""

import polars as pl
from contracts.compute.base import OperationHandler, OperationParams


class SortParams(OperationParams):
    columns: list[str]
    descending: list[bool] | bool = False


class SortHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = SortParams.model_validate(params)
        return lf.sort(validated.columns, descending=validated.descending)
