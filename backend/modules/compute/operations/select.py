"""Select columns operation."""

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class SelectParams(OperationParams):
    columns: list[str]


class SelectHandler(OperationHandler):
    @property
    def name(self) -> str:
        return 'select'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = SelectParams.model_validate(params)
        return lf.select(validated.columns)
