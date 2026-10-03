from fastapi import Depends, Query

from backend_core.api_execution_budget import run_api_blocking
from backend_core.database import run_db
from backend_core.error_handlers import handle_errors
from backend_core.validation import UdfId, parse_udf_id
from modules.auth.dependencies import get_current_user
from modules.auth.models import User
from modules.mcp.router import MCPRouter
from modules.udf import schemas, service

router = MCPRouter(prefix='/udf', tags=['udf'])


@router.get('', response_model=list[schemas.UdfResponseSchema], mcp=True)
@handle_errors(operation='list UDFs')
async def list_udfs(
    q: str | None = Query(default=None),
    dtype_key: str | None = Query(default=None),
    tag: str | None = Query(default=None),
):
    """List user-defined functions. Optional filters: q (name search), dtype_key (input dtype), tag."""
    return await run_api_blocking(run_db, service.list_udfs, query=q, dtype_key=dtype_key, tag=tag)


@router.post('', response_model=schemas.UdfResponseSchema, mcp=True)
@handle_errors(operation='create UDF')
async def create_udf(
    data: schemas.UdfCreateSchema,
    user: User | None = Depends(get_current_user),
):
    """Create a new user-defined function.

    Requires: name, code (Python expression using Polars), signature (input dtypes and output dtype).
    Use GET /udf to see existing UDFs. Use GET /analysis/step-types to see how UDFs are used in pipelines.
    """
    owner_id = user.id if user else None
    return await run_api_blocking(run_db, service.create_udf, data, owner_id=owner_id)


@router.get('/match', response_model=list[schemas.UdfResponseSchema], mcp=True)
@handle_errors(operation='match UDFs')
async def match_udfs(
    dtypes: list[str] = Query(default=[]),
):
    """Find UDFs compatible with given column dtypes. Pass dtypes as query params (e.g., ?dtypes=Int64&dtypes=Utf8)."""
    return await run_api_blocking(run_db, service.match_udfs, dtypes)


@router.get('/export', response_model=schemas.UdfExportSchema, mcp=True)
@handle_errors(operation='export UDFs')
async def export_udfs():
    """Export all UDFs as a JSON bundle for backup or transfer between environments."""
    udfs = await run_api_blocking(run_db, service.export_udfs)
    return schemas.UdfExportSchema(udfs=udfs)


@router.post('/import', response_model=list[schemas.UdfResponseSchema], mcp=True)
@handle_errors(operation='import UDFs')
async def import_udfs(
    data: schemas.UdfImportSchema,
):
    """Import UDFs from an export bundle. Existing UDFs with matching names are skipped."""
    return await run_api_blocking(run_db, service.import_udfs, data)


@router.get('/{udf_id}', response_model=schemas.UdfResponseSchema, mcp=True)
@handle_errors(operation='get UDF')
async def get_udf(udf_id: UdfId):
    """Get a single UDF by ID. Use GET /udf to find UDF IDs."""
    return await run_api_blocking(run_db, service.get_udf, parse_udf_id(udf_id))


@router.put('/{udf_id}', response_model=schemas.UdfResponseSchema, mcp=True)
@handle_errors(operation='update UDF')
async def update_udf(
    udf_id: UdfId,
    data: schemas.UdfUpdateSchema,
):
    """Update a UDF's name, code, signature, description, or tags. Use GET /udf/{id} to see current values."""
    return await run_api_blocking(run_db, service.update_udf, parse_udf_id(udf_id), data)


@router.post('/{udf_id}/clone', response_model=schemas.UdfResponseSchema, mcp=True)
@handle_errors(operation='clone UDF')
async def clone_udf(
    udf_id: UdfId,
    data: schemas.UdfCloneSchema,
):
    """Clone a UDF with a new name. The clone is independent of the original."""
    return await run_api_blocking(run_db, service.clone_udf, parse_udf_id(udf_id), data)


@router.delete('/{udf_id}', status_code=204, mcp=True)
@handle_errors(operation='delete UDF')
async def delete_udf(udf_id: UdfId):
    """Delete a UDF by ID. This will not affect analyses that reference the UDF by name in their step configs."""
    await run_api_blocking(run_db, service.delete_udf, parse_udf_id(udf_id))
