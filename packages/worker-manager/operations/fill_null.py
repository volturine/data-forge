from collections.abc import Callable

import polars as pl
from contracts.compute.base import OperationHandler, OperationParams
from contracts.step_config_enums import FillNullStrategy

from operations.type_casting import cast_value, get_polars_type


class FillNullParams(OperationParams):
    strategy: FillNullStrategy
    columns: list[str] | None = None
    value: str | int | float | bool | None = None
    value_type: str | None = None


_FILL_STRATEGIES: dict[FillNullStrategy, Callable[[pl.Expr], pl.Expr]] = {}


def fill_strategy(strategy: FillNullStrategy) -> Callable[[Callable[[pl.Expr], pl.Expr]], Callable[[pl.Expr], pl.Expr]]:
    def register(func: Callable[[pl.Expr], pl.Expr]) -> Callable[[pl.Expr], pl.Expr]:
        _FILL_STRATEGIES[strategy] = func
        return func

    return register


@fill_strategy(FillNullStrategy.FORWARD)
def _forward_fill(col: pl.Expr) -> pl.Expr:
    return col.forward_fill()


@fill_strategy(FillNullStrategy.BACKWARD)
def _backward_fill(col: pl.Expr) -> pl.Expr:
    return col.backward_fill()


@fill_strategy(FillNullStrategy.MEAN)
def _mean_fill(col: pl.Expr) -> pl.Expr:
    return col.fill_null(col.mean())


@fill_strategy(FillNullStrategy.MEDIAN)
def _median_fill(col: pl.Expr) -> pl.Expr:
    return col.fill_null(col.median())


@fill_strategy(FillNullStrategy.ZERO)
def _zero_fill(col: pl.Expr) -> pl.Expr:
    return col.fill_null(0)


def get_fill_strategy(name: FillNullStrategy) -> Callable[[pl.Expr], pl.Expr] | None:
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

        if validated.strategy.uses_literal_value:
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

        if validated.strategy.drops_rows:
            if columns:
                return lf.drop_nulls(subset=columns)
            return lf.drop_nulls()

        raise ValueError(f"Unsupported fill_null strategy: {validated.strategy}")
