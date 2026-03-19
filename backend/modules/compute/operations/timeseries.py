from collections.abc import Callable
from typing import Literal, cast

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class TimeseriesParams(OperationParams):
    column: str
    operation_type: str
    new_column: str
    component: str | None = None
    value: int | float | None = None
    unit: str | None = None
    direction: str | None = None
    column2: str | None = None


_VALID_COMPONENTS = frozenset({'year', 'month', 'day', 'hour', 'minute', 'second', 'quarter', 'week', 'dayofweek'})
_COMPONENT_ALIAS: dict[str, str] = {'dayofweek': 'weekday'}

_DURATION_BUILDERS: dict[str, Callable[[int], pl.Expr]] = {
    'seconds': lambda value: pl.duration(seconds=value),
    'minutes': lambda value: pl.duration(minutes=value),
    'hours': lambda value: pl.duration(hours=value),
    'days': lambda value: pl.duration(days=value),
    'weeks': lambda value: pl.duration(weeks=value),
}


def get_extractor(component: str) -> str:
    if component not in _VALID_COMPONENTS:
        raise ValueError(f'Unsupported time component: {component}')
    return _COMPONENT_ALIAS.get(component, component)


def get_duration(unit: str, value: int) -> pl.Expr:
    builder = _DURATION_BUILDERS.get(unit)
    if not builder:
        raise ValueError(f'Unsupported duration unit: {unit}')
    return builder(value)


class TimeseriesHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = TimeseriesParams.model_validate(params)

        if validated.operation_type == 'extract':
            method = get_extractor(validated.component or '')
            return lf.with_columns(getattr(pl.col(validated.column).dt, method)().alias(validated.new_column))

        if validated.operation_type == 'timestamp':
            valid_units = {'ns', 'us', 'ms'}
            unit = validated.unit if validated.unit in valid_units else 'us'
            unit_literal = cast(Literal['ns', 'us', 'ms'], unit)
            return lf.with_columns(pl.col(validated.column).dt.timestamp(unit_literal).alias(validated.new_column))

        if validated.operation_type in {'add', 'subtract', 'offset'}:
            if validated.value is None:
                raise ValueError('timeseries operation requires numeric value parameter')
            if not validated.unit:
                raise ValueError('timeseries operation requires unit parameter')

            subtracting = validated.operation_type == 'subtract' or validated.direction == 'subtract'

            if validated.unit == 'months':
                offset = f'-{validated.value}mo' if subtracting else f'{validated.value}mo'
                return lf.with_columns(pl.col(validated.column).dt.offset_by(offset).alias(validated.new_column))

            duration = get_duration(validated.unit, int(validated.value))
            expr = pl.col(validated.column) - duration if subtracting else pl.col(validated.column) + duration
            return lf.with_columns(expr.alias(validated.new_column))

        if validated.operation_type == 'diff':
            if not validated.column2:
                raise ValueError('timeseries operation requires column2 parameter')
            return lf.with_columns((pl.col(validated.column2) - pl.col(validated.column)).alias(validated.new_column))

        raise ValueError(f'Unsupported timeseries operation: {validated.operation_type}')
