"""Rename columns operation."""

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class RenameParams(OperationParams):
    mapping: dict[str, str]


class RenameHandler(OperationHandler):
    @property
    def name(self) -> str:
        return 'rename'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = RenameParams.model_validate(params)
        return lf.rename(validated.mapping)
