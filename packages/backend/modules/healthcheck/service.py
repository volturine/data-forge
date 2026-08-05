import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlmodel import Session

from backend_core.domain.healthcheck_models import HealthCheckType
from backend_core.exceptions import HealthcheckValidationError, healthcheck_not_found
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.healthchecks.models import HealthCheck, HealthCheckResult
from backend_core.sqlmodel_typing import col, sa
from modules.healthcheck.schemas import (
    HealthCheckCreate,
    HealthCheckResponse,
    HealthCheckResultResponse,
    HealthCheckUpdate,
)


def list_healthchecks(
    session: Session,
    datasource_id: str,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[HealthCheckResponse]:
    datasource = session.get(DataSource, datasource_id)
    if not datasource:
        return []
    query = (
        select(HealthCheck).join(DataSource, sa(HealthCheck.datasource_id == DataSource.id), isouter=True).where(sa(HealthCheck.datasource_id == datasource_id))
    )
    if search:
        q = f'%{search}%'
        query = query.where(
            or_(
                col(HealthCheck.id).ilike(q),
                col(HealthCheck.name).ilike(q),
                col(HealthCheck.check_type).ilike(q),
                col(DataSource.name).ilike(q),
            )
        )
    query = query.order_by(col(HealthCheck.created_at).desc(), col(HealthCheck.id).asc()).limit(limit).offset(offset)
    checks = session.execute(query).scalars().all()
    return [HealthCheckResponse.model_validate(check) for check in checks]


def list_all_healthchecks(
    session: Session,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[HealthCheckResponse]:
    query = select(HealthCheck).join(DataSource, sa(HealthCheck.datasource_id == DataSource.id), isouter=True)
    if search:
        q = f'%{search}%'
        query = query.where(
            or_(
                col(HealthCheck.id).ilike(q),
                col(HealthCheck.name).ilike(q),
                col(HealthCheck.check_type).ilike(q),
                col(DataSource.name).ilike(q),
            )
        )
    query = query.order_by(col(HealthCheck.created_at).desc(), col(HealthCheck.id).asc()).limit(limit).offset(offset)
    checks = session.execute(query).scalars().all()
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
        raise healthcheck_not_found(healthcheck_id)
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
        raise healthcheck_not_found(healthcheck_id)
    session.delete(check)
    session.commit()


def list_results(session: Session, datasource_id: str, limit: int = 10) -> list[HealthCheckResultResponse]:
    datasource = session.get(DataSource, datasource_id)
    if not datasource:
        return []
    query = select(HealthCheckResult).order_by(col(HealthCheckResult.checked_at).desc(), col(HealthCheckResult.id).asc()).limit(limit)
    checks = session.execute(
        select(col(HealthCheck.id)).where(col(HealthCheck.datasource_id) == datasource_id),
    )
    check_ids = checks.scalars().all()
    if not check_ids:
        return []
    results = session.execute(
        query.where(col(HealthCheckResult.healthcheck_id).in_(check_ids)),
    )
    return [HealthCheckResultResponse.model_validate(r) for r in results.scalars().all()]


def list_all_results(session: Session, limit: int = 10) -> list[HealthCheckResultResponse]:
    query = select(HealthCheckResult).order_by(col(HealthCheckResult.checked_at).desc(), col(HealthCheckResult.id).asc()).limit(limit)
    results = session.execute(query)
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
        sa(HealthCheck.datasource_id == datasource_id),
        sa(HealthCheck.check_type == HealthCheckType.ROW_COUNT.value),
    )
    if exclude_id:
        query = query.where(sa(HealthCheck.id != exclude_id))
    existing = session.execute(query).scalars().first()
    if existing:
        raise HealthcheckValidationError('Only one row_count healthcheck is allowed per datasource')
