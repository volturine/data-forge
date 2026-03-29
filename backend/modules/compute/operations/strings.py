from collections.abc import Callable

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams
from modules.compute.operations._validation import validate_regex_pattern


class StringTransformParams(OperationParams):
    column: str
    method: str
    new_column: str | None = None
    start: int | None = None
    end: int | None = None
    pattern: str | None = None
    replacement: str | None = None
    group_index: int | None = None
    delimiter: str | None = None
    index: int | None = None


_STRING_METHODS: dict[str, Callable[[pl.Expr], pl.Expr]] = {
    'uppercase': lambda col: col.str.to_uppercase(),
    'lowercase': lambda col: col.str.to_lowercase(),
    'title': lambda col: col.str.to_titlecase(),
    'strip': lambda col: col.str.strip_chars(),
    'lstrip': lambda col: col.str.strip_chars_start(),
    'rstrip': lambda col: col.str.strip_chars_end(),
    'length': lambda col: col.str.len_chars(),
}


def get_string_method(name: str) -> Callable[[pl.Expr], pl.Expr] | None:
    return _STRING_METHODS.get(name)


class StringTransformHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = StringTransformParams.model_validate(params)
        target = validated.new_column or validated.column
        if not target:
            raise ValueError('string_transform requires new_column parameter')

        base = pl.col(validated.column)
        method = get_string_method(validated.method)
        if method:
            return lf.with_columns(method(base).alias(target))

        if validated.method == 'slice':
            return lf.with_columns(base.str.slice(validated.start or 0, validated.end).alias(target))

        if validated.method == 'replace':
            if not validated.pattern:
                raise ValueError('string_transform replace requires pattern parameter')
            validate_regex_pattern(validated.pattern)
            return lf.with_columns(base.str.replace_all(validated.pattern, validated.replacement or '').alias(target))

        if validated.method == 'extract':
            if not validated.pattern:
                raise ValueError('string_transform extract requires pattern parameter')
            validate_regex_pattern(validated.pattern)
            return lf.with_columns(base.str.extract(validated.pattern, validated.group_index or 0).alias(target))

        if validated.method == 'split':
            return lf.with_columns(base.str.split(validated.delimiter or ' ').alias(target))

        if validated.method == 'split_take':
            return lf.with_columns(base.str.split(validated.delimiter or ' ').list.get(validated.index or 0).alias(target))

        raise ValueError(f'Unsupported string method: {validated.method}')
