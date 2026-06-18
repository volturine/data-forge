from collections.abc import Callable

import polars as pl

from operations.type_casting import cast_value, get_polars_type
from runtime.domain.compute.base import OperationHandler, OperationParams
from runtime.domain.step_config_enums import FillNullStrategy


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


def get_fill_strategy(name: FillNullStrategy | str) -> Callable[[pl.Expr], pl.Expr] | None:
    strategy = FillNullStrategy.read(name)
    return _FILL_STRATEGIES.get(strategy) if strategy is not None else None


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
                literal = pl.lit(value, dtype=dtype) if dtype is not None else value
                return pl.col(col).fill_null(literal)

            if columns:
                return lf.with_columns([build_expr(col) for col in columns])
            return lf.with_columns([build_expr(col) for col in lf.collect_schema().names()])

        if strategy := get_fill_strategy(validated.strategy):
            if validated.strategy in (FillNullStrategy.MEAN, FillNullStrategy.MEDIAN):
                statistical_columns = _resolve_statistical_columns(
                    lf,
                    validated.strategy,
                    columns,
                )
                return lf.with_columns([strategy(pl.col(col)) for col in statistical_columns])
            if columns:
                return lf.with_columns([strategy(pl.col(col)) for col in columns])
            return lf.with_columns([strategy(pl.col(col)) for col in lf.collect_schema().names()])

        if validated.strategy.drops_rows:
            if columns:
                return lf.drop_nulls(subset=columns)
            return lf.drop_nulls()

        raise ValueError(f"Unsupported fill_null strategy: {validated.strategy}")
