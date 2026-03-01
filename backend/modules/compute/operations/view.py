"""View passthrough operation."""

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class ViewParams(OperationParams):
    rowLimit: int | None = None


class ViewHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        ViewParams.model_validate(params)
        return lf
