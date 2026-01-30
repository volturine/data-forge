"""Export passthrough operation."""

import polars as pl

from modules.compute.operations.base import OperationHandler, OperationParams


class ExportParams(OperationParams):
    format: str = 'csv'
    filename: str = 'export'
    destination: str = 'download'


class ExportHandler(OperationHandler):
    @property
    def name(self) -> str:
        return 'export'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        ExportParams.model_validate(params)
        return lf
