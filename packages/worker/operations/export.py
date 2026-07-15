"""Export passthrough operation."""

import polars as pl

from dataforge_protocol import enums_pb2
from runtime.domain.compute.base import OperationHandler, OperationParams


class ExportParams(OperationParams):
    format: int = enums_pb2.EXPORT_FORMAT_CSV
    filename: str = "export"
    destination: int = enums_pb2.EXPORT_DESTINATION_DOWNLOAD
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
