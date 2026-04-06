import uuid

from fastapi import Depends
from sqlmodel import Session

from core.database import get_db
from core.error_handlers import handle_errors
from core.exceptions import InvalidIdError
from core.validation import HealthcheckId, parse_datasource_id, parse_healthcheck_id
from modules.healthcheck import schemas, service
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix='/healthchecks', tags=['healthchecks'])


@router.get('', response_model=list[schemas.HealthCheckResponse], mcp=True)
@handle_errors(operation='list healthchecks')
def list_healthchecks(datasource_id: str, session: Session = Depends(get_db)):
    """List all healthchecks for a datasource. Requires datasource_id (from GET /datasource)."""
    return service.list_healthchecks(session, parse_datasource_id(datasource_id))


@router.get('/results', response_model=list[schemas.HealthCheckResultResponse], mcp=True)
@handle_errors(operation='list healthcheck results')
def list_results(datasource_id: str, limit: int = 10, session: Session = Depends(get_db)):
    """List recent healthcheck results for a datasource. Returns the last N results (default 10)."""
    parsed_id = parse_datasource_id(datasource_id)
    try:
        uuid.UUID(parsed_id)
    except ValueError as exc:
        raise InvalidIdError(message='Invalid UUID', details={'value': parsed_id}) from exc
    return service.list_results(session, parsed_id, limit)


@router.post('', response_model=schemas.HealthCheckResponse, mcp=True)
@handle_errors(operation='create healthcheck')
def create_healthcheck(payload: schemas.HealthCheckCreate, session: Session = Depends(get_db)):
    """Create a healthcheck for a datasource.

    Requires: datasource_id, name, check_type (one of: row_count, null_check, schema_check,
    value_range, custom_query), and config (varies by check_type).
    Use GET /datasource to find datasource IDs.
    """
    return service.create_healthcheck(session, payload)


@router.put('/{healthcheck_id}', response_model=schemas.HealthCheckResponse, mcp=True)
@handle_errors(operation='update healthcheck')
def update_healthcheck(
    healthcheck_id: HealthcheckId,
    payload: schemas.HealthCheckUpdate,
    session: Session = Depends(get_db),
):
    """Update a healthcheck's name, config, enabled state, or critical flag. Use GET /healthchecks to find IDs."""
    return service.update_healthcheck(session, parse_healthcheck_id(healthcheck_id), payload)


@router.delete('/{healthcheck_id}', status_code=204, mcp=True)
@handle_errors(operation='delete healthcheck')
def delete_healthcheck(healthcheck_id: HealthcheckId, session: Session = Depends(get_db)):
    """Delete a healthcheck by ID. Use GET /healthchecks?datasource_id=... to find healthcheck IDs."""
    service.delete_healthcheck(session, parse_healthcheck_id(healthcheck_id))
