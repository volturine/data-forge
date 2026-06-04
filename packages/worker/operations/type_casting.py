from __future__ import annotations

from typing import Any

import polars as pl

_TYPE_CASTERS: dict[str, tuple[type[Any] | None, pl.DataType]] = {
    "Int64": (int, pl.Int64()),
    "Float64": (float, pl.Float64()),
    "Boolean": (bool, pl.Boolean()),
    "String": (str, pl.Utf8()),
    "Utf8": (str, pl.Utf8()),
    "Date": (None, pl.Date()),
    "Datetime": (None, pl.Datetime()),
}


def cast_value(value: Any, type_name: str | None) -> Any:
    if not type_name or value is None:
        return value
    spec = _TYPE_CASTERS.get(type_name)
    if not spec:
        return value
    caster, _ = spec
    return caster(value) if caster else value


def get_polars_type(type_name: str | None) -> pl.DataType | None:
    if not type_name:
        return None
    spec = _TYPE_CASTERS.get(type_name)
    return spec[1] if spec else None


def require_polars_type(type_name: str) -> pl.DataType:
    dtype = get_polars_type(type_name)
    if dtype is not None:
        return dtype
    supported = ", ".join(sorted(_TYPE_CASTERS.keys()))
    raise ValueError(f"Unsupported cast type: {type_name}. Supported types: {supported}")
