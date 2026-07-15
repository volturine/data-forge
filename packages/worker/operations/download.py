"""Download operation - downloads the LazyFrame at any point in the pipeline."""

import polars as pl

from dataforge_protocol import enums_pb2
from runtime.domain.compute.base import OperationHandler, OperationParams


class DownloadParams(OperationParams):
    format: int = enums_pb2.EXPORT_FORMAT_CSV
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
