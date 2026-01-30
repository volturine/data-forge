"""Top-K rows operation."""

import polars as pl

from modules.compute.operations.base import OperationHandler, OperationParams


class TopKParams(OperationParams):
    column: str
    k: int = 10
    descending: bool = False


class TopKHandler(OperationHandler):
    @property
    def name(self) -> str:
        return 'topk'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = TopKParams.model_validate(params)
        return lf.sort(validated.column, descending=validated.descending).head(validated.k)
