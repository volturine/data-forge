"""Download operation - downloads the LazyFrame at any point in the pipeline."""

import polars as pl
from contracts.compute.base import OperationHandler, OperationParams


class DownloadParams(OperationParams):
    format: str = "csv"
    filename: str = "download"


class DownloadHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        DownloadParams.model_validate(params)
        return lf
