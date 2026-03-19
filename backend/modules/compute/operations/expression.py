"""Expression-based column operations."""

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class ExpressionParams(OperationParams):
    """Parameters for expression-based column creation."""

    expression: str
    column_name: str


def parse_expression(expr_str: str) -> pl.Expr:
    """Parse a Polars expression string.

    Provides full access to the pl.* namespace.
    Usage: pl.col("column").cast(pl.Float64)
    """
    if not expr_str or not expr_str.strip():
        raise ValueError('Expression cannot be empty')

    # Basic security: block dangerous patterns
    dangerous = [
        'import ',
        '__import__',
        'exec(',
        'eval(',
        'open(',
        'compile(',
        '__builtins__',
        '__class__',
        '__subclasses__',
        'subprocess',
        'os.system',
        'os.popen',
    ]
    if found := next((p for p in dangerous if p in expr_str), None):
        raise ValueError(f'Expression contains forbidden pattern: {found}')

    try:
        result = eval(expr_str, {'__builtins__': {}, 'pl': pl})  # noqa: S307
    except SyntaxError as e:
        raise ValueError(f'Syntax error in expression: {e}') from e
    except Exception as e:
        raise ValueError(f'Failed to parse expression: {e}') from e

    if not isinstance(result, pl.Expr):
        raise ValueError(f'Expression must return a Polars expression, got {type(result).__name__}')

    return result


class ExpressionHandler(OperationHandler):
    """Create a new column using a Polars expression string."""

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = ExpressionParams.model_validate(params)

        return lf.with_columns(parse_expression(validated.expression).alias(validated.column_name))
