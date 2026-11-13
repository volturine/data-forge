from collections.abc import Callable

import polars as pl

from operations.enums import FillNullStrategy
from operations.type_casting import cast_value, get_polars_type
from runtime.domain.compute.base import OperationParams


class FillNullParams(OperationParams):
    strategy: FillNullStrategy
    columns: list[str] | None = None
    value: str | int | float | bool | None = None
    value_type: str | None = None


_FILL_STRATEGIES: dict[FillNullStrategy, Callable[[pl.Expr], pl.Expr]] = {
    FillNullStrategy.FORWARD: lambda col: col.forward_fill(),
    FillNullStrategy.BACKWARD: lambda col: col.backward_fill(),
    FillNullStrategy.MEAN: lambda col: col.fill_null(col.mean()),
    FillNullStrategy.MEDIAN: lambda col: col.fill_null(col.median()),
    FillNullStrategy.ZERO: lambda col: col.fill_null(0),
}


def _resolve_statistical_columns(
    lf: pl.LazyFrame,
    strategy: FillNullStrategy,
    columns: list[str] | None,
) -> list[str]:
    schema = lf.collect_schema()

    if columns:
        unsupported = [column for column in columns if not schema[column].is_numeric()]
        if unsupported:
            cols = ", ".join(unsupported)
            raise ValueError(f"fill_null {strategy.value} requires numeric columns. Unsupported columns: {cols}")
        return columns

    numeric_columns = [name for name, dtype in schema.items() if dtype.is_numeric()]
    if not numeric_columns:
        raise ValueError(f"fill_null {strategy.value} requires at least one numeric column")
    return numeric_columns


def _literal_compatible_columns(lf: pl.LazyFrame, literal: pl.Expr) -> list[str]:
    """Columns a literal can fill without changing their dtype.

    Without an explicit column list, filling every column with e.g. a string
    literal would silently turn numeric columns into strings.
    """
    literal_dtype = pl.select(literal).to_series().dtype
    schema = lf.collect_schema()
    if literal_dtype == pl.Null:
        return schema.names()
    if literal_dtype.is_numeric():
        return [name for name, dtype in schema.items() if dtype.is_numeric()]
    if literal_dtype.is_temporal():
        return [name for name, dtype in schema.items() if dtype.is_temporal()]
    return [name for name, dtype in schema.items() if dtype == literal_dtype]


def fill_null(lf: pl.LazyFrame, params: FillNullParams, **_) -> pl.LazyFrame:
    strategy = params.strategy
    columns = params.columns

    if strategy == FillNullStrategy.DROP_ROWS:
        return lf.drop_nulls(subset=columns) if columns else lf.drop_nulls()

    if strategy in (FillNullStrategy.MEAN, FillNullStrategy.MEDIAN):
        fill = _FILL_STRATEGIES[strategy]
        return lf.with_columns([fill(pl.col(col)) for col in _resolve_statistical_columns(lf, strategy, columns)])

    if strategy == FillNullStrategy.LITERAL:
        value = cast_value(params.value, params.value_type)
        dtype = get_polars_type(params.value_type)
        literal = pl.lit(value, dtype=dtype) if dtype is not None else pl.lit(value)
        target_columns = columns or _literal_compatible_columns(lf, literal)
        return lf.with_columns([pl.col(col).fill_null(literal) for col in target_columns])

    target_columns = columns or lf.collect_schema().names()

    column_fill = _FILL_STRATEGIES[strategy]
    return lf.with_columns([column_fill(pl.col(col)) for col in target_columns])
