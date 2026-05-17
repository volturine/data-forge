"""Sample rows operation."""

import polars as pl
from contracts.compute.base import OperationHandler, OperationParams


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
        mod = int(1 / validated.fraction)
        if mod <= 0 or mod > 2**31 - 1:
            raise ValueError("Sample fraction is too small (minimum ~4.7e-10)")
        seed = validated.seed if validated.seed is not None else 0
        return lf.with_row_index("_idx").filter(pl.col("_idx").hash(seed=seed) % mod == 0).drop("_idx")
