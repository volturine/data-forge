"""Deduplicate rows operation."""

from enum import StrEnum

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class DeduplicateKeep(StrEnum):
    FIRST = 'first'
    LAST = 'last'
    ANY = 'any'
    NONE = 'none'


class DeduplicateParams(OperationParams):
    subset: list[str] | None = None
    keep: DeduplicateKeep = DeduplicateKeep.FIRST


class DeduplicateHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = DeduplicateParams.model_validate(params)
        if validated.keep == DeduplicateKeep.FIRST:
            return lf.unique(subset=validated.subset, keep='first', maintain_order=True)
        if validated.keep == DeduplicateKeep.LAST:
            return lf.unique(subset=validated.subset, keep='last', maintain_order=True)
        if validated.keep == DeduplicateKeep.ANY:
            return lf.unique(subset=validated.subset, keep='any', maintain_order=True)
        return lf.unique(subset=validated.subset, keep='none', maintain_order=True)
