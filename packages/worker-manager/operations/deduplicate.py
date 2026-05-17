"""Deduplicate rows operation."""

import polars as pl
from contracts.compute.base import OperationHandler, OperationParams
from contracts.step_config_enums import DeduplicateKeep


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
        return lf.unique(subset=validated.subset, keep=validated.keep.polars_keep, maintain_order=True)
