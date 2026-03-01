"""Drop columns operation."""

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class DropParams(OperationParams):
    columns: list[str]


class DropHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = DropParams.model_validate(params)
        return lf.drop(validated.columns)
