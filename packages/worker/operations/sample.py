"""Sample rows operation."""

import math

import polars as pl
from pydantic import Field

from runtime.domain.compute.base import OperationParams

_MAX_HASH = (1 << 64) - 1


class SampleParams(OperationParams):
    fraction: float = Field(gt=0, le=1)
    seed: int | None = None


def sample(lf: pl.LazyFrame, params: SampleParams, **_) -> pl.LazyFrame:
    """Sample rows using a deterministic hash-based approach for lazy evaluation."""
    if params.fraction == 1:
        return lf
    threshold = max(1, math.ceil(params.fraction * _MAX_HASH))
    seed = params.seed if params.seed is not None else 0
    return lf.with_row_index("_idx").filter(pl.col("_idx").hash(seed=seed) <= pl.lit(threshold, dtype=pl.UInt64)).drop("_idx")
