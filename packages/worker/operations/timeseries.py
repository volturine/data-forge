import polars as pl

from operations.enums import (
    DurationUnit,
    TimeComponent,
    TimeDirection,
    TimeseriesOperationType,
)
from runtime.domain.compute.base import OperationParams


class TimeseriesParams(OperationParams):
    column: str
    operation_type: TimeseriesOperationType
    new_column: str
    component: TimeComponent | None = None
    value: int | float | None = None
    unit: DurationUnit | None = None
    direction: TimeDirection | None = None
    column2: str | None = None

    def extractor_name(self) -> str:
        if self.component is None:
            raise ValueError("timeseries extract requires component parameter")
        return self.component.extractor_name

    def require_duration_unit(self) -> DurationUnit:
        if self.unit is None:
            raise ValueError("timeseries operation requires unit parameter")
        return self.unit

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


def timeseries(lf: pl.LazyFrame, params: TimeseriesParams, **_) -> pl.LazyFrame:
    if params.operation_type == TimeseriesOperationType.EXTRACT:
        method = params.extractor_name()
        return lf.with_columns(getattr(pl.col(params.column).dt, method)().alias(params.new_column))

    if params.operation_type == TimeseriesOperationType.TIMESTAMP:
        unit = DurationUnit.MICROSECONDS if params.unit is None else params.unit
        expr = pl.col(params.column)
        match unit:
            case DurationUnit.NANOSECONDS:
                timestamp_expr = expr.dt.timestamp("ns")
            case DurationUnit.MICROSECONDS:
                timestamp_expr = expr.dt.timestamp("us")
            case DurationUnit.MILLISECONDS:
                timestamp_expr = expr.dt.timestamp("us") // 1_000
            case DurationUnit.SECONDS:
                timestamp_expr = expr.dt.timestamp("us") // 1_000_000
            case DurationUnit.MINUTES:
                timestamp_expr = expr.dt.timestamp("us") // 60_000_000
            case DurationUnit.HOURS:
                timestamp_expr = expr.dt.timestamp("us") // 3_600_000_000
            case DurationUnit.DAYS:
                timestamp_expr = expr.dt.timestamp("us") // 86_400_000_000
            case DurationUnit.WEEKS:
                timestamp_expr = expr.dt.timestamp("us") // 604_800_000_000
            case _:
                raise ValueError(f"Unsupported duration unit: {unit.value}")
        return lf.with_columns(timestamp_expr.alias(params.new_column))

    if params.operation_type in {
        TimeseriesOperationType.ADD,
        TimeseriesOperationType.SUBTRACT,
        TimeseriesOperationType.OFFSET,
    }:
        if params.value is None:
            raise ValueError("timeseries operation requires numeric value parameter")
        if not float(params.value).is_integer():
            raise ValueError("timeseries operation requires a whole number value")
        duration_unit = params.require_duration_unit()
        subtracting = params.operation_type == TimeseriesOperationType.SUBTRACT or params.direction == TimeDirection.SUBTRACT
        value_int = int(params.value)

        if duration_unit == DurationUnit.MONTHS:
            offset = f"-{value_int}mo" if subtracting else f"{value_int}mo"
            return lf.with_columns(pl.col(params.column).dt.offset_by(offset).alias(params.new_column))

        if not (-10_000_000 <= value_int <= 10_000_000):
            raise ValueError("Timeseries value must be between -10000000 and 10000000")
        duration = params.duration_expr(value_int)
        expr = pl.col(params.column) - duration if subtracting else pl.col(params.column) + duration
        return lf.with_columns(expr.alias(params.new_column))

    if params.operation_type == TimeseriesOperationType.DIFF:
        if not params.column2:
            raise ValueError("timeseries operation requires column2 parameter")
        return lf.with_columns((pl.col(params.column2) - pl.col(params.column)).alias(params.new_column))

    if params.operation_type in {
        TimeseriesOperationType.TRUNCATE,
        TimeseriesOperationType.ROUND,
    }:
        method = getattr(pl.col(params.column).dt, params.operation_type.value)
        return lf.with_columns(method(params.require_duration_unit().every_token).alias(params.new_column))

    raise ValueError(f"Unsupported timeseries operation: {params.operation_type}")
