import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypeAlias

import polars as pl
from sqlalchemy import select
from sqlmodel import Session

from core.exceptions import HealthcheckNotFoundError, HealthcheckValidationError
from modules.datasource.models import DataSource
from modules.healthcheck.models import HealthCheck, HealthCheckResult
from modules.healthcheck.schemas import HealthCheckCreate, HealthCheckResponse, HealthCheckResultResponse, HealthCheckUpdate

HealthcheckDetails: TypeAlias = dict[str, object]
HealthcheckEvaluator: TypeAlias = Callable[[HealthCheck, pl.DataFrame], tuple[bool, str, HealthcheckDetails]]


def list_healthchecks(session: Session, datasource_id: str) -> list[HealthCheckResponse]:
    datasource = session.get(DataSource, datasource_id)
    if not datasource:
        return []
    result = session.execute(
        select(HealthCheck).where(HealthCheck.datasource_id == datasource_id),  # type: ignore[arg-type]
    )
    checks = result.scalars().all()
    return [HealthCheckResponse.model_validate(check) for check in checks]


def create_healthcheck(session: Session, payload: HealthCheckCreate) -> HealthCheckResponse:
    _ensure_unique_row_count(session, payload.datasource_id, payload.check_type)
    record = HealthCheck(
        id=str(uuid.uuid4()),
        datasource_id=payload.datasource_id,
        name=payload.name,
        check_type=payload.check_type,
        config=payload.config,
        enabled=payload.enabled,
        critical=payload.critical,
        created_at=datetime.now(UTC),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return HealthCheckResponse.model_validate(record)


def update_healthcheck(
    session: Session,
    healthcheck_id: str,
    payload: HealthCheckUpdate,
) -> HealthCheckResponse:
    check = session.get(HealthCheck, healthcheck_id)
    if not check:
        raise HealthcheckNotFoundError(healthcheck_id)
    check_type = payload.check_type or check.check_type
    if check_type == 'row_count':
        _ensure_unique_row_count(session, check.datasource_id, check_type, exclude_id=healthcheck_id)
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(check, key, value)
    session.add(check)
    session.commit()
    session.refresh(check)
    return HealthCheckResponse.model_validate(check)


def delete_healthcheck(session: Session, healthcheck_id: str) -> None:
    check = session.get(HealthCheck, healthcheck_id)
    if not check:
        raise HealthcheckNotFoundError(healthcheck_id)
    session.delete(check)
    session.commit()


def list_results(session: Session, datasource_id: str, limit: int = 10) -> list[HealthCheckResultResponse]:
    """Get recent healthcheck results for all checks on a datasource."""
    datasource = session.get(DataSource, datasource_id)
    if not datasource:
        return []
    checks = session.execute(
        select(HealthCheck.id).where(HealthCheck.datasource_id == datasource_id),  # type: ignore[arg-type, call-overload]
    )
    check_ids = checks.scalars().all()
    if not check_ids:
        return []
    results = session.execute(
        select(HealthCheckResult)
        .where(HealthCheckResult.healthcheck_id.in_(check_ids))  # type: ignore[union-attr, attr-defined]
        .order_by(HealthCheckResult.checked_at.desc())  # type: ignore[union-attr, attr-defined]
        .limit(limit),
    )
    return [HealthCheckResultResponse.model_validate(r) for r in results.scalars().all()]


def list_results_for_check(session: Session, healthcheck_id: str, limit: int = 10) -> list[HealthCheckResultResponse]:
    """Get recent results for a single healthcheck."""
    check = session.get(HealthCheck, healthcheck_id)
    if not check:
        return []
    results = session.execute(
        select(HealthCheckResult)
        .where(HealthCheckResult.healthcheck_id == healthcheck_id)  # type: ignore[arg-type]
        .order_by(HealthCheckResult.checked_at.desc())  # type: ignore[union-attr, attr-defined]
        .limit(limit),
    )
    return [HealthCheckResultResponse.model_validate(r) for r in results.scalars().all()]


def _build_expressions(checks: list[HealthCheck], schema_names: set[str]) -> tuple[list[pl.Expr], list[HealthCheck]]:
    """Build Polars aggregation expressions for all valid checks.

    Returns (expressions, valid_checks).  Checks whose referenced column is
    missing from the schema are excluded so the caller can create immediate-
    failure results for them.
    """
    exprs: list[pl.Expr] = []
    valid: list[HealthCheck] = []

    sorted_names = sorted(schema_names)
    row_count_added = False

    for check in checks:
        config = check.config
        if check.check_type == 'row_count':
            valid.append(check)
            if row_count_added:
                continue
            exprs.append(pl.len().alias('row_count__count'))
            row_count_added = True

        elif check.check_type == 'column_null':
            col = str(config.get('column', ''))
            if col not in schema_names:
                continue
            prefix = check.id
            pct = pl.col(col).null_count().cast(pl.Float64) / pl.len().cast(pl.Float64) * 100.0
            exprs.append(pct.alias(f'{prefix}__null_pct'))
            valid.append(check)

        elif check.check_type == 'column_unique':
            col = str(config.get('column', ''))
            if col not in schema_names:
                continue
            prefix = check.id
            exprs.append(pl.col(col).n_unique().alias(f'{prefix}__unique'))
            valid.append(check)

        elif check.check_type == 'column_range':
            col = str(config.get('column', ''))
            if col not in schema_names:
                continue
            prefix = check.id
            exprs.append(pl.col(col).min().alias(f'{prefix}__min'))
            exprs.append(pl.col(col).max().alias(f'{prefix}__max'))
            valid.append(check)

        elif check.check_type == 'column_count':
            valid.append(check)

        elif check.check_type == 'null_percentage':
            threshold = float(config.get('threshold', 0))
            if threshold < 0:
                continue
            if not sorted_names:
                exprs.append(pl.lit(0.0).alias(f'{check.id}__null_pct'))
                valid.append(check)
                continue
            nulls = sum(pl.col(name).null_count().cast(pl.Float64) for name in sorted_names)
            total = pl.len().cast(pl.Float64) * float(len(sorted_names))
            pct = (nulls / total * 100.0).fill_nan(0.0)
            exprs.append(pct.alias(f'{check.id}__null_pct'))
            valid.append(check)

        elif check.check_type == 'duplicate_percentage':
            cols = config.get('columns')
            columns = [str(col) for col in cols] if isinstance(cols, list) else []
            if not columns:
                columns = sorted_names
            if any(col not in schema_names for col in columns):
                continue
            prefix = check.id
            exprs.append(pl.len().alias(f'{prefix}__rows'))
            exprs.append(pl.struct(columns).n_unique().alias(f'{prefix}__unique_rows'))
            valid.append(check)

    return exprs, valid


def _evaluate_row_count(check: HealthCheck, row: pl.DataFrame) -> tuple[bool, str, HealthcheckDetails]:
    config = check.config
    if 'row_count__count' in row.columns:
        count: int = row['row_count__count'][0]
    else:
        count = row[f'{check.id}__count'][0]
    min_rows = config.get('min_rows')
    max_rows = config.get('max_rows')

    passed = True
    messages: list[str] = []
    if min_rows is not None and count < int(min_rows):
        passed = False
        messages.append(f'Too few: {count} < {min_rows}')
    if max_rows is not None and count > int(max_rows):
        passed = False
        messages.append(f'Too many: {count} > {max_rows}')

    message = '; '.join(messages) if messages else f'Row count: {count}'
    details: HealthcheckDetails = {**config, 'actual_count': count}
    return passed, message, details


def _evaluate_column_count(check: HealthCheck, schema_names: set[str]) -> tuple[bool, str, HealthcheckDetails]:
    config = check.config
    count = len(schema_names)
    min_cols = config.get('min_columns')
    max_cols = config.get('max_columns')

    passed = True
    messages: list[str] = []
    if min_cols is not None and count < int(min_cols):
        passed = False
        messages.append(f'Too few: {count} < {min_cols}')
    if max_cols is not None and count > int(max_cols):
        passed = False
        messages.append(f'Too many: {count} > {max_cols}')

    message = '; '.join(messages) if messages else f'Column count: {count}'
    details: HealthcheckDetails = {**config, 'actual_count': count}
    return passed, message, details


def _evaluate_column_null(check: HealthCheck, row: pl.DataFrame) -> tuple[bool, str, HealthcheckDetails]:
    config = check.config
    pct: float = row[f'{check.id}__null_pct'][0]
    threshold = float(config.get('threshold', 0))

    passed = pct <= threshold
    message = f'Nulls: {pct:.1f}% (threshold: {threshold}%)'
    details: HealthcheckDetails = {**config, 'actual_percentage': round(pct, 2)}
    return passed, message, details


def _evaluate_null_percentage(check: HealthCheck, row: pl.DataFrame) -> tuple[bool, str, HealthcheckDetails]:
    config = check.config
    pct: float = row[f'{check.id}__null_pct'][0]
    threshold = float(config.get('threshold', 0))

    passed = pct <= threshold
    message = f'Nulls: {pct:.1f}% (threshold: {threshold}%)'
    details: HealthcheckDetails = {**config, 'actual_percentage': round(pct, 2)}
    return passed, message, details


def _evaluate_column_unique(check: HealthCheck, row: pl.DataFrame) -> tuple[bool, str, HealthcheckDetails]:
    config = check.config
    unique: int = row[f'{check.id}__unique'][0]
    expected_raw = config.get('expected_unique')
    expected = int(expected_raw) if expected_raw is not None else None

    if expected is None:
        passed = True
        message = f'Unique values: {unique}'
    else:
        passed = unique == expected
        message = f'Unique: {unique} (expected: {expected})'

    details: HealthcheckDetails = {**config, 'actual_unique': unique}
    return passed, message, details


def _evaluate_column_range(check: HealthCheck, row: pl.DataFrame) -> tuple[bool, str, HealthcheckDetails]:
    config = check.config
    col_min = row[f'{check.id}__min'][0]
    col_max = row[f'{check.id}__max'][0]
    min_value = config.get('min')
    max_value = config.get('max')

    passed = True
    messages: list[str] = []
    if min_value is not None and col_min < float(min_value):
        passed = False
        messages.append(f'Min {col_min!r} < {min_value}')
    if max_value is not None and col_max > float(max_value):
        passed = False
        messages.append(f'Max {col_max!r} > {max_value}')

    message = '; '.join(messages) if messages else f'Range: [{col_min!r}, {col_max!r}]'
    details: HealthcheckDetails = {**config, 'actual_min': col_min, 'actual_max': col_max}
    return passed, message, details


def _evaluate_duplicate_percentage(check: HealthCheck, row: pl.DataFrame) -> tuple[bool, str, HealthcheckDetails]:
    config = check.config
    total: int = row[f'{check.id}__rows'][0]
    unique: int = row[f'{check.id}__unique_rows'][0]
    threshold = float(config.get('threshold', 0))

    pct = 0.0 if total == 0 else (1 - unique / total) * 100.0

    passed = pct <= threshold
    message = f'Duplicates: {pct:.1f}% (threshold: {threshold}%)'
    details: HealthcheckDetails = {**config, 'actual_percentage': round(pct, 2)}
    return passed, message, details


_EVALUATORS: dict[str, HealthcheckEvaluator] = {
    'row_count': _evaluate_row_count,
    'column_null': _evaluate_column_null,
    'null_percentage': _evaluate_null_percentage,
    'column_unique': _evaluate_column_unique,
    'column_range': _evaluate_column_range,
    'duplicate_percentage': _evaluate_duplicate_percentage,
}


def run_healthchecks(
    session: Session,
    checks: list[HealthCheck],
    lf: pl.LazyFrame,
    *,
    critical_only: bool = False,
) -> list[HealthCheckResult]:
    """Run all health checks in a single LazyFrame evaluation.

    1. Validate referenced columns against the LazyFrame schema.
    2. Build one combined set of Polars aggregation expressions.
    3. Collect once — single materialisation for all checks.
    4. Evaluate each check against the collected scalars.
    5. Persist and return ``HealthCheckResult`` rows.
    """
    selected = checks
    if critical_only:
        selected = [check for check in checks if check.critical]
    if not selected:
        return []

    now = datetime.now(UTC)
    schema_names = set(lf.collect_schema().names())
    exprs, valid_checks = _build_expressions(selected, schema_names)

    valid_ids = {c.id for c in valid_checks}
    results: list[HealthCheckResult] = []
    for check in selected:
        if check.id in valid_ids:
            continue
        col = check.config.get('column', '')
        result = HealthCheckResult(
            id=str(uuid.uuid4()),
            healthcheck_id=check.id,
            passed=False,
            message=f'Column "{col}" not found in dataset',
            details={**check.config, 'error': 'column_not_found'},
            checked_at=now,
        )
        session.add(result)
        results.append(result)

    collected = lf.select(exprs).collect() if exprs else None
    for check in valid_checks:
        evaluator = _EVALUATORS.get(check.check_type)
        if check.check_type == 'column_count':
            passed, message, details = _evaluate_column_count(check, schema_names)
        elif collected is None or not evaluator:
            passed, message, details = False, f'Unknown check type: {check.check_type}', check.config
        else:
            passed, message, details = evaluator(check, collected)

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


def _ensure_unique_row_count(
    session: Session,
    datasource_id: str,
    check_type: str,
    exclude_id: str | None = None,
) -> None:
    if check_type != 'row_count':
        return
    query = select(HealthCheck).where(
        HealthCheck.datasource_id == datasource_id,  # type: ignore[arg-type]
        HealthCheck.check_type == 'row_count',  # type: ignore[arg-type]
    )
    if exclude_id:
        query = query.where(HealthCheck.id != exclude_id)  # type: ignore[arg-type]
    existing = session.execute(query).scalars().first()
    if existing:
        raise HealthcheckValidationError('Only one row_count healthcheck is allowed per datasource')
