from fastapi import APIRouter, Request

from modules.logs.schemas import ClientLogBatch
from modules.logs.service import save_client_logs

router = APIRouter(prefix='/logs', tags=['logs'])


@router.post('/client')
async def ingest_client_logs(batch: ClientLogBatch, request: Request):
    client_id = request.headers.get('x-client-id')
    session_id = request.headers.get('x-client-session')
    items = [
        log.model_copy(update={'client_id': log.client_id or client_id, 'session_id': log.session_id or session_id}) for log in batch.logs
    ]
    total = save_client_logs(items)
    return {'accepted': total}
