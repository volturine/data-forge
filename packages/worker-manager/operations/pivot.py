import polars as pl
from contracts.compute.base import OperationHandler, OperationParams
from contracts.step_config_enums import PivotAggregateFunction

_MAX_AUTO_PIVOT_VALUES = 200


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
            raise ValueError(f"Pivot requires explicit on_columns when {pivot_column!r} has more than {_MAX_AUTO_PIVOT_VALUES} distinct values")
        return values

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = PivotParams.model_validate(params)

        if not validated.columns:
            raise ValueError("Pivot requires a pivot column")

        if not validated.index:
            raise ValueError("Pivot requires at least one index column")

        on_columns = validated.on_columns or params.get("onColumns")
        if not on_columns:
            on_columns = self._auto_on_columns(lf, validated.columns)

        return lf.pivot(
            on=validated.columns,
            on_columns=on_columns,
            index=validated.index,
            values=validated.values,
            aggregate_function=validated.aggregate_function.polars_aggregate_function,
        )
