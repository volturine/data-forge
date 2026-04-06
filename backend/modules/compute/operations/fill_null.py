from collections.abc import Callable

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams
from modules.compute.operations.type_casting import cast_value, get_polars_type


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


def get_fill_strategy(name: str) -> Callable[[pl.Expr], pl.Expr] | None:
    return _FILL_STRATEGIES.get(name)


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
