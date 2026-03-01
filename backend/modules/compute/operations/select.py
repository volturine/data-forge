"""Select columns operation."""

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class SelectParams(OperationParams):
    columns: list[str]


class SelectHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = SelectParams.model_validate(params)
        return lf.select(validated.columns)
