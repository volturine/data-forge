"""Explode list columns operation."""

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class ExplodeParams(OperationParams):
    columns: list[str] | str


class ExplodeHandler(OperationHandler):
    @property
    def name(self) -> str:
        return 'explode'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = ExplodeParams.model_validate(params)
        columns = validated.columns
        if isinstance(columns, str):
            columns = [columns]
        if not columns:
            raise ValueError('Explode requires at least one column')
        return lf.explode(columns)
