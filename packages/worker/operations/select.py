"""Select columns operation."""

import polars as pl
from pydantic import Field

from operations.enums import CastMapType
from operations.type_casting import require_polars_type
from runtime.domain.compute.base import OperationParams


class SelectParams(OperationParams):
    columns: list[str]
    cast_map: dict[str, CastMapType] = Field(default_factory=dict)


def select(lf: pl.LazyFrame, params: SelectParams, **_) -> pl.LazyFrame:
    missing = sorted(set(params.cast_map) - set(params.columns))
    if missing:
        cols = ", ".join(missing)
        raise ValueError(f"cast_map keys must reference selected columns. Unknown keys: {cols}")
    selected = lf.select(params.columns)
    if not params.cast_map:
        return selected
    exprs = [pl.col(col).cast(require_polars_type(dtype.value)).alias(col) for col, dtype in params.cast_map.items()]
    return selected.with_columns(exprs)
