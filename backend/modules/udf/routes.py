from fastapi import Depends, HTTPException, Query
from sqlmodel import Session

from core.database import get_db
from core.validation import UdfId, parse_udf_id
from modules.auth.dependencies import get_optional_user
from modules.auth.models import User
from modules.mcp.router import MCPRouter
from modules.udf import schemas, service

router = MCPRouter(prefix='/udf', tags=['udf'])


@router.get('', response_model=list[schemas.UdfResponseSchema], mcp=True)
def list_udfs(
    q: str | None = Query(default=None),
    dtype_key: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    session: Session = Depends(get_db),
):
    """List user-defined functions. Optional filters: q (name search), dtype_key (input dtype), tag."""
    return service.list_udfs(session, query=q, dtype_key=dtype_key, tag=tag)


@router.post('', response_model=schemas.UdfResponseSchema, mcp=True)
def create_udf(
    data: schemas.UdfCreateSchema,
    session: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Create a new user-defined function.

    Requires: name, code (Python expression using Polars), signature (input dtypes and output dtype).
    Use GET /udf to see existing UDFs. Use GET /analysis/step-types to see how UDFs are used in pipelines.
    """
    try:
        owner_id = user.id if user else None
        return service.create_udf(session, data, owner_id=owner_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get('/match', response_model=list[schemas.UdfResponseSchema], mcp=True)
def match_udfs(
    dtypes: list[str] = Query(default=[]),
    session: Session = Depends(get_db),
):
    """Find UDFs compatible with given column dtypes. Pass dtypes as query params (e.g., ?dtypes=Int64&dtypes=Utf8)."""
    return service.match_udfs(session, dtypes)


@router.get('/export', response_model=schemas.UdfExportSchema, mcp=True)
def export_udfs(session: Session = Depends(get_db)):
    """Export all UDFs as a JSON bundle for backup or transfer between environments."""
    udfs = service.export_udfs(session)
    return schemas.UdfExportSchema(udfs=udfs)


@router.post('/import', response_model=list[schemas.UdfResponseSchema], mcp=True)
def import_udfs(
    data: schemas.UdfImportSchema,
    session: Session = Depends(get_db),
):
    """Import UDFs from an export bundle. Existing UDFs with matching names are skipped."""
    try:
        return service.import_udfs(session, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get('/{udf_id}', response_model=schemas.UdfResponseSchema, mcp=True)
def get_udf(udf_id: UdfId, session: Session = Depends(get_db)):
    """Get a single UDF by ID. Use GET /udf to find UDF IDs."""
    try:
        return service.get_udf(session, parse_udf_id(udf_id))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put('/{udf_id}', response_model=schemas.UdfResponseSchema, mcp=True)
def update_udf(
    udf_id: UdfId,
    data: schemas.UdfUpdateSchema,
    session: Session = Depends(get_db),
):
    """Update a UDF's name, code, signature, description, or tags. Use GET /udf/{id} to see current values."""
    try:
        return service.update_udf(session, parse_udf_id(udf_id), data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post('/{udf_id}/clone', response_model=schemas.UdfResponseSchema, mcp=True)
def clone_udf(
    udf_id: UdfId,
    data: schemas.UdfCloneSchema,
    session: Session = Depends(get_db),
):
    """Clone a UDF with a new name. The clone is independent of the original."""
    try:
        return service.clone_udf(session, parse_udf_id(udf_id), data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete('/{udf_id}', status_code=204, mcp=True)
def delete_udf(udf_id: UdfId, session: Session = Depends(get_db)):
    """Delete a UDF by ID. This will not affect analyses that reference the UDF by name in their step configs."""
    try:
        udf_id_value = parse_udf_id(udf_id)
        service.delete_udf(session, udf_id_value)
        return None
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
