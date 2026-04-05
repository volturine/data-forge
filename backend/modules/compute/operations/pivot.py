from enum import StrEnum

import polars as pl

from modules.compute.core.base import OperationHandler, OperationParams

_MAX_AUTO_PIVOT_VALUES = 200


class PivotAggregateFunction(StrEnum):
    FIRST = 'first'
    LAST = 'last'
    SUM = 'sum'
    MEAN = 'mean'
    MEDIAN = 'median'
    MIN = 'min'
    MAX = 'max'
    COUNT = 'count'


class PivotParams(OperationParams):
    index: list[str]
    columns: str
    values: str | None = None
    aggregate_function: PivotAggregateFunction = PivotAggregateFunction.FIRST
    on_columns: list[str] | None = None


class PivotHandler(OperationHandler):
    @staticmethod
    def _auto_on_columns(lf: pl.LazyFrame, pivot_column: str) -> list[str]:
        values = lf.select(pl.col(pivot_column)).unique().limit(_MAX_AUTO_PIVOT_VALUES + 1).collect().to_series().sort().to_list()
        if len(values) > _MAX_AUTO_PIVOT_VALUES:
            raise ValueError(
                f'Pivot requires explicit on_columns when {pivot_column!r} has more than {_MAX_AUTO_PIVOT_VALUES} distinct values'
            )
        return values

    @staticmethod
    def _pivot_with_aggregate(
        lf: pl.LazyFrame,
        *,
        pivot_column: str,
        on_columns: list[str],
        index: list[str],
        values: str | None,
        aggregate_function: PivotAggregateFunction,
    ) -> pl.LazyFrame:
        if aggregate_function == PivotAggregateFunction.COUNT:
            return lf.pivot(on=pivot_column, on_columns=on_columns, index=index, aggregate_function='len', values=values)
        if aggregate_function == PivotAggregateFunction.FIRST:
            return lf.pivot(on=pivot_column, on_columns=on_columns, index=index, aggregate_function='first', values=values)
        if aggregate_function == PivotAggregateFunction.LAST:
            return lf.pivot(on=pivot_column, on_columns=on_columns, index=index, aggregate_function='last', values=values)
        if aggregate_function == PivotAggregateFunction.SUM:
            return lf.pivot(on=pivot_column, on_columns=on_columns, index=index, aggregate_function='sum', values=values)
        if aggregate_function == PivotAggregateFunction.MEAN:
            return lf.pivot(on=pivot_column, on_columns=on_columns, index=index, aggregate_function='mean', values=values)
        if aggregate_function == PivotAggregateFunction.MEDIAN:
            return lf.pivot(on=pivot_column, on_columns=on_columns, index=index, aggregate_function='median', values=values)
        if aggregate_function == PivotAggregateFunction.MIN:
            return lf.pivot(on=pivot_column, on_columns=on_columns, index=index, aggregate_function='min', values=values)
        return lf.pivot(on=pivot_column, on_columns=on_columns, index=index, aggregate_function='max', values=values)

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = PivotParams.model_validate(params)

        if not validated.columns:
            raise ValueError('Pivot requires a pivot column')

        if not validated.index:
            raise ValueError('Pivot requires at least one index column')

        # on_columns expects unique *values* from the pivot column, not column names.
        # When not provided, compute from the data with a hard limit.
        on_columns = validated.on_columns or params.get('onColumns')
        if not on_columns:
            on_columns = self._auto_on_columns(lf, validated.columns)

        return self._pivot_with_aggregate(
            lf,
            pivot_column=validated.columns,
            on_columns=on_columns,
            index=validated.index,
            values=validated.values,
            aggregate_function=validated.aggregate_function,
        )
