"""Shared validation helpers for compute operations."""

import ast
import re

_DUNDER_RE = re.compile(r"(^|[^A-Za-z0-9_])__[^\s]*__")
_REFLECTION_PATTERNS = (
    "__",
    "getattr(",
    "setattr(",
    "delattr(",
    "vars(",
    "dir(",
    "globals(",
    "locals(",
    "object.",
    "type(",
    "super(",
)

# Attribute names UDF code may not reach on polars objects or values derived
# from them: anything that writes files, executes SQL or plugins, loads pickled
# plans, or hands out another library's I/O surface.
_FORBIDDEN_UDF_ATTRIBUTES = frozenset(
    {
        "ctypes",
        "deserialize",
        "dump",
        "from_json",
        "load_from_file",
        "plot",
        "remote",
        "save",
        "save_to_file",
        "serialize",
        "show_graph",
        "sql",
        "style",
        "to_jax",
        "to_pandas",
        "to_torch",
        "tofile",
    },
)
_FORBIDDEN_UDF_ATTRIBUTE_PREFIXES = ("_", "write_", "sink_", "register_")


def validate_regex_pattern(pattern: str) -> None:
    """Raise ValueError if *pattern* does not compile as a valid Python regex."""
    try:
        re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern: {e}") from e


def validate_no_reflection_escape(code: str, *, label: str) -> None:
    """Reject obvious dunder and reflection escape patterns."""
    if _DUNDER_RE.search(code):
        raise ValueError(f"{label} contains forbidden dunder access")
    lowered = code.lower()
    for pattern in _REFLECTION_PATTERNS:
        if pattern in lowered:
            raise ValueError(f"{label} contains forbidden pattern: {pattern}")


def validate_udf_attribute_access(code: str, *, label: str) -> None:
    """Reject imports, attribute writes and I/O-capable attribute names in UDF code.

    ``validate_no_reflection_escape`` already blocks dynamic attribute lookup, so
    every attribute UDF code can reach is a literal ``ast.Attribute`` node.
    """
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Import | ast.ImportFrom):
            raise ValueError(f"{label} cannot import modules")
        if not isinstance(node, ast.Attribute):
            continue
        if not isinstance(node.ctx, ast.Load):
            raise ValueError(f"{label} cannot assign or delete attributes")
        if node.attr in _FORBIDDEN_UDF_ATTRIBUTES or node.attr.startswith(_FORBIDDEN_UDF_ATTRIBUTE_PREFIXES):
            raise ValueError(f"{label} cannot use forbidden attribute: {node.attr}")
