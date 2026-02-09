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


class TimeseriesHandler(OperationHandler):
    DT_EXTRACTORS: dict[str, str] = {
        'year': 'year',
        'month': 'month',
        'day': 'day',
        'hour': 'hour',
        'minute': 'minute',
        'second': 'second',
        'quarter': 'quarter',
        'week': 'week',
        'dayofweek': 'weekday',
    }

    DURATION_BUILDERS: dict[str, Callable[[int], pl.Expr]] = {
        'seconds': lambda value: pl.duration(seconds=value),
        'minutes': lambda value: pl.duration(minutes=value),
        'hours': lambda value: pl.duration(hours=value),
        'days': lambda value: pl.duration(days=value),
        'weeks': lambda value: pl.duration(weeks=value),
    }

    @property
    def name(self) -> str:
        return 'timeseries'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = TimeseriesParams.model_validate(params)

        if validated.operation_type == 'extract':
            method = self._get_extractor(validated.component or '')
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

            if validated.unit == 'months':
                subtracting = validated.operation_type == 'subtract' or validated.direction == 'subtract'
                offset = f'-{validated.value}mo' if subtracting else f'{validated.value}mo'
                return lf.with_columns(pl.col(validated.column).dt.offset_by(offset).alias(validated.new_column))

            duration = self._get_duration(validated.unit, int(validated.value))
            subtracting = validated.operation_type == 'subtract' or validated.direction == 'subtract'
            expr = pl.col(validated.column) - duration if subtracting else pl.col(validated.column) + duration
            return lf.with_columns(expr.alias(validated.new_column))

        if validated.operation_type == 'diff':
            if not validated.column2:
                raise ValueError('timeseries operation requires column2 parameter')
            return lf.with_columns((pl.col(validated.column2) - pl.col(validated.column)).alias(validated.new_column))

        raise ValueError(f'Unsupported timeseries operation: {validated.operation_type}')

    def _get_extractor(self, component: str) -> str:
        method = self.DT_EXTRACTORS.get(component)
        if not method:
            raise ValueError(f'Unsupported time component: {component}')
        return method

    def _get_duration(self, unit: str, value: int) -> pl.Expr:
        builder = self.DURATION_BUILDERS.get(unit)
        if not builder:
            raise ValueError(f'Unsupported duration unit: {unit}')
        return builder(value)


def get_extractor(component: str) -> str:
    return TimeseriesHandler()._get_extractor(component)


def get_duration(unit: str, value: int) -> pl.Expr:
    return TimeseriesHandler()._get_duration(unit, value)
