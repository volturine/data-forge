import uuid
from datetime import UTC, datetime

from contracts.datasource.models import DataSource
from contracts.healthcheck_models import HealthCheck, HealthCheckResult, HealthCheckType
from core.exceptions import HealthcheckNotFoundError, HealthcheckValidationError
from sqlalchemy import select
from sqlmodel import Session

from backend_core.healthcheck_schemas import (
    HealthCheckCreate,
    HealthCheckResponse,
    HealthCheckResultResponse,
    HealthCheckUpdate,
)


def list_healthchecks(session: Session, datasource_id: str) -> list[HealthCheckResponse]:
    datasource = session.get(DataSource, datasource_id)
    if not datasource:
        return []
    result = session.execute(select(HealthCheck).where(HealthCheck.datasource_id == datasource_id))  # type: ignore[arg-type]
    checks = result.scalars().all()
    return [HealthCheckResponse.model_validate(check) for check in checks]


def list_all_healthchecks(session: Session) -> list[HealthCheckResponse]:
    result = session.execute(select(HealthCheck))
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
    if HealthCheckType.require(check_type).requires_unique_per_datasource:
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
    datasource = session.get(DataSource, datasource_id)
    if not datasource:
        return []
    query = select(HealthCheckResult).order_by(HealthCheckResult.checked_at.desc()).limit(limit)  # type: ignore[union-attr, attr-defined]
    checks = session.execute(
        select(HealthCheck.id).where(HealthCheck.datasource_id == datasource_id),  # type: ignore[arg-type, call-overload]
    )
    check_ids = checks.scalars().all()
    if not check_ids:
        return []
    results = session.execute(
        query.where(HealthCheckResult.healthcheck_id.in_(check_ids)),  # type: ignore[union-attr, attr-defined]
    )
    return [HealthCheckResultResponse.model_validate(r) for r in results.scalars().all()]


def list_all_results(session: Session, limit: int = 10) -> list[HealthCheckResultResponse]:
    query = select(HealthCheckResult).order_by(HealthCheckResult.checked_at.desc()).limit(limit)  # type: ignore[union-attr, attr-defined]
    results = session.execute(query)
    return [HealthCheckResultResponse.model_validate(r) for r in results.scalars().all()]


def list_results_for_check(session: Session, healthcheck_id: str, limit: int = 10) -> list[HealthCheckResultResponse]:
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


def _ensure_unique_row_count(
    session: Session,
    datasource_id: str,
    check_type: HealthCheckType | str,
    exclude_id: str | None = None,
) -> None:
    if not HealthCheckType.require(check_type).requires_unique_per_datasource:
        return
    query = select(HealthCheck).where(
        HealthCheck.datasource_id == datasource_id,  # type: ignore[arg-type]
        HealthCheck.check_type == HealthCheckType.ROW_COUNT.value,  # type: ignore[arg-type]
    )
    if exclude_id:
        query = query.where(HealthCheck.id != exclude_id)  # type: ignore[arg-type]
    existing = session.execute(query).scalars().first()
    if existing:
        raise HealthcheckValidationError("Only one row_count healthcheck is allowed per datasource")
