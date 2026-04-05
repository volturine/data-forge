"""With columns operation for adding/modifying columns."""

import builtins
from collections.abc import Callable
from enum import StrEnum
from functools import partial
from typing import Any, cast

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from modules.compute.core.base import OperationHandler, OperationParams
from modules.compute.operations._validation import validate_no_reflection_escape

# Builtins allowed inside UDF code.
# Keep this as a narrow allowlist so aliased introspection helpers cannot escape the sandbox.
_ALLOWED_BUILTINS = frozenset(
    {
        'abs',
        'all',
        'any',
        'ArithmeticError',
        'bool',
        'complex',
        'dict',
        'divmod',
        'enumerate',
        'Exception',
        'filter',
        'float',
        'frozenset',
        'hash',
        'int',
        'isinstance',
        'issubclass',
        'len',
        'list',
        'map',
        'max',
        'min',
        'pow',
        'range',
        'repr',
        'reversed',
        'round',
        'set',
        'slice',
        'sorted',
        'str',
        'sum',
        'tuple',
        'TypeError',
        'ValueError',
        'zip',
    },
)
_SAFE_BUILTINS: dict[str, Any] = {name: getattr(builtins, name) for name in _ALLOWED_BUILTINS}


class WithColumnsExprType(StrEnum):
    LITERAL = 'literal'
    COLUMN = 'column'
    UDF = 'udf'


class WithColumnsExpr(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str
    type: WithColumnsExprType
    value: Any | None = None
    column: str | None = None
    args: list[str] | None = None
    code: str | None = None
    udf_id: str | None = None


class WithColumnsParams(OperationParams):
    expressions: list[WithColumnsExpr] = Field(default_factory=list)


class WithColumnsHandler(OperationHandler):
    """Add or modify columns using expressions."""

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = WithColumnsParams.model_validate(params)
        exprs: list[pl.Expr] = []
        for expr in validated.expressions:
            if expr.type == WithColumnsExprType.LITERAL:
                exprs.append(pl.lit(expr.value).alias(expr.name))
            elif expr.type == WithColumnsExprType.COLUMN and expr.column:
                exprs.append(pl.col(expr.column).alias(expr.name))
            elif expr.type == WithColumnsExprType.UDF and expr.code:
                validate_no_reflection_escape(expr.code, label='UDF code')
                scope: dict[str, Any] = {'pl': pl, '__builtins__': _SAFE_BUILTINS}
                local_scope: dict[str, Any] = {}
                exec(expr.code, scope, local_scope)
                udf = local_scope.get('udf') or scope.get('udf')
                if not callable(udf):
                    raise ValueError('UDF must define a callable named udf')
                fn = cast(Callable[..., Any], udf)
                args = expr.args or []

                def apply_row(row: dict[str, Any], *, fn: Callable[..., Any], cols: list[str]) -> Any:
                    return fn(*[row[col] for col in cols])

                def apply_null(_: Any, *, fn: Callable[..., Any]) -> Any:
                    return fn()

                if args:
                    struct = pl.struct(args)
                    exprs.append(struct.map_elements(partial(apply_row, fn=fn, cols=args)).alias(expr.name))
                else:
                    exprs.append(pl.int_range(pl.len()).map_elements(partial(apply_null, fn=fn)).alias(expr.name))
        return lf.with_columns(exprs)
