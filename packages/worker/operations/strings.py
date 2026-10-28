from collections.abc import Callable

import polars as pl

from operations.enums import StringTransformMethod
from operations.validation import validate_regex_pattern
from runtime.domain.compute.base import OperationParams


class StringTransformParams(OperationParams):
    column: str
    method: StringTransformMethod
    new_column: str | None = None
    start: int | None = None
    end: int | None = None
    pattern: str | None = None
    replacement: str | None = None
    group_index: int | None = None
    delimiter: str | None = None
    index: int | None = None


_STRING_METHODS: dict[StringTransformMethod, Callable[[pl.Expr], pl.Expr]] = {
    StringTransformMethod.UPPERCASE: lambda col: col.str.to_uppercase(),
    StringTransformMethod.LOWERCASE: lambda col: col.str.to_lowercase(),
    StringTransformMethod.TITLE: lambda col: col.str.to_titlecase(),
    StringTransformMethod.STRIP: lambda col: col.str.strip_chars(),
    StringTransformMethod.LSTRIP: lambda col: col.str.strip_chars_start(),
    StringTransformMethod.RSTRIP: lambda col: col.str.strip_chars_end(),
    StringTransformMethod.LENGTH: lambda col: col.str.len_chars(),
}


def string_transform(lf: pl.LazyFrame, params: StringTransformParams, **_) -> pl.LazyFrame:
    target = params.new_column or params.column
    if not target:
        raise ValueError("string_transform requires new_column parameter")

    base = pl.col(params.column)
    method = _STRING_METHODS.get(params.method)
    if method:
        return lf.with_columns(method(base).alias(target))

    if params.method == StringTransformMethod.SLICE:
        start = params.start or 0
        length = None if params.end is None else max(params.end - start, 0)
        return lf.with_columns(base.str.slice(start, length).alias(target))

    if params.method == StringTransformMethod.REPLACE:
        if not params.pattern:
            raise ValueError("string_transform replace requires pattern parameter")
        validate_regex_pattern(params.pattern)
        return lf.with_columns(base.str.replace_all(params.pattern, params.replacement or "").alias(target))

    if params.method == StringTransformMethod.EXTRACT:
        if not params.pattern:
            raise ValueError("string_transform extract requires pattern parameter")
        validate_regex_pattern(params.pattern)
        return lf.with_columns(base.str.extract(params.pattern, params.group_index or 0).alias(target))

    if params.method == StringTransformMethod.SPLIT:
        return lf.with_columns(base.str.split(params.delimiter or " ").alias(target))

    if params.method == StringTransformMethod.SPLIT_TAKE:
        return lf.with_columns(base.str.split(params.delimiter or " ").list.get(params.index or 0).alias(target))

    raise ValueError(f"Unsupported string method: {params.method}")
