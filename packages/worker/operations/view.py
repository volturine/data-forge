"""View passthrough operation."""

import polars as pl

from worker_models.compute.base import OperationHandler, OperationParams


class ViewParams(OperationParams):
    rowLimit: int | None = None


class ViewHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        ViewParams.model_validate(params)
        return lf
