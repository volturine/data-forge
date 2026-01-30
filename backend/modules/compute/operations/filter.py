from collections.abc import Callable
from typing import Any

import polars as pl
from pydantic import BaseModel, ConfigDict

from modules.compute.operations.base import OperationHandler, OperationParams


class FilterCondition(BaseModel):
    model_config = ConfigDict(extra='forbid')

    column: str
    operator: str = '=='
    value: Any | None = None


class FilterParams(OperationParams):
    conditions: list[FilterCondition]
    logic: str = 'AND'


class FilterHandler(OperationHandler):
    OPERATORS: dict[str, Callable[[pl.Expr, Any], pl.Expr]] = {
        '=': lambda col, value: col == value,
        '==': lambda col, value: col == value,
        '!=': lambda col, value: col != value,
        '>': lambda col, value: col > value,
        '<': lambda col, value: col < value,
        '>=': lambda col, value: col >= value,
        '<=': lambda col, value: col <= value,
        'contains': lambda col, value: col.str.contains(value),
        'starts_with': lambda col, value: col.str.starts_with(value),
        'ends_with': lambda col, value: col.str.ends_with(value),
        'is_null': lambda col, _: col.is_null(),
        'is_not_null': lambda col, _: col.is_not_null(),
        'in': lambda col, value: col.is_in(value),
        'not_in': lambda col, value: ~col.is_in(value),
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

        exprs: list[pl.Expr] = []
        for cond in validated.conditions:
            op = self._get_operator(cond.operator)
            exprs.append(op(pl.col(cond.column), cond.value))

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

    def _get_operator(self, name: str) -> Callable[[pl.Expr, Any], pl.Expr]:
        op = self.OPERATORS.get(name)
        if not op:
            raise ValueError(f'Unsupported filter operator: {name}')
        return op


def get_operator(name: str) -> Callable[[pl.Expr, Any], pl.Expr]:
    return FilterHandler()._get_operator(name)
