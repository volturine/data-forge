from fastapi import APIRouter, Query
from pydantic import BaseModel

from core.error_handlers import handle_errors
from modules.ai.service import get_ai_client

router = APIRouter(prefix='/ai', tags=['ai'])


class AIModelResponse(BaseModel):
    name: str
    detail: str = ''


class AIConnectionResponse(BaseModel):
    ok: bool
    detail: str


@router.get('/models', response_model=list[AIModelResponse])
@handle_errors(operation='list ai models', value_error_status=400)
def list_models(
    provider: str = Query('ollama'),
    endpoint_url: str | None = Query(None),
    api_key: str | None = Query(None),
) -> list[AIModelResponse]:
    client = get_ai_client(provider, endpoint_url=endpoint_url, api_key=api_key)
    raw = client.list_models()
    return [AIModelResponse(name=m.get('name', ''), detail=str({k: v for k, v in m.items() if k != 'name'})) for m in raw]


@router.get('/test', response_model=AIConnectionResponse)
@handle_errors(operation='test ai connection', value_error_status=400)
def test_connection(
    provider: str = Query('ollama'),
    endpoint_url: str | None = Query(None),
    api_key: str | None = Query(None),
) -> AIConnectionResponse:
    client = get_ai_client(provider, endpoint_url=endpoint_url, api_key=api_key)
    result = client.test_connection()
    return AIConnectionResponse(**result)
