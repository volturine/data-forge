from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import polars as pl

from runtime.domain.compute.schemas import BuildStatus
from runtime.domain.healthcheck_models import HealthCheckType
from runtime.worker_runtime_client import HealthCheckSpec, client_from_env
from runtime.namespace import get_namespace


@dataclass(frozen=True)
class HealthCheckDetail:
    name: str
    passed: bool
    message: str
    critical: bool


@dataclass(frozen=True)
class HealthCheckResult:
    healthcheck_id: str
    passed: bool
    message: str
    details: dict[str, object]
    checked_at: datetime


def resolve_build_status(
    results: Sequence[HealthCheckResult],
    checks: Sequence[HealthCheckSpec] | None = None,
) -> tuple[BuildStatus, str | None, list[HealthCheckDetail] | None]:
    if not results:
        return BuildStatus.SUCCESS, None, None
    names = {check.id: check.name for check in checks} if checks else {}
    critical = {check.id: check.critical for check in checks} if checks else {}
    failed = [result for result in results if not result.passed]
    if not failed:
        return BuildStatus.SUCCESS, f"{len(results)}/{len(results)} passed", None
    details = [
        HealthCheckDetail(
            name=names.get(result.healthcheck_id, result.healthcheck_id),
            passed=result.passed,
            message=result.message,
            critical=critical.get(result.healthcheck_id, False),
        )
        for result in results
    ]
    return BuildStatus.WARNING, f"{len(failed)}/{len(results)} failed", details


_SCANNERS: dict[str, Callable[[str], pl.LazyFrame]] = {
    "parquet": pl.scan_parquet,
    "csv": pl.scan_csv,
    "ndjson": pl.scan_ndjson,
}


def load_lazy_frame(output_path: str, export_format: str) -> pl.LazyFrame | None:
    if scanner := _SCANNERS.get(export_format):
        return scanner(output_path)
    if export_format == "json":
        return pl.read_json(output_path).lazy()
    return None


def _alias(check: HealthCheckSpec, suffix: str) -> str:
    if HealthCheckType.require(check.check_type) == HealthCheckType.ROW_COUNT and suffix == "count":
        return "row_count__count"
    return f"{check.id}__{suffix}"


def _column(check: HealthCheckSpec) -> str | None:
    value = check.config.get("column")
    return value if isinstance(value, str) and value else None


def _config_int(check: HealthCheckSpec, key: str) -> int | None:
    value = check.config.get(key)
    return int(cast(int | float | str, value)) if value is not None else None


def _config_float(check: HealthCheckSpec, key: str) -> float | None:
    value = check.config.get(key)
    return float(cast(int | float | str, value)) if value is not None else None


def _configured_columns(check: HealthCheckSpec, *, default: list[str]) -> list[str]:
    values = check.config.get("columns")
    if not isinstance(values, list):
        return default
    columns = [str(value) for value in values if str(value)]
    return columns or default


def _details(check: HealthCheckSpec, **actuals: object) -> dict[str, object]:
    return {**check.config, **actuals}


def _value(check: HealthCheckSpec, values: dict[str, object], suffix: str) -> object:
    return values[_alias(check, suffix)]


def _value_int(check: HealthCheckSpec, values: dict[str, object], suffix: str) -> int:
    return int(cast(int | float | str, _value(check, values, suffix)))


def _value_float(check: HealthCheckSpec, values: dict[str, object], suffix: str) -> float:
    return float(cast(int | float | str, _value(check, values, suffix)))


def _missing_column(check: HealthCheckSpec, *, now: datetime) -> HealthCheckResult:
    return HealthCheckResult(
        healthcheck_id=check.id,
        passed=False,
        message=f'Column "{_column(check) or ""}" not found in dataset',
        details=_details(check, error="column_not_found"),
        checked_at=now,
    )


def _evaluate(check: HealthCheckSpec, *, values: dict[str, object], schema_names: set[str]) -> tuple[bool, str, dict[str, object]]:
    match HealthCheckType.require(check.check_type):
        case HealthCheckType.ROW_COUNT:
            count = _value_int(check, values, "count")
            minimum = _config_int(check, "min_rows")
            maximum = _config_int(check, "max_rows")
            messages = ([f"Too few: {count} < {minimum}"] if minimum is not None and count < minimum else []) + (
                [f"Too many: {count} > {maximum}"] if maximum is not None and count > maximum else []
            )
            return not messages, "; ".join(messages) or f"Row count: {count}", _details(check, actual_count=count)
        case HealthCheckType.COLUMN_COUNT:
            count = len(schema_names)
            minimum = _config_int(check, "min_columns")
            maximum = _config_int(check, "max_columns")
            messages = ([f"Too few: {count} < {minimum}"] if minimum is not None and count < minimum else []) + (
                [f"Too many: {count} > {maximum}"] if maximum is not None and count > maximum else []
            )
            return not messages, "; ".join(messages) or f"Column count: {count}", _details(check, actual_count=count)
        case HealthCheckType.COLUMN_NULL | HealthCheckType.NULL_PERCENTAGE:
            percentage = _value_float(check, values, "null_pct")
            threshold = _config_float(check, "threshold") or 0.0
            return percentage <= threshold, f"Nulls: {percentage:.1f}% (threshold: {threshold}%)", _details(check, actual_percentage=round(percentage, 2))
        case HealthCheckType.COLUMN_UNIQUE:
            unique = _value_int(check, values, "unique")
            expected = _config_int(check, "expected_unique")
            if expected is None:
                return True, f"Unique values: {unique}", _details(check, actual_unique=unique)
            return unique == expected, f"Unique: {unique} (expected: {expected})", _details(check, actual_unique=unique)
        case HealthCheckType.COLUMN_RANGE:
            minimum_value = _value(check, values, "min")
            maximum_value = _value(check, values, "max")
            range_minimum = _config_float(check, "min")
            range_maximum = _config_float(check, "max")
            messages = (
                [f"Min {minimum_value!r} < {range_minimum}"]
                if range_minimum is not None and float(cast(int | float | str, minimum_value)) < range_minimum
                else []
            ) + (
                [f"Max {maximum_value!r} > {range_maximum}"]
                if range_maximum is not None and float(cast(int | float | str, maximum_value)) > range_maximum
                else []
            )
            return (
                not messages,
                "; ".join(messages) or f"Range: [{minimum_value!r}, {maximum_value!r}]",
                _details(check, actual_min=minimum_value, actual_max=maximum_value),
            )
        case HealthCheckType.DUPLICATE_PERCENTAGE:
            total = _value_int(check, values, "rows")
            unique = _value_int(check, values, "unique_rows")
            threshold = _config_float(check, "threshold") or 0.0
            percentage = 0.0 if total == 0 else (1 - unique / total) * 100.0
            return percentage <= threshold, f"Duplicates: {percentage:.1f}% (threshold: {threshold}%)", _details(check, actual_percentage=round(percentage, 2))
    raise ValueError(f"Unsupported healthcheck type: {check.check_type!r}")


def _expressions(checks: list[HealthCheckSpec], schema_names: set[str]) -> tuple[list[pl.Expr], list[HealthCheckSpec]]:
    expressions: list[pl.Expr] = []
    valid: list[HealthCheckSpec] = []
    sorted_names = sorted(schema_names)
    row_count_added = False
    for check in checks:
        check_type = HealthCheckType.require(check.check_type)
        column = _column(check)
        match check_type:
            case HealthCheckType.ROW_COUNT:
                valid.append(check)
                if not row_count_added:
                    expressions.append(pl.len().alias(_alias(check, "count")))
                    row_count_added = True
            case HealthCheckType.COLUMN_NULL if column is not None and column in schema_names:
                expressions.append((pl.col(column).null_count().cast(pl.Float64) / pl.len().cast(pl.Float64) * 100.0).alias(_alias(check, "null_pct")))
                valid.append(check)
            case HealthCheckType.COLUMN_UNIQUE if column is not None and column in schema_names:
                expressions.append(pl.col(column).n_unique().alias(_alias(check, "unique")))
                valid.append(check)
            case HealthCheckType.COLUMN_RANGE if column is not None and column in schema_names:
                expressions.extend([pl.col(column).min().alias(_alias(check, "min")), pl.col(column).max().alias(_alias(check, "max"))])
                valid.append(check)
            case HealthCheckType.COLUMN_COUNT:
                valid.append(check)
            case HealthCheckType.NULL_PERCENTAGE if float(cast(int | float | str, check.config.get("threshold", 0))) >= 0:
                expression = (
                    pl.lit(0.0)
                    if not sorted_names
                    else (
                        sum(pl.col(name).null_count().cast(pl.Float64) for name in sorted_names)
                        / (pl.len().cast(pl.Float64) * float(len(sorted_names)))
                        * 100.0
                    ).fill_nan(0.0)
                )
                expressions.append(expression.alias(_alias(check, "null_pct")))
                valid.append(check)
            case HealthCheckType.DUPLICATE_PERCENTAGE:
                columns = _configured_columns(check, default=sorted_names)
                if not any(column_name not in schema_names for column_name in columns):
                    expressions.extend([pl.len().alias(_alias(check, "rows")), pl.struct(columns).n_unique().alias(_alias(check, "unique_rows"))])
                    valid.append(check)
    return expressions, valid


def run_healthchecks(checks: list[HealthCheckSpec], lazy_frame: pl.LazyFrame) -> list[HealthCheckResult]:
    if not checks:
        return []
    now = datetime.now(UTC)
    schema_names = set(lazy_frame.collect_schema().names())
    expressions, valid_checks = _expressions(checks, schema_names)
    valid_ids = {check.id for check in valid_checks}
    results = [_missing_column(check, now=now) for check in checks if check.id not in valid_ids]
    collected = lazy_frame.select(expressions).collect() if expressions else None
    values = dict(collected.row(0, named=True)) if collected is not None and collected.height > 0 else {}
    for check in valid_checks:
        passed, message, details = _evaluate(check, values=values, schema_names=schema_names)
        results.append(HealthCheckResult(check.id, passed, message, details, now))
    return results


def persist_results(results: list[HealthCheckResult]) -> None:
    if results:
        client_from_env().record_healthcheck_results(
            namespace=get_namespace(),
            results=[
                {
                    "healthcheck_id": result.healthcheck_id,
                    "passed": result.passed,
                    "message": result.message,
                    "details": result.details,
                    "checked_at": result.checked_at.isoformat(),
                }
                for result in results
            ],
        )
