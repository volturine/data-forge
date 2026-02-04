from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, model_validator

from modules.compute.core.base import OperationHandler, OperationParams
from core.config import settings

ValueType = Literal['string', 'number', 'date', 'datetime', 'column', 'boolean']


class FilterCondition(BaseModel):
    model_config = ConfigDict(extra='forbid')

    column: str
    operator: str = '=='
    value: Any | None = None
    value_type: ValueType = 'string'
    compare_column: str | None = None

    @model_validator(mode='after')
    def validate_condition(self) -> 'FilterCondition':
        if self.operator in ('is_null', 'is_not_null'):
            return self
        if self.value_type == 'column' and not self.compare_column:
            raise ValueError('compare_column required when value_type is column')
        if self.value_type != 'column' and self.value is None:
            raise ValueError('value required for non-column comparisons')
        return self


class FilterParams(OperationParams):
    conditions: list[FilterCondition]
    logic: str = 'AND'


def coerce_value(value: Any, value_type: ValueType) -> Any:
    """Coerce value to the appropriate Python/Polars type."""
    if value is None:
        return None

    if value_type == 'number':
        if isinstance(value, (int, float)):
            return value
        s = str(value)
        return float(s) if '.' in s else int(s)

    if value_type == 'boolean':
        if isinstance(value, bool):
            return value
        return str(value).lower() in ('true', '1', 'yes')

    if value_type == 'date':
        if isinstance(value, datetime):
            return value.date()
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).date()

    if value_type == 'datetime':
        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if not dt.tzinfo:
            if settings.normalize_tz:
                return dt.replace(tzinfo=ZoneInfo(settings.timezone))
            return dt
        if settings.normalize_tz:
            return dt.astimezone(ZoneInfo(settings.timezone))
        return dt.astimezone(ZoneInfo(settings.timezone)).replace(tzinfo=None)

    return str(value)


class FilterHandler(OperationHandler):
    def __init__(self) -> None:
        self._last_schema: dict[str, pl.DataType] | None = None

    OPERATORS: dict[str, Callable[[pl.Expr, Any], pl.Expr]] = {
        '=': lambda col, val: col == val,
        '==': lambda col, val: col == val,
        '!=': lambda col, val: col != val,
        '>': lambda col, val: col > val,
        '<': lambda col, val: col < val,
        '>=': lambda col, val: col >= val,
        '<=': lambda col, val: col <= val,
        'contains': lambda col, val: col.str.contains(val, literal=True),
        'not_contains': lambda col, val: ~col.str.contains(val, literal=True),
        'starts_with': lambda col, val: col.str.starts_with(val),
        'ends_with': lambda col, val: col.str.ends_with(val),
        'regex': lambda col, val: col.str.contains(val, literal=False),
        'is_null': lambda col, _: col.is_null(),
        'is_not_null': lambda col, _: col.is_not_null(),
        'in': lambda col, val: col.is_in(val),
        'not_in': lambda col, val: ~col.is_in(val),
    }

    COLUMN_OPERATORS: dict[str, Callable[[pl.Expr, pl.Expr], pl.Expr]] = {
        '=': lambda left, right: left == right,
        '==': lambda left, right: left == right,
        '!=': lambda left, right: left != right,
        '>': lambda left, right: left > right,
        '<': lambda left, right: left < right,
        '>=': lambda left, right: left >= right,
        '<=': lambda left, right: left <= right,
    }

    @property
    def name(self) -> str:
        return 'filter'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = FilterParams.model_validate(params)
        self._last_schema = lf.collect_schema()

        exprs: list[pl.Expr] = []
        for cond in validated.conditions:
            exprs.append(self._build_expr(cond))

        if len(exprs) == 1:
            return lf.filter(exprs[0])

        combined = exprs[0]
        if validated.logic == 'AND':
            for expr in exprs[1:]:
                combined = combined & expr
            return lf.filter(combined)

        if validated.logic == 'OR':
            for expr in exprs[1:]:
                combined = combined | expr
            return lf.filter(combined)

        raise ValueError(f'Unsupported logic operator: {validated.logic}')

    def _build_expr(self, cond: FilterCondition) -> pl.Expr:
        """Build a filter expression from a condition."""
        left = pl.col(cond.column)
        schema = self._schema
        if schema and cond.column in schema:
            left = self._normalize_datetime_col(left, schema[cond.column])

        if cond.operator in ('is_null', 'is_not_null'):
            op = self.OPERATORS.get(cond.operator)
            if not op:
                raise ValueError(f'Unsupported filter operator: {cond.operator}')
            return op(left, None)

        if cond.value_type == 'column':
            op = self.COLUMN_OPERATORS.get(cond.operator)
            if not op:
                raise ValueError(f'Operator {cond.operator} not supported for column comparison')
            if not cond.compare_column:
                raise ValueError('compare_column required when value_type is column')
            right = pl.col(cond.compare_column)
            if schema and cond.compare_column in schema:
                right = self._normalize_datetime_col(right, schema[cond.compare_column])
            return op(left, right)

        coerced = coerce_value(cond.value, cond.value_type)
        op = self.OPERATORS.get(cond.operator)
        if not op:
            raise ValueError(f'Unsupported filter operator: {cond.operator}')
        return op(left, coerced)

    def _get_operator(self, name: str) -> Callable[[pl.Expr, Any], pl.Expr]:
        op = self.OPERATORS.get(name)
        if not op:
            raise ValueError(f'Unsupported filter operator: {name}')
        return op

    @property
    def _schema(self) -> dict[str, pl.DataType] | None:
        try:
            return self._last_schema
        except AttributeError:
            return None

    def _normalize_datetime_col(self, expr: pl.Expr, dtype: pl.DataType) -> pl.Expr:
        if not isinstance(dtype, pl.Datetime):
            return expr
        tz = dtype.time_zone
        if settings.normalize_tz:
            if tz is None:
                return expr.dt.replace_time_zone(settings.timezone)
            return expr.dt.convert_time_zone(settings.timezone)
        if tz is None:
            return expr
        return expr.dt.replace_time_zone(None)


def get_operator(name: str) -> Callable[[pl.Expr, Any], pl.Expr]:
    return FilterHandler()._get_operator(name)
