"""Unpivot (melt) operation."""

import polars as pl
from contracts.compute.base import OperationHandler, OperationParams


class UnpivotParams(OperationParams):
    index: list[str] | None = None
    id_vars: list[str] | None = None  # Alias for index
    on: list[str] | None = None
    value_vars: list[str] | None = None  # Alias for on
    variable_name: str = "variable"
    value_name: str = "value"


class UnpivotHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = UnpivotParams.model_validate(params)
        index = validated.index or validated.id_vars or []
        on = validated.on or validated.value_vars
        return lf.unpivot(
            index=index,
            on=on,
            variable_name=validated.variable_name,
            value_name=validated.value_name,
        )
