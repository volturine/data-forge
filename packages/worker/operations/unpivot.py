"""Unpivot (melt) operation."""

import polars as pl

from runtime.domain.compute.base import OperationParams


class UnpivotParams(OperationParams):
    id_vars: list[str] | None = None
    value_vars: list[str] | None = None
    variable_name: str = "variable"
    value_name: str = "value"


def unpivot(lf: pl.LazyFrame, params: UnpivotParams, **_) -> pl.LazyFrame:
    return lf.unpivot(
        index=params.id_vars or [],
        on=params.value_vars,
        variable_name=params.variable_name,
        value_name=params.value_name,
    )
