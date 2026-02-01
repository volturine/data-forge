"""Sort rows operation."""

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class SortParams(OperationParams):
    columns: list[str]
    descending: list[bool] | bool = False


class SortHandler(OperationHandler):
    @property
    def name(self) -> str:
        return 'sort'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = SortParams.model_validate(params)
        return lf.sort(validated.columns, descending=validated.descending)
