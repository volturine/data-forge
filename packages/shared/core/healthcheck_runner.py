import uuid
from datetime import UTC, datetime

import polars as pl
from sqlmodel import Session

from contracts.healthcheck_models import HealthCheck, HealthCheckResult, HealthCheckType


def _build_expressions(checks: list[HealthCheck], schema_names: set[str]) -> tuple[list[pl.Expr], list[HealthCheck]]:
    """Build Polars aggregation expressions for all valid checks.

    Returns (expressions, valid_checks). Checks whose referenced column is
    missing from the schema are excluded so the caller can create immediate-
    failure results for them.
    """
    exprs: list[pl.Expr] = []
    valid: list[HealthCheck] = []

    sorted_names = sorted(schema_names)
    row_count_added = False

    for check in checks:
        check_type = check.check_type_kind()
        column_name = check.column_name()

        match check_type:
            case HealthCheckType.ROW_COUNT:
                valid.append(check)
                if row_count_added:
                    continue
                exprs.append(pl.len().alias(check.metric_alias('count')))
                row_count_added = True
            case HealthCheckType.COLUMN_NULL:
                if column_name is None or column_name not in schema_names:
                    continue
                pct = pl.col(column_name).null_count().cast(pl.Float64) / pl.len().cast(pl.Float64) * 100.0
                exprs.append(pct.alias(check.metric_alias('null_pct')))
                valid.append(check)
            case HealthCheckType.COLUMN_UNIQUE:
                if column_name is None or column_name not in schema_names:
                    continue
                exprs.append(pl.col(column_name).n_unique().alias(check.metric_alias('unique')))
                valid.append(check)
            case HealthCheckType.COLUMN_RANGE:
                if column_name is None or column_name not in schema_names:
                    continue
                exprs.append(pl.col(column_name).min().alias(check.metric_alias('min')))
                exprs.append(pl.col(column_name).max().alias(check.metric_alias('max')))
                valid.append(check)
            case HealthCheckType.COLUMN_COUNT:
                valid.append(check)
            case HealthCheckType.NULL_PERCENTAGE:
                threshold = float(check.config.get('threshold', 0))
                if threshold < 0:
                    continue
                if not sorted_names:
                    exprs.append(pl.lit(0.0).alias(check.metric_alias('null_pct')))
                    valid.append(check)
                    continue
                nulls = sum(pl.col(name).null_count().cast(pl.Float64) for name in sorted_names)
                total = pl.len().cast(pl.Float64) * float(len(sorted_names))
                pct = (nulls / total * 100.0).fill_nan(0.0)
                exprs.append(pct.alias(check.metric_alias('null_pct')))
                valid.append(check)
            case HealthCheckType.DUPLICATE_PERCENTAGE:
                columns = check.configured_columns(default=sorted_names)
                if any(column not in schema_names for column in columns):
                    continue
                exprs.append(pl.len().alias(check.metric_alias('rows')))
                exprs.append(pl.struct(columns).n_unique().alias(check.metric_alias('unique_rows')))
                valid.append(check)

    return exprs, valid


def _collected_values(collected: pl.DataFrame | None) -> dict[str, object]:
    if collected is None or collected.height == 0:
        return {}
    return dict(collected.row(0, named=True))


def run_healthchecks(session: Session, checks: list[HealthCheck], lf: pl.LazyFrame, *, critical_only: bool = False) -> list[HealthCheckResult]:
    """Run all health checks in a single LazyFrame evaluation."""
    selected = [check for check in checks if check.critical] if critical_only else checks
    if not selected:
        return []

    now = datetime.now(UTC)
    schema_names = set(lf.collect_schema().names())
    exprs, valid_checks = _build_expressions(selected, schema_names)
    valid_ids = {check.id for check in valid_checks}

    results: list[HealthCheckResult] = []
    for check in selected:
        if check.id in valid_ids:
            continue
        result = check.missing_column_result(now=now)
        session.add(result)
        results.append(result)

    values = _collected_values(lf.select(exprs).collect() if exprs else None)
    for check in valid_checks:
        passed, message, details = check.evaluate(values=values, schema_names=schema_names)
        result = HealthCheckResult(
            id=str(uuid.uuid4()),
            healthcheck_id=check.id,
            passed=passed,
            message=message,
            details=details,
            checked_at=now,
        )
        session.add(result)
        results.append(result)

    session.commit()
    return results
