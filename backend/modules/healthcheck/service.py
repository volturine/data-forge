import uuid
from datetime import UTC, datetime

import polars as pl
from sqlalchemy import select
from sqlmodel import Session

from modules.healthcheck.models import HealthCheck, HealthCheckResult
from modules.healthcheck.schemas import HealthCheckCreate, HealthCheckResponse, HealthCheckResultResponse, HealthCheckUpdate


def list_healthchecks(session: Session, datasource_id: str) -> list[HealthCheckResponse]:
    result = session.execute(select(HealthCheck).where(HealthCheck.datasource_id == datasource_id))  # type: ignore[arg-type]
    checks = result.scalars().all()
    return [HealthCheckResponse.model_validate(check) for check in checks]


def create_healthcheck(session: Session, payload: HealthCheckCreate) -> HealthCheckResponse:
    record = HealthCheck(
        id=str(uuid.uuid4()),
        datasource_id=payload.datasource_id,
        name=payload.name,
        check_type=payload.check_type,
        config=payload.config,
        enabled=payload.enabled,
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
        raise ValueError('Healthcheck not found')
    update_data = payload.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(check, key, value)
    session.add(check)
    session.commit()
    session.refresh(check)
    return HealthCheckResponse.model_validate(check)


def delete_healthcheck(session: Session, healthcheck_id: str) -> None:
    check = session.get(HealthCheck, healthcheck_id)
    if not check:
        raise ValueError('Healthcheck not found')
    session.delete(check)
    session.commit()


def list_results(session: Session, datasource_id: str, limit: int = 10) -> list[HealthCheckResultResponse]:
    """Get recent healthcheck results for all checks on a datasource."""
    checks = session.execute(
        select(HealthCheck.id).where(HealthCheck.datasource_id == datasource_id)  # type: ignore[arg-type, call-overload]
    )
    check_ids = [row[0] for row in checks.all()]
    if not check_ids:
        return []
    results = session.execute(
        select(HealthCheckResult)
        .where(HealthCheckResult.healthcheck_id.in_(check_ids))  # type: ignore[union-attr, attr-defined]
        .order_by(HealthCheckResult.checked_at.desc())  # type: ignore[union-attr, attr-defined]
        .limit(limit)
    )
    return [HealthCheckResultResponse.model_validate(r) for r in results.scalars().all()]


def list_results_for_check(session: Session, healthcheck_id: str, limit: int = 10) -> list[HealthCheckResultResponse]:
    """Get recent results for a single healthcheck."""
    results = session.execute(
        select(HealthCheckResult)
        .where(HealthCheckResult.healthcheck_id == healthcheck_id)  # type: ignore[arg-type]
        .order_by(HealthCheckResult.checked_at.desc())  # type: ignore[union-attr, attr-defined]
        .limit(limit)
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

    for check in checks:
        config = check.config
        prefix = check.id

        if check.check_type == 'row_count':
            exprs.append(pl.len().alias(f'{prefix}__count'))
            valid.append(check)

        elif check.check_type == 'column_null':
            col = str(config.get('column', ''))
            if col not in schema_names:
                continue
            pct = pl.col(col).null_count().cast(pl.Float64) / pl.len().cast(pl.Float64) * 100.0
            exprs.append(pct.alias(f'{prefix}__null_pct'))
            valid.append(check)

        elif check.check_type == 'column_unique':
            col = str(config.get('column', ''))
            if col not in schema_names:
                continue
            exprs.append(pl.col(col).n_unique().alias(f'{prefix}__unique'))
            valid.append(check)

        elif check.check_type == 'column_range':
            col = str(config.get('column', ''))
            if col not in schema_names:
                continue
            exprs.append(pl.col(col).min().alias(f'{prefix}__min'))
            exprs.append(pl.col(col).max().alias(f'{prefix}__max'))
            valid.append(check)

    return exprs, valid


def _evaluate_row_count(check: HealthCheck, row: pl.DataFrame) -> tuple[bool, str, dict]:
    config = check.config
    count: int = row[f'{check.id}__count'][0]
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
    details = {**config, 'actual_count': count}
    return passed, message, details


def _evaluate_column_null(check: HealthCheck, row: pl.DataFrame) -> tuple[bool, str, dict]:
    config = check.config
    pct: float = row[f'{check.id}__null_pct'][0]
    threshold = float(config.get('threshold', 0))

    passed = pct <= threshold
    message = f'Nulls: {pct:.1f}% (threshold: {threshold}%)'
    details = {**config, 'actual_percentage': round(pct, 2)}
    return passed, message, details


def _evaluate_column_unique(check: HealthCheck, row: pl.DataFrame) -> tuple[bool, str, dict]:
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

    details = {**config, 'actual_unique': unique}
    return passed, message, details


def _evaluate_column_range(check: HealthCheck, row: pl.DataFrame) -> tuple[bool, str, dict]:
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
    details = {**config, 'actual_min': col_min, 'actual_max': col_max}
    return passed, message, details


_EVALUATORS: dict[str, object] = {
    'row_count': _evaluate_row_count,
    'column_null': _evaluate_column_null,
    'column_unique': _evaluate_column_unique,
    'column_range': _evaluate_column_range,
}


def run_healthchecks(
    session: Session,
    checks: list[HealthCheck],
    lf: pl.LazyFrame,
) -> list[HealthCheckResult]:
    """Run all health checks in a single LazyFrame evaluation.

    1. Validate referenced columns against the LazyFrame schema.
    2. Build one combined set of Polars aggregation expressions.
    3. Collect once — single materialisation for all checks.
    4. Evaluate each check against the collected scalars.
    5. Persist and return ``HealthCheckResult`` rows.
    """
    if not checks:
        return []

    now = datetime.now(UTC)
    schema_names = set(lf.collect_schema().names())
    exprs, valid_checks = _build_expressions(checks, schema_names)

    valid_ids = {c.id for c in valid_checks}
    results: list[HealthCheckResult] = []
    for check in checks:
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

    if exprs:
        collected = lf.select(exprs).collect()
        for check in valid_checks:
            evaluator = _EVALUATORS.get(check.check_type)
            if not evaluator:
                passed, message, details = False, f'Unknown check type: {check.check_type}', check.config
            else:
                passed, message, details = evaluator(check, collected)  # type: ignore[operator]

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
