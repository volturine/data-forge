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


def _check_column_null_percentage(lf: pl.LazyFrame, column: str, threshold: float) -> tuple[bool, str]:
    df = lf.select(pl.col(column)).collect()
    total = df.height
    if total == 0:
        return True, 'No rows to evaluate'
    nulls = df[column].null_count()
    percentage = (nulls / total) * 100
    passed = percentage <= threshold
    return passed, f'Nulls: {percentage:.1f}% (threshold: {threshold}%)'


def _check_column_unique(lf: pl.LazyFrame, column: str, expected_unique: int | None) -> tuple[bool, str]:
    df = lf.select(pl.col(column)).collect()
    unique_count = df[column].n_unique()
    if expected_unique is None:
        return True, f'Unique values: {unique_count}'
    passed = unique_count == expected_unique
    return passed, f'Unique: {unique_count} (expected: {expected_unique})'


def _check_column_range(
    lf: pl.LazyFrame,
    column: str,
    min_value: float | None,
    max_value: float | None,
) -> tuple[bool, str]:
    df = lf.select(pl.col(column)).collect()
    if df.height == 0:
        return True, 'No rows to evaluate'
    col_min = df[column].min()
    col_max = df[column].max()
    passed = True
    messages: list[str] = []
    if min_value is not None and col_min < min_value:  # type: ignore[operator]
        passed = False
        messages.append(f'Min {col_min!r} < {min_value}')
    if max_value is not None and col_max > max_value:  # type: ignore[operator]
        passed = False
        messages.append(f'Max {col_max!r} > {max_value}')
    if messages:
        return passed, '; '.join(messages)
    return True, f'Range: [{col_min!r}, {col_max!r}]'


def _check_row_count(lf: pl.LazyFrame, min_rows: int | None, max_rows: int | None) -> tuple[bool, str]:
    count = lf.collect().height
    passed = True
    messages: list[str] = []
    if min_rows is not None and count < min_rows:
        passed = False
        messages.append(f'Too few: {count} < {min_rows}')
    if max_rows is not None and count > max_rows:
        passed = False
        messages.append(f'Too many: {count} > {max_rows}')
    if messages:
        return passed, '; '.join(messages)
    return True, f'Row count: {count}'


def run_healthcheck(session: Session, check: HealthCheck, lf: pl.LazyFrame) -> HealthCheckResult:
    config = check.config
    if check.check_type == 'column_null':
        passed, message = _check_column_null_percentage(
            lf,
            str(config.get('column')),
            float(config.get('threshold', 0)),
        )
    elif check.check_type == 'column_unique':
        expected_unique = config.get('expected_unique')
        expected = int(expected_unique) if expected_unique is not None else None
        passed, message = _check_column_unique(
            lf,
            str(config.get('column')),
            expected,
        )
    elif check.check_type == 'column_range':
        min_value = config.get('min')
        max_value = config.get('max')
        min_val = float(min_value) if min_value is not None else None
        max_val = float(max_value) if max_value is not None else None
        passed, message = _check_column_range(
            lf,
            str(config.get('column')),
            min_val,
            max_val,
        )
    elif check.check_type == 'row_count':
        min_rows = config.get('min_rows')
        max_rows = config.get('max_rows')
        min_val = int(min_rows) if min_rows is not None else None
        max_val = int(max_rows) if max_rows is not None else None
        passed, message = _check_row_count(lf, min_val, max_val)
    else:
        raise ValueError(f'Unknown check type: {check.check_type}')

    result = HealthCheckResult(
        id=str(uuid.uuid4()),
        healthcheck_id=check.id,
        passed=passed,
        message=message,
        details=config,
        checked_at=datetime.now(UTC),
    )
    session.add(result)
    session.commit()
    session.refresh(result)
    return result
