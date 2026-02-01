from collections.abc import Callable

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


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


class StringTransformHandler(OperationHandler):
    STRING_METHODS: dict[str, Callable[[pl.Expr], pl.Expr]] = {
        'uppercase': lambda col: col.str.to_uppercase(),
        'lowercase': lambda col: col.str.to_lowercase(),
        'title': lambda col: col.str.to_titlecase(),
        'strip': lambda col: col.str.strip_chars(),
        'lstrip': lambda col: col.str.strip_chars_start(),
        'rstrip': lambda col: col.str.strip_chars_end(),
        'length': lambda col: col.str.len_chars(),
    }

    @property
    def name(self) -> str:
        return 'string_transform'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = StringTransformParams.model_validate(params)
        target = validated.new_column or validated.column
        if not target:
            raise ValueError('string_transform requires new_column parameter')

        base = pl.col(validated.column)
        method = self._get_string_method(validated.method)
        if method:
            return lf.with_columns(method(base).alias(target))

        if validated.method == 'slice':
            start = validated.start or 0
            return lf.with_columns(base.str.slice(start, validated.end).alias(target))

        if validated.method == 'replace':
            if not validated.pattern:
                raise ValueError('string_transform replace requires pattern parameter')
            replacement = validated.replacement or ''
            return lf.with_columns(base.str.replace_all(validated.pattern, replacement).alias(target))

        if validated.method == 'extract':
            if not validated.pattern:
                raise ValueError('string_transform extract requires pattern parameter')
            group_index = validated.group_index or 0
            return lf.with_columns(base.str.extract(validated.pattern, group_index).alias(target))

        if validated.method == 'split':
            delimiter = validated.delimiter or ' '
            return lf.with_columns(base.str.split(delimiter).alias(target))

        if validated.method == 'split_take':
            delimiter = validated.delimiter or ' '
            index = validated.index or 0
            return lf.with_columns(base.str.split(delimiter).list.get(index).alias(target))

        raise ValueError(f'Unsupported string method: {validated.method}')

    def _get_string_method(self, name: str) -> Callable[[pl.Expr], pl.Expr] | None:
        return self.STRING_METHODS.get(name)


def get_string_method(name: str) -> Callable[[pl.Expr], pl.Expr] | None:
    return StringTransformHandler()._get_string_method(name)
