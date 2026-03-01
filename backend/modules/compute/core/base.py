from typing import Protocol

import polars as pl
from pydantic import BaseModel, ConfigDict


class OperationParams(BaseModel):
    model_config = ConfigDict(extra='forbid')


class OperationHandler(Protocol):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame: ...
