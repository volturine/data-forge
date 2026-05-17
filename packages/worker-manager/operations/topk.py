"""Top-K rows operation."""

import polars as pl
from contracts.compute.base import OperationHandler, OperationParams


class TopKParams(OperationParams):
    column: str
    k: int = 10
    descending: bool = False


class TopKHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = TopKParams.model_validate(params)
        return lf.sort(validated.column, descending=validated.descending).head(validated.k)
