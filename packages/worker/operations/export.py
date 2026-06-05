"""Export passthrough operation."""

import polars as pl

from worker_models.compute.base import OperationHandler, OperationParams


class ExportParams(OperationParams):
    format: str = "csv"
    filename: str = "export"
    destination: str = "download"
    iceberg_options: dict | None = None


class ExportHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        ExportParams.model_validate(params)
        return lf
