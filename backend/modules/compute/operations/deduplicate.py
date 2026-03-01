"""Deduplicate rows operation."""

from typing import Literal

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class DeduplicateParams(OperationParams):
    subset: list[str] | None = None
    keep: Literal['first', 'last', 'any', 'none'] = 'first'


class DeduplicateHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = DeduplicateParams.model_validate(params)
        return lf.unique(subset=validated.subset, keep=validated.keep, maintain_order=True)
