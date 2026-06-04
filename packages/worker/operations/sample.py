"""Sample rows operation."""

import math

import polars as pl

from worker_contracts.compute.base import OperationHandler, OperationParams

_MAX_HASH = (1 << 64) - 1


class SampleParams(OperationParams):
    fraction: float
    seed: int | None = None


class SampleHandler(OperationHandler):
    """Sample rows using a deterministic hash-based approach for lazy evaluation."""

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = SampleParams.model_validate(params)
        if validated.fraction <= 0 or validated.fraction > 1:
            raise ValueError("Sample fraction must be between 0 and 1")
        if validated.fraction == 1:
            return lf
        threshold = max(1, math.ceil(validated.fraction * _MAX_HASH))
        seed = validated.seed if validated.seed is not None else 0
        return lf.with_row_index("_idx").filter(pl.col("_idx").hash(seed=seed) <= pl.lit(threshold, dtype=pl.UInt64)).drop("_idx")
