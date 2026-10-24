"""Rename columns operation."""

import polars as pl

from runtime.domain.compute.base import OperationParams


class RenameParams(OperationParams):
    column_mapping: dict[str, str]


def rename(lf: pl.LazyFrame, params: RenameParams, **_) -> pl.LazyFrame:
    return lf.rename(params.column_mapping)
