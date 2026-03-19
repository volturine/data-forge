from collections.abc import Callable
from typing import Any

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class FillNullParams(OperationParams):
    strategy: str
    columns: list[str] | None = None
    value: str | int | float | bool | None = None
    value_type: str | None = None


_FILL_STRATEGIES: dict[str, Callable[[pl.Expr], pl.Expr]] = {
    'forward': lambda col: col.forward_fill(),
    'backward': lambda col: col.backward_fill(),
    'mean': lambda col: col.fill_null(col.mean()),
    'median': lambda col: col.fill_null(col.median()),
    'zero': lambda col: col.fill_null(0),
}

_TYPE_CASTERS: dict[str, tuple] = {
    'Int64': (int, pl.Int64()),
    'Float64': (float, pl.Float64()),
    'Boolean': (bool, pl.Boolean()),
    'String': (str, pl.Utf8()),
    'Utf8': (str, pl.Utf8()),
    'Date': (None, pl.Date()),
    'Datetime': (None, pl.Datetime()),
}


def get_fill_strategy(name: str) -> Callable[[pl.Expr], pl.Expr] | None:
    return _FILL_STRATEGIES.get(name)


def cast_value(value: Any, type_name: str | None) -> Any:
    if not type_name or value is None:
        return value
    spec = _TYPE_CASTERS.get(type_name)
    if not spec:
        return value
    caster, _ = spec
    return caster(value) if caster else value


def get_polars_type(type_name: str | None) -> pl.DataType | None:
    if not type_name:
        return None
    spec = _TYPE_CASTERS.get(type_name)
    return spec[1] if spec else None


class FillNullHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = FillNullParams.model_validate(params)
        columns = validated.columns

        if validated.strategy == 'literal':
            value = cast_value(validated.value, validated.value_type)
            dtype = get_polars_type(validated.value_type)

            def build_expr(col: str) -> pl.Expr:
                expr = pl.col(col)
                if dtype is not None:
                    expr = expr.cast(dtype)
                return expr.fill_null(value)

            if columns:
                return lf.with_columns([build_expr(col) for col in columns])
            return lf.with_columns([build_expr(col) for col in lf.collect_schema().names()])

        if strategy := get_fill_strategy(validated.strategy):
            if columns:
                return lf.with_columns([strategy(pl.col(col)) for col in columns])
            return lf.with_columns([strategy(pl.col(col)) for col in lf.collect_schema().names()])

        if validated.strategy == 'drop_rows':
            if columns:
                return lf.drop_nulls(subset=columns)
            return lf.drop_nulls()

        raise ValueError(f'Unsupported fill_null strategy: {validated.strategy}')
