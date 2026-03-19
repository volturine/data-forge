from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

import polars as pl
from pydantic import BaseModel, ConfigDict, model_validator

from core.config import settings
from modules.compute.core.base import OperationHandler, OperationParams

ValueType = Literal['string', 'number', 'date', 'datetime', 'column', 'boolean']


class FilterCondition(BaseModel):
    model_config = ConfigDict(extra='forbid')

    column: str
    operator: str = '=='
    value: Any | list[Any] | None = None
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

    if isinstance(value, list):
        return [coerce_value(item, value_type) for item in value]

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
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if not dt.tzinfo and not settings.normalize_tz:
            return dt
        tz = ZoneInfo(settings.timezone)
        dt = dt.replace(tzinfo=tz) if not dt.tzinfo else dt.astimezone(tz)
        return dt if settings.normalize_tz else dt.replace(tzinfo=None)

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

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = FilterParams.model_validate(params)
        self._last_schema = lf.collect_schema()

        exprs = [self._build_expr(cond) for cond in validated.conditions]

        if validated.logic == 'AND':
            return lf.filter(pl.all_horizontal(exprs))
        if validated.logic == 'OR':
            return lf.filter(pl.any_horizontal(exprs))
        raise ValueError(f'Unsupported logic operator: {validated.logic}')

    def _build_expr(self, cond: FilterCondition) -> pl.Expr:
        left = pl.col(cond.column)
        schema = self._schema
        col_dtype = schema.get(cond.column) if schema else None
        if col_dtype:
            left = self._normalize_datetime_col(left, col_dtype)

        if cond.operator in ('is_null', 'is_not_null'):
            return get_operator(cond.operator)(left, None)

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

        is_date_only = self._is_date_only_value(cond.value)
        is_datetime_col = isinstance(col_dtype, pl.Datetime)

        if is_date_only and is_datetime_col and cond.value_type == 'datetime':
            return get_operator(cond.operator)(pl.col(cond.column).dt.date(), coerce_value(cond.value, 'date'))

        coerced = coerce_value(cond.value, cond.value_type)
        op = get_operator(cond.operator)
        if cond.operator == 'regex' and coerced == '':
            return pl.lit(False)
        if isinstance(coerced, list):
            if not coerced:
                if cond.operator in ('not_contains', 'not_in'):
                    return pl.lit(True)
                return pl.lit(False)
            if cond.operator in ('in', 'not_in'):
                return op(left, coerced)
            if cond.operator == 'not_contains':
                combined = op(left, coerced[0])
                for item in coerced[1:]:
                    combined = combined & op(left, item)
                return combined
            combined = op(left, coerced[0])
            for item in coerced[1:]:
                combined = combined | op(left, item)
            return combined
        return op(left, coerced)

    def _is_date_only_value(self, value: Any) -> bool:
        """Check if value is a date-only string (YYYY-MM-DD without time)."""
        if not isinstance(value, str):
            return False
        return len(value) == 10 and '-' in value and 'T' not in value

    @property
    def _schema(self) -> dict[str, pl.DataType] | None:
        return self._last_schema

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
    op = FilterHandler.OPERATORS.get(name)
    if not op:
        raise ValueError(f'Unsupported filter operator: {name}')
    return op
