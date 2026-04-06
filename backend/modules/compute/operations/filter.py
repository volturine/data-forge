from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.config import settings
from modules.compute.core.base import OperationHandler, OperationParams
from modules.compute.operations._validation import validate_regex_pattern


def _parse_datetime_string(s: str) -> datetime:
    """Parse a datetime string, supporting ISO 8601 and common fallback formats."""
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    for fmt in ('%Y-%m-%d %H:%M:%S', '%m/%d/%Y %H:%M:%S', '%m/%d/%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(
        f"Cannot parse datetime string '{s}'. Accepted formats: ISO 8601 (YYYY-MM-DDTHH:MM:SS), YYYY-MM-DD HH:MM:SS, MM/DD/YYYY",
    )


class FilterValueType(StrEnum):
    STRING = 'string'
    NUMBER = 'number'
    DATE = 'date'
    DATETIME = 'datetime'
    COLUMN = 'column'
    BOOLEAN = 'boolean'


NULL_CHECK_OPERATORS = frozenset({'is_null', 'is_not_null'})


def _normalize_text_field(value: Any) -> str:
    if not isinstance(value, str):
        return ''
    return value.strip()


def normalize_filter_conditions(conditions: list[Any] | None) -> list[Any]:
    if not conditions:
        return []

    normalized: list[Any] = []
    for condition in conditions:
        if not isinstance(condition, dict):
            normalized.append(condition)
            continue

        column = _normalize_text_field(condition.get('column'))
        if not column:
            continue

        operator = condition.get('operator') or '='
        value_type = condition.get('value_type', FilterValueType.STRING.value)
        item: dict[str, Any] = {
            'column': column,
            'operator': operator,
            'value': condition.get('value'),
            'value_type': value_type,
        }

        if operator in NULL_CHECK_OPERATORS:
            normalized.append(item)
            continue

        compare_column = _normalize_text_field(condition.get('compare_column'))
        if value_type == FilterValueType.COLUMN and not compare_column:
            continue
        if compare_column:
            item['compare_column'] = compare_column

        normalized.append(item)

    return normalized


class FilterCondition(BaseModel):
    model_config = ConfigDict(extra='forbid')

    column: str
    operator: str = '=='
    value: Any | list[Any] | None = None
    value_type: FilterValueType = FilterValueType.STRING
    compare_column: str | None = None

    @model_validator(mode='after')
    def validate_condition(self) -> 'FilterCondition':
        if self.operator in NULL_CHECK_OPERATORS:
            return self
        if self.value_type == FilterValueType.COLUMN and not self.compare_column:
            raise ValueError('compare_column required when value_type is column')
        if self.value_type != FilterValueType.COLUMN and self.value is None:
            raise ValueError('value required for non-column comparisons')
        return self


class FilterParams(OperationParams):
    conditions: list[FilterCondition] = Field(default_factory=list)
    logic: str = 'AND'

    @model_validator(mode='before')
    @classmethod
    def normalize_conditions(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        return {**data, 'conditions': normalize_filter_conditions(data.get('conditions'))}


def coerce_value(value: Any, value_type: FilterValueType) -> Any:
    """Coerce value to the appropriate Python/Polars type."""
    if value is None:
        return None

    if isinstance(value, list):
        return [coerce_value(item, value_type) for item in value]

    if value_type == FilterValueType.NUMBER:
        if isinstance(value, (int, float)):
            return value
        s = str(value)
        parsed = float(s)
        if parsed.is_integer() and '.' not in s and 'e' not in s.lower():
            return int(parsed)
        return parsed

    if value_type == FilterValueType.BOOLEAN:
        if isinstance(value, bool):
            return value
        return str(value).lower() in ('true', '1', 'yes')

    if value_type == FilterValueType.DATE:
        if isinstance(value, datetime):
            return value.date()
        return _parse_datetime_string(str(value)).date()

    if value_type == FilterValueType.DATETIME:
        dt = value if isinstance(value, datetime) else _parse_datetime_string(str(value))
        if not dt.tzinfo and not settings.normalize_tz:
            return dt
        tz = ZoneInfo(settings.timezone)
        dt = dt.replace(tzinfo=tz) if not dt.tzinfo else dt.astimezone(tz)
        return dt if settings.normalize_tz else dt.replace(tzinfo=None)

    return str(value)


class FilterHandler(OperationHandler):
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
        if not validated.conditions:
            return lf

        schema = lf.collect_schema()

        exprs = [self._build_expr(cond, schema) for cond in validated.conditions]

        if validated.logic == 'AND':
            return lf.filter(pl.all_horizontal(exprs))
        if validated.logic == 'OR':
            return lf.filter(pl.any_horizontal(exprs))
        raise ValueError(f'Unsupported logic operator: {validated.logic}')

    def _build_expr(self, cond: FilterCondition, schema: pl.Schema) -> pl.Expr:
        left = pl.col(cond.column)
        col_dtype = schema.get(cond.column)
        if col_dtype:
            left = _normalize_datetime_col(left, col_dtype)

        if cond.operator in ('is_null', 'is_not_null'):
            return get_operator(cond.operator)(left, None)

        if cond.value_type == FilterValueType.COLUMN:
            op = self.COLUMN_OPERATORS.get(cond.operator)
            if not op:
                raise ValueError(f'Operator {cond.operator} not supported for column comparison')
            if not cond.compare_column:
                raise ValueError('compare_column required when value_type is column')
            right = pl.col(cond.compare_column)
            if cond.compare_column in schema:
                right = _normalize_datetime_col(right, schema[cond.compare_column])
            return op(left, right)

        is_date_only = _is_date_only_value(cond.value)
        is_datetime_col = isinstance(col_dtype, pl.Datetime)

        if is_date_only and is_datetime_col and cond.value_type == 'datetime':
            return get_operator(cond.operator)(pl.col(cond.column).dt.date(), coerce_value(cond.value, FilterValueType.DATE))

        coerced = coerce_value(cond.value, cond.value_type)
        op = get_operator(cond.operator)
        if cond.operator == 'regex' and coerced == '':
            return pl.lit(False)
        if cond.operator == 'regex' and isinstance(coerced, str):
            validate_regex_pattern(coerced)
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


def _is_date_only_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return len(value) == 10 and '-' in value and 'T' not in value


def _normalize_datetime_col(expr: pl.Expr, dtype: pl.DataType) -> pl.Expr:
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
