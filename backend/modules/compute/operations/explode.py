"""Explode list columns operation."""

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class ExplodeParams(OperationParams):
    columns: list[str] | str


class ExplodeHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = ExplodeParams.model_validate(params)
        columns = [validated.columns] if isinstance(validated.columns, str) else validated.columns
        if not columns:
            raise ValueError('Explode requires at least one column')
        return lf.explode(columns)
