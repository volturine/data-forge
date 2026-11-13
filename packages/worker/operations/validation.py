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
# plans, or hands out another library's I/O surface. ``format``/``format_map``
# resolve attribute paths inside the template string, which the AST pass cannot
# see (e.g. ``"{0.gi_frame.f_globals[os].environ}".format(rows)``); ``mro``
# leads from any class to ``object``. Arrow/numpy interop is denied because
# raw buffers can be reassembled into arrays whose offsets read process memory
# (e.g. ``Series.to_arrow()`` then ``Array.from_buffers`` with a forged offset).
_FORBIDDEN_UDF_ATTRIBUTES = frozenset(
    {
        "address",
        "as_buffer",
        "buffers",
        "from_arrow",
        "from_buffer",
        "from_buffers",
        "from_numpy",
        "from_pandas",
        "to_arrow",
        "to_numpy",
        "to_pybytes",
        "ctypes",
        "deserialize",
        "dump",
        "format",
        "format_map",
        "from_json",
        "func_code",
        "func_globals",
        "im_func",
        "im_self",
        "load_from_file",
        "mro",
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
# ``gi_``/``cr_``/``ag_``/``f_``/``tb_``/``co_`` are generator, coroutine,
# frame, traceback and code attributes. A frame's ``f_back``/``f_globals``/
# ``f_builtins`` reach the worker's real globals and builtins without dunders,
# and polars itself returns generators (e.g. ``DataFrame.iter_rows``).
_FORBIDDEN_UDF_ATTRIBUTE_PREFIXES = ("_", "write_", "sink_", "register_", "gi_", "cr_", "ag_", "f_", "tb_", "co_")
# Generators and coroutines are the UDF code's own source of frame handles.
_FORBIDDEN_UDF_NODES = (ast.Yield, ast.YieldFrom, ast.Await, ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith)


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
    """Reject imports, generators, attribute writes and escape-capable attribute names in UDF code.

    ``validate_no_reflection_escape`` already blocks dynamic attribute lookup and
    this pass blocks ``str.format``, so every attribute UDF code can reach is a
    literal ``ast.Attribute`` node.
    """
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Import | ast.ImportFrom):
            raise ValueError(f"{label} cannot import modules")
        if isinstance(node, _FORBIDDEN_UDF_NODES) or (isinstance(node, ast.comprehension) and node.is_async):
            raise ValueError(f"{label} cannot define generators or coroutines")
        if not isinstance(node, ast.Attribute):
            continue
        if not isinstance(node.ctx, ast.Load):
            raise ValueError(f"{label} cannot assign or delete attributes")
        if node.attr in _FORBIDDEN_UDF_ATTRIBUTES or node.attr.startswith(_FORBIDDEN_UDF_ATTRIBUTE_PREFIXES):
            raise ValueError(f"{label} cannot use forbidden attribute: {node.attr}")
