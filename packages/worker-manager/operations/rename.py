"""Rename columns operation."""

import polars as pl
from contracts.compute.base import OperationHandler, OperationParams


class RenameParams(OperationParams):
    mapping: dict[str, str]


class RenameHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = RenameParams.model_validate(params)
        return lf.rename(validated.mapping)
