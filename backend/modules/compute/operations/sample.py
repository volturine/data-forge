"""Sample rows operation."""

import polars as pl

from modules.compute.operations.base import OperationHandler, OperationParams


class SampleParams(OperationParams):
    fraction: float
    seed: int | None = None


class SampleHandler(OperationHandler):
    """Sample rows using a deterministic hash-based approach for lazy evaluation."""

    @property
    def name(self) -> str:
        return 'sample'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = SampleParams.model_validate(params)
        if validated.fraction <= 0 or validated.fraction > 1:
            raise ValueError('Sample fraction must be between 0 and 1')
        mod = int(1 / validated.fraction)
        if validated.seed is not None:
            return lf.with_row_index('_idx').filter(pl.col('_idx').hash(seed=validated.seed) % mod == 0).drop('_idx')
        return lf.with_row_index('_idx').filter(pl.col('_idx').hash() % mod == 0).drop('_idx')
