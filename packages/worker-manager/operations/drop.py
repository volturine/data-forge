"""Drop columns operation."""

import polars as pl
from contracts.compute.base import OperationHandler, OperationParams


class DropParams(OperationParams):
    columns: list[str]


class DropHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = DropParams.model_validate(params)
        return lf.drop(validated.columns)
