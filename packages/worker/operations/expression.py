"""Expression-based column operations."""

import ast
import operator
from collections.abc import Callable

import polars as pl

from operations.validation import validate_no_reflection_escape
from runtime.domain.compute.base import OperationHandler, OperationParams


class ExpressionParams(OperationParams):
    """Parameters for expression-based column creation."""

    expression: str
    column_name: str


_POLARS_ROOT_NAMES = {
    "all",
    "any",
    "coalesce",
    "col",
    "concat_arr",
    "concat_list",
    "concat_str",
    "count",
    "date",
    "datetime",
    "duration",
    "element",
    "first",
    "format",
    "int_range",
    "last",
    "len",
    "lit",
    "when",
}
_POLARS_DTYPE_NAMES = {
    "Array",
    "Binary",
    "Boolean",
    "Categorical",
    "Date",
    "Datetime",
    "Decimal",
    "Duration",
    "Enum",
    "Float32",
    "Float64",
    "Int8",
    "Int16",
    "Int32",
    "Int64",
    "List",
    "Object",
    "String",
    "Struct",
    "Time",
    "UInt8",
    "UInt16",
    "UInt32",
    "UInt64",
}
_BINARY_OPERATORS: dict[type[ast.operator], Callable[..., object]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.BitAnd: operator.and_,
    ast.BitOr: operator.or_,
    ast.BitXor: operator.xor,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[..., object]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Invert: operator.invert,
}
_COMPARISON_OPERATORS: dict[type[ast.cmpop], Callable[..., object]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


def _evaluate_expression_node(node: ast.AST) -> object:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id == "pl":
            return pl
        raise ValueError(f"Expression name is not allowed: {node.id}")
    if isinstance(node, ast.List):
        return [_evaluate_expression_node(item) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_evaluate_expression_node(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        result: dict[object, object] = {}
        for key, value in zip(node.keys, node.values, strict=True):
            if key is None:
                raise ValueError("Dictionary unpacking is not allowed")
            result[_evaluate_expression_node(key)] = _evaluate_expression_node(value)
        return result
    if isinstance(node, ast.Attribute):
        if node.attr.startswith("_"):
            raise ValueError("Expression contains forbidden dunder access")
        owner = _evaluate_expression_node(node.value)
        if owner is pl and node.attr not in _POLARS_ROOT_NAMES | _POLARS_DTYPE_NAMES:
            raise ValueError(f"Polars root attribute is not allowed: {node.attr}")
        if owner is not pl and not isinstance(owner, pl.Expr) and not type(owner).__module__.startswith("polars"):
            raise ValueError(f"Attribute access is not allowed on {type(owner).__name__}")
        return getattr(owner, node.attr)
    if isinstance(node, ast.Call):
        target = _evaluate_expression_node(node.func)
        if not callable(target):
            raise ValueError("Expression call target is not callable")
        if any(keyword.arg is None for keyword in node.keywords):
            raise ValueError("Keyword unpacking is not allowed")
        args = [_evaluate_expression_node(arg) for arg in node.args]
        kwargs = {keyword.arg: _evaluate_expression_node(keyword.value) for keyword in node.keywords if keyword.arg is not None}
        return target(*args, **kwargs)
    if isinstance(node, ast.BinOp):
        binary_operation = _BINARY_OPERATORS.get(type(node.op))
        if binary_operation is None:
            raise ValueError(f"Binary operator is not allowed: {type(node.op).__name__}")
        return binary_operation(_evaluate_expression_node(node.left), _evaluate_expression_node(node.right))
    if isinstance(node, ast.UnaryOp):
        unary_operation = _UNARY_OPERATORS.get(type(node.op))
        if unary_operation is None:
            raise ValueError(f"Unary operator is not allowed: {type(node.op).__name__}")
        return unary_operation(_evaluate_expression_node(node.operand))
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise ValueError("Chained comparisons are not allowed")
        comparison_operation = _COMPARISON_OPERATORS.get(type(node.ops[0]))
        if comparison_operation is None:
            raise ValueError(f"Comparison operator is not allowed: {type(node.ops[0]).__name__}")
        return comparison_operation(_evaluate_expression_node(node.left), _evaluate_expression_node(node.comparators[0]))
    raise ValueError(f"Expression syntax is not allowed: {type(node).__name__}")


def parse_expression(expr_str: str) -> pl.Expr:
    """Parse a Polars expression string.

    Provides full access to the pl.* namespace.
    Usage: pl.col("column").cast(pl.Float64)
    """
    if not expr_str or not expr_str.strip():
        raise ValueError("Expression cannot be empty")

    validate_no_reflection_escape(expr_str, label="Expression")

    try:
        syntax = ast.parse(expr_str, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Syntax error in expression: {e}") from e
    try:
        result = _evaluate_expression_node(syntax.body)
    except Exception as e:
        raise ValueError(f"Failed to parse expression: {e}") from e

    if not isinstance(result, pl.Expr):
        raise ValueError(f"Expression must return a Polars expression, got {type(result).__name__}")

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
