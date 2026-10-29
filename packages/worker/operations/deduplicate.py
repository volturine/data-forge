"""Deduplicate rows operation."""

import polars as pl

from operations.enums import DeduplicateKeep
from runtime.domain.compute.base import OperationParams


class DeduplicateParams(OperationParams):
    subset: list[str] | None = None
    keep: DeduplicateKeep = DeduplicateKeep.FIRST


def deduplicate(lf: pl.LazyFrame, params: DeduplicateParams, **_) -> pl.LazyFrame:
    return lf.unique(subset=params.subset, keep=params.keep.polars_keep, maintain_order=True)
