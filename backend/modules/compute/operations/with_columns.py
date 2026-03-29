"""With columns operation for adding/modifying columns."""

import builtins
from collections.abc import Callable
from functools import partial
from typing import Any, cast

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from modules.compute.core.base import OperationHandler, OperationParams

# Builtins allowed inside UDF code — system-access and reflection functions are excluded.
# Reflection functions (getattr/setattr/delattr/vars/dir) are blocked to prevent
# attribute-chain escapes even when __builtins__ is otherwise restricted.
_DANGEROUS_BUILTINS = frozenset(
    {
        'open',
        'exec',
        'eval',
        'compile',
        '__import__',
        'input',
        'breakpoint',
        'getattr',
        'setattr',
        'delattr',
        'vars',
        'dir',
    }
)
_SAFE_BUILTINS: dict[str, Any] = {name: getattr(builtins, name) for name in dir(builtins) if name not in _DANGEROUS_BUILTINS}


class WithColumnsExpr(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str
    type: str
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
            if expr.type == 'literal':
                exprs.append(pl.lit(expr.value).alias(expr.name))
            elif expr.type == 'column' and expr.column:
                exprs.append(pl.col(expr.column).alias(expr.name))
            elif expr.type == 'udf' and expr.code:
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
                    exprs.append(pl.lit(0).map_elements(partial(apply_null, fn=fn)).alias(expr.name))
        return lf.with_columns(exprs)
