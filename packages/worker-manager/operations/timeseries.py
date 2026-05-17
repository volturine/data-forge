import polars as pl
from contracts.compute.base import OperationHandler, OperationParams
from contracts.enums import DataForgeStrEnum
from contracts.step_config_enums import (
    DurationUnit,
    TimeComponent,
    TimeDirection,
    TimeseriesOperationType,
)


class TimestampUnit(DataForgeStrEnum):
    NS = "ns"
    US = "us"
    MS = "ms"


class TimeseriesParams(OperationParams):
    column: str
    operation_type: TimeseriesOperationType
    new_column: str
    component: TimeComponent | None = None
    value: int | float | None = None
    unit: str | None = None
    direction: TimeDirection | None = None
    column2: str | None = None

    def require_component(self) -> TimeComponent:
        if self.component is None:
            raise ValueError("timeseries extract requires component parameter")
        return self.component

    def extractor_name(self) -> str:
        return self.require_component().extractor_name

    def require_duration_unit(self) -> DurationUnit:
        if self.unit is None:
            raise ValueError("timeseries operation requires unit parameter")
        try:
            return DurationUnit.require(self.unit)
        except ValueError as exc:
            raise ValueError(f"Unsupported duration unit: {self.unit}") from exc

    def duration_expr(self, value: int) -> pl.Expr:
        duration_unit = self.require_duration_unit()
        if duration_unit == DurationUnit.SECONDS:
            return pl.duration(seconds=value)
        if duration_unit == DurationUnit.MINUTES:
            return pl.duration(minutes=value)
        if duration_unit == DurationUnit.HOURS:
            return pl.duration(hours=value)
        if duration_unit == DurationUnit.DAYS:
            return pl.duration(days=value)
        if duration_unit == DurationUnit.WEEKS:
            return pl.duration(weeks=value)
        raise ValueError(f"Unsupported duration unit: {duration_unit.value}")

    def every_token(self) -> str:
        return self.require_duration_unit().every_token


class TimeseriesHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = TimeseriesParams.model_validate(params)

        if validated.operation_type == TimeseriesOperationType.EXTRACT:
            method = validated.extractor_name()
            return lf.with_columns(getattr(pl.col(validated.column).dt, method)().alias(validated.new_column))

        if validated.operation_type == TimeseriesOperationType.TIMESTAMP:
            unit = validated.unit
            if unit == TimestampUnit.NS.value:
                return lf.with_columns(pl.col(validated.column).dt.timestamp("ns").alias(validated.new_column))
            if unit == TimestampUnit.MS.value:
                return lf.with_columns(pl.col(validated.column).dt.timestamp("ms").alias(validated.new_column))
            return lf.with_columns(pl.col(validated.column).dt.timestamp("us").alias(validated.new_column))

        if validated.operation_type in {
            TimeseriesOperationType.ADD,
            TimeseriesOperationType.SUBTRACT,
            TimeseriesOperationType.OFFSET,
        }:
            if validated.value is None:
                raise ValueError("timeseries operation requires numeric value parameter")
            duration_unit = validated.require_duration_unit()
            subtracting = validated.operation_type == TimeseriesOperationType.SUBTRACT or validated.direction == TimeDirection.SUBTRACT

            if duration_unit == DurationUnit.MONTHS:
                offset = f"-{validated.value}mo" if subtracting else f"{validated.value}mo"
                return lf.with_columns(pl.col(validated.column).dt.offset_by(offset).alias(validated.new_column))

            value_int = int(validated.value)
            if not (-10_000_000 <= value_int <= 10_000_000):
                raise ValueError("Timeseries value must be between -10000000 and 10000000")
            duration = validated.duration_expr(value_int)
            expr = pl.col(validated.column) - duration if subtracting else pl.col(validated.column) + duration
            return lf.with_columns(expr.alias(validated.new_column))

        if validated.operation_type == TimeseriesOperationType.DIFF:
            if not validated.column2:
                raise ValueError("timeseries operation requires column2 parameter")
            return lf.with_columns((pl.col(validated.column2) - pl.col(validated.column)).alias(validated.new_column))

        if validated.operation_type in {
            TimeseriesOperationType.TRUNCATE,
            TimeseriesOperationType.ROUND,
        }:
            method = getattr(pl.col(validated.column).dt, validated.operation_type.value)
            return lf.with_columns(method(validated.every_token()).alias(validated.new_column))

        raise ValueError(f"Unsupported timeseries operation: {validated.operation_type}")
