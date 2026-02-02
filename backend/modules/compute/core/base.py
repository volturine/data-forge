from typing import Protocol, runtime_checkable

import polars as pl
from pydantic import BaseModel, ConfigDict


class OperationParams(BaseModel):
    model_config = ConfigDict(extra='forbid')


@runtime_checkable
class OperationHandler(Protocol):
    @property
    def name(self) -> str: ...

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame: ...
