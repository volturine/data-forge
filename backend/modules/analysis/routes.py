from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlmodel import Session

from core.database import get_db
from core.error_handlers import handle_errors
from core.validation import AnalysisId, DataSourceId, parse_analysis_id, parse_datasource_id
from modules.analysis import schemas, service
from modules.compute import service as compute_service
from modules.locks import service as lock_service

router = APIRouter(prefix='/analysis', tags=['analysis'])


@router.post('', response_model=schemas.AnalysisResponseSchema)
@handle_errors(operation='create analysis', value_error_status=400)
def create_analysis(
    data: schemas.AnalysisCreateSchema,
    session: Session = Depends(get_db),
):
    return service.create_analysis(session, data)


@router.get('', response_model=list[schemas.AnalysisGalleryItemSchema])
@handle_errors(operation='list analyses')
def list_analyses(session: Session = Depends(get_db)):
    return service.list_analyses(session)


@router.get('/{analysis_id}', response_model=schemas.AnalysisResponseSchema)
@handle_errors(operation='get analysis', value_error_status=404)
def get_analysis(
    analysis_id: AnalysisId,
    response: Response,
    session: Session = Depends(get_db),
):
    analysis = service.get_analysis(session, parse_analysis_id(analysis_id))
    response.headers['ETag'] = f'"analysis-{analysis.id}-{analysis.updated_at.isoformat()}"'
    response.headers['X-Analysis-Version'] = analysis.updated_at.isoformat()
    return analysis


@router.put('/{analysis_id}', response_model=schemas.AnalysisResponseSchema)
@handle_errors(operation='update analysis', value_error_status=409)
def update_analysis(
    analysis_id: AnalysisId,
    data: schemas.AnalysisUpdateSchema,
    session: Session = Depends(get_db),
):
    analysis_id_value = parse_analysis_id(analysis_id)
    try:
        service.get_analysis(session, analysis_id_value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not data.client_id or not data.lock_token:
        raise HTTPException(status_code=409, detail='Editing lock required')

    lock_service.validate_lock(session, analysis_id_value, data.client_id, data.lock_token)

    return service.update_analysis(session, analysis_id_value, data)


@router.delete('/{analysis_id}', status_code=204)
@handle_errors(operation='delete analysis', value_error_status=404)
def delete_analysis(
    analysis_id: AnalysisId,
    session: Session = Depends(get_db),
):
    analysis_id_value = parse_analysis_id(analysis_id)
    try:
        service.delete_analysis(session, analysis_id_value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return None


@router.post('/{analysis_id}/datasource/{datasource_id}')
@handle_errors(operation='link datasource', value_error_status=400)
def link_datasource(
    analysis_id: AnalysisId,
    datasource_id: DataSourceId,
    session: Session = Depends(get_db),
):
    analysis_id_value = parse_analysis_id(analysis_id)
    datasource_id_value = parse_datasource_id(datasource_id)
    service.link_datasource(session, analysis_id_value, datasource_id_value)
    return {'message': f'DataSource {datasource_id_value} linked to Analysis {analysis_id_value}'}


@router.post('/{analysis_id}/execute')
@handle_errors(operation='execute analysis', value_error_status=400)
async def execute_analysis(
    analysis_id: AnalysisId,
    request: Request,
    analysis_tab_id: str | None = None,
    session: Session = Depends(get_db),
):
    analysis_payload = None
    body = None
    try:
        body = await request.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        analysis_payload = body.get('pipeline')

    analysis_id_value = parse_analysis_id(analysis_id)

    if not isinstance(analysis_payload, dict):
        raise HTTPException(status_code=400, detail='pipeline payload must be provided')

    tabs = analysis_payload.get('tabs', [])
    if not isinstance(tabs, list):
        raise HTTPException(status_code=400, detail='pipeline tabs must be a list')
    if analysis_tab_id:
        selected = next((tab for tab in tabs if tab.get('id') == analysis_tab_id), None)
    else:
        selected = next((tab for tab in tabs if tab.get('steps')), None)
    if not selected:
        selected = tabs[0] if tabs else None
    if not selected:
        raise HTTPException(status_code=400, detail='pipeline payload missing tabs')
    datasource_id = selected.get('datasource_id')
    pipeline_steps = selected.get('steps', [])
    if not datasource_id:
        raise HTTPException(status_code=400, detail='Analysis tab missing datasource_id')
    if not isinstance(pipeline_steps, list):
        raise HTTPException(status_code=400, detail='Analysis tab steps must be a list')
    config = selected.get('datasource_config') or {}
    if config and not isinstance(config, dict):
        raise HTTPException(status_code=400, detail='Analysis tab datasource_config must be a dict')
    next_config = {**config}
    payload_id = analysis_payload.get('analysis_id')
    payload_id = str(payload_id) if payload_id is not None else None
    if payload_id and payload_id == analysis_id_value:
        next_config['analysis_pipeline'] = analysis_payload

    preview = compute_service.preview_step(
        session=session,
        target_step_id=pipeline_steps[-1]['id'] if pipeline_steps else 'source',
        row_limit=50,
        page=1,
        analysis_id=analysis_id_value,
        datasource_config=next_config,
        analysis_pipeline=analysis_payload,
        tab_id=analysis_tab_id,
    )

    return {
        'schema': preview.column_types,
        'rows': preview.data,
        'row_count': preview.total_rows,
    }


@router.delete('/{analysis_id}/datasources/{datasource_id}', status_code=204)
@handle_errors(operation='unlink datasource', value_error_status=400)
def unlink_datasource(
    analysis_id: AnalysisId,
    datasource_id: DataSourceId,
    session: Session = Depends(get_db),
):
    service.unlink_datasource(session, parse_analysis_id(analysis_id), parse_datasource_id(datasource_id))
    return None
