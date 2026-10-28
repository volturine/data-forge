import polars as pl
from pydantic import Field

from operations.enums import PivotAggregateFunction
from runtime.domain.compute.base import OperationParams

_MAX_AUTO_PIVOT_VALUES = 200


class PivotParams(OperationParams):
    index: list[str] = Field(min_length=1)
    columns: str = Field(min_length=1)
    value_columns: list[str] | None = None
    aggregate_function: PivotAggregateFunction = PivotAggregateFunction.FIRST


def _auto_on_columns(lf: pl.LazyFrame, pivot_column: str) -> list[str]:
    values = lf.select(pl.col(pivot_column)).unique().limit(_MAX_AUTO_PIVOT_VALUES + 1).collect().to_series().sort().to_list()
    if len(values) > _MAX_AUTO_PIVOT_VALUES:
        raise ValueError(f"Pivot column {pivot_column!r} has more than {_MAX_AUTO_PIVOT_VALUES} distinct values")
    return values


def pivot(lf: pl.LazyFrame, params: PivotParams, **_) -> pl.LazyFrame:
    return lf.pivot(
        on=params.columns,
        on_columns=_auto_on_columns(lf, params.columns),
        index=params.index,
        values=params.value_columns or None,
        aggregate_function=params.aggregate_function.polars_aggregate_function,
    )
