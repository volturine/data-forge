import uuid

from fastapi import Depends

from backend_core.api_execution_budget import run_api_blocking
from backend_core.database import run_db
from backend_core.error_handlers import handle_errors
from backend_core.exceptions import InvalidIdError
from backend_core.validation import (
    HealthcheckId,
    parse_datasource_id,
    parse_healthcheck_id,
)
from modules.auth.dependencies import get_current_user
from modules.healthcheck import schemas, service
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix='/healthchecks', tags=['healthchecks'], dependencies=[Depends(get_current_user)])


@router.get('', response_model=list[schemas.HealthCheckResponse], mcp=True)
@handle_errors(operation='list healthchecks')
async def list_healthchecks(
    datasource_id: str,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """List healthchecks for a datasource. Supports text search and pagination."""
    return [
        schemas.HealthCheckResponse.model_validate(item)
        for item in await run_api_blocking(
            run_db,
            service.list_healthchecks,
            parse_datasource_id(datasource_id),
            search=search,
            limit=limit,
            offset=offset,
        )
    ]


@router.get('/all', response_model=list[schemas.HealthCheckResponse], mcp=True)
@handle_errors(operation='list all healthchecks')
async def list_all_healthchecks(
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """List healthchecks across all datasources. Supports text search and pagination."""
    items = await run_api_blocking(run_db, service.list_all_healthchecks, search=search, limit=limit, offset=offset)
    return [schemas.HealthCheckResponse.model_validate(item) for item in items]


@router.get('/results', response_model=list[schemas.HealthCheckResultResponse], mcp=True)
@handle_errors(operation='list healthcheck results')
async def list_results(datasource_id: str, limit: int = 10):
    """List recent healthcheck results for a datasource."""
    parsed_id = parse_datasource_id(datasource_id)
    try:
        uuid.UUID(parsed_id)
    except ValueError as exc:
        raise InvalidIdError(message='Invalid UUID', details={'value': parsed_id}) from exc
    items = await run_api_blocking(run_db, service.list_results, parsed_id, limit)
    return [schemas.HealthCheckResultResponse.model_validate(item) for item in items]


@router.get('/results/all', response_model=list[schemas.HealthCheckResultResponse], mcp=True)
@handle_errors(operation='list all healthcheck results')
async def list_all_results(limit: int = 10):
    """List recent healthcheck results across all datasources."""
    items = await run_api_blocking(run_db, service.list_all_results, limit)
    return [schemas.HealthCheckResultResponse.model_validate(item) for item in items]


@router.post('', response_model=schemas.HealthCheckResponse, mcp=True)
@handle_errors(operation='create healthcheck')
async def create_healthcheck(payload: schemas.HealthCheckCreate):
    """Create a healthcheck for a datasource.

    Requires: datasource_id, name, check_type (one of: row_count, column_null, column_unique,
    column_range, column_count, null_percentage, duplicate_percentage), and config (varies by check_type).
    Use GET /datasource to find datasource IDs.
    """
    created = await run_api_blocking(
        run_db,
        service.create_healthcheck,
        service.HealthCheckCreate.model_validate(payload.model_dump()),
    )
    return schemas.HealthCheckResponse.model_validate(created)


@router.put('/{healthcheck_id}', response_model=schemas.HealthCheckResponse, mcp=True)
@handle_errors(operation='update healthcheck')
async def update_healthcheck(
    healthcheck_id: HealthcheckId,
    payload: schemas.HealthCheckUpdate,
):
    """Update a healthcheck's name, config, enabled state, or critical flag. Use GET /healthchecks?datasource_id=... to find IDs."""
    updated = await run_api_blocking(
        run_db,
        service.update_healthcheck,
        parse_healthcheck_id(healthcheck_id),
        service.HealthCheckUpdate.model_validate(payload.model_dump(exclude_none=True)),
    )
    return schemas.HealthCheckResponse.model_validate(updated)


@router.delete('/{healthcheck_id}', status_code=204, mcp=True)
@handle_errors(operation='delete healthcheck')
async def delete_healthcheck(healthcheck_id: HealthcheckId):
    """Delete a healthcheck by ID. Use GET /healthchecks?datasource_id=... to find healthcheck IDs."""
    await run_api_blocking(run_db, service.delete_healthcheck, parse_healthcheck_id(healthcheck_id))
