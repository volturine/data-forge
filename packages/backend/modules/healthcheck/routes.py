import uuid

from core.database import get_db
from core.exceptions import InvalidIdError
from fastapi import Depends
from sqlmodel import Session

from backend_core import healthcheck_schemas as schemas
from backend_core.error_handlers import handle_errors
from backend_core.validation import (
    HealthcheckId,
    parse_datasource_id,
    parse_healthcheck_id,
)
from modules.healthcheck import service
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix="/healthchecks", tags=["healthchecks"])


@router.get("", response_model=list[schemas.HealthCheckResponse], mcp=True)
@handle_errors(operation="list healthchecks")
async def list_healthchecks(datasource_id: str, session: Session = Depends(get_db)):
    """List healthchecks for a datasource."""
    return [schemas.HealthCheckResponse.model_validate(item) for item in service.list_healthchecks(session, parse_datasource_id(datasource_id))]


@router.get("/all", response_model=list[schemas.HealthCheckResponse], mcp=True)
@handle_errors(operation="list all healthchecks")
async def list_all_healthchecks(session: Session = Depends(get_db)):
    """List healthchecks across all datasources."""
    return [schemas.HealthCheckResponse.model_validate(item) for item in service.list_all_healthchecks(session)]


@router.get("/results", response_model=list[schemas.HealthCheckResultResponse], mcp=True)
@handle_errors(operation="list healthcheck results")
async def list_results(datasource_id: str, limit: int = 10, session: Session = Depends(get_db)):
    """List recent healthcheck results for a datasource."""
    parsed_id = parse_datasource_id(datasource_id)
    try:
        uuid.UUID(parsed_id)
    except ValueError as exc:
        raise InvalidIdError(message="Invalid UUID", details={"value": parsed_id}) from exc
    return [schemas.HealthCheckResultResponse.model_validate(item) for item in service.list_results(session, parsed_id, limit)]


@router.get("/results/all", response_model=list[schemas.HealthCheckResultResponse], mcp=True)
@handle_errors(operation="list all healthcheck results")
async def list_all_results(limit: int = 10, session: Session = Depends(get_db)):
    """List recent healthcheck results across all datasources."""
    return [schemas.HealthCheckResultResponse.model_validate(item) for item in service.list_all_results(session, limit)]


@router.post("", response_model=schemas.HealthCheckResponse, mcp=True)
@handle_errors(operation="create healthcheck")
async def create_healthcheck(payload: schemas.HealthCheckCreate, session: Session = Depends(get_db)):
    """Create a healthcheck for a datasource.

    Requires: datasource_id, name, check_type (one of: row_count, column_null, column_unique,
    column_range, column_count, null_percentage, duplicate_percentage), and config (varies by check_type).
    Use GET /datasource to find datasource IDs.
    """
    created = service.create_healthcheck(
        session,
        service.HealthCheckCreate.model_validate(payload.model_dump()),
    )
    return schemas.HealthCheckResponse.model_validate(created)


@router.put("/{healthcheck_id}", response_model=schemas.HealthCheckResponse, mcp=True)
@handle_errors(operation="update healthcheck")
async def update_healthcheck(
    healthcheck_id: HealthcheckId,
    payload: schemas.HealthCheckUpdate,
    session: Session = Depends(get_db),
):
    """Update a healthcheck's name, config, enabled state, or critical flag. Use GET /healthchecks?datasource_id=... to find IDs."""
    updated = service.update_healthcheck(
        session,
        parse_healthcheck_id(healthcheck_id),
        service.HealthCheckUpdate.model_validate(payload.model_dump(exclude_none=True)),
    )
    return schemas.HealthCheckResponse.model_validate(updated)


@router.delete("/{healthcheck_id}", status_code=204, mcp=True)
@handle_errors(operation="delete healthcheck")
async def delete_healthcheck(healthcheck_id: HealthcheckId, session: Session = Depends(get_db)):
    """Delete a healthcheck by ID. Use GET /healthchecks?datasource_id=... to find healthcheck IDs."""
    service.delete_healthcheck(session, parse_healthcheck_id(healthcheck_id))
