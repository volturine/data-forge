from typing import Any, Literal

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams


class PivotParams(OperationParams):
    index: list[str]
    columns: str
    values: str | None = None
    aggregate_function: Literal['first', 'last', 'sum', 'mean', 'median', 'min', 'max', 'count'] = 'first'
    on_columns: list[str] | None = None


class PivotHandler(OperationHandler):
    @property
    def name(self) -> str:
        return 'pivot'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = PivotParams.model_validate(params)
        on_columns = validated.on_columns or params.get('onColumns')
        if not on_columns:
            on_columns = lf.collect_schema().names()

        if not validated.columns:
            raise ValueError('Pivot requires a pivot column')

        if not validated.index:
            raise ValueError('Pivot requires at least one index column')

        agg = None if validated.aggregate_function == 'count' else validated.aggregate_function
        agg_value: Any = agg
        if validated.values:
            return lf.pivot(
                on=validated.columns,
                on_columns=on_columns,
                index=validated.index,
                values=validated.values,
                aggregate_function=agg_value,
            )
        return lf.pivot(
            on=validated.columns,
            on_columns=on_columns,
            index=validated.index,
            aggregate_function=agg_value,
        )
