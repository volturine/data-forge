"""Expression-based column operations."""

from typing import Any

import polars as pl
from pydantic import BaseModel, ConfigDict

from modules.compute.operations.base import OperationHandler, OperationParams


class WithColumnsExpr(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str
    type: str
    value: Any | None = None
    column: str | None = None


class WithColumnsParams(OperationParams):
    expressions: list[WithColumnsExpr]


class WithColumnsHandler(OperationHandler):
    """Add or modify columns using expressions."""

    @property
    def name(self) -> str:
        return 'with_columns'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = WithColumnsParams.model_validate(params)
        exprs: list[pl.Expr] = []
        for expr in validated.expressions:
            if expr.type == 'literal':
                exprs.append(pl.lit(expr.value).alias(expr.name))
            elif expr.type == 'column' and expr.column:
                exprs.append(pl.col(expr.column).alias(expr.name))
        return lf.with_columns(exprs)
