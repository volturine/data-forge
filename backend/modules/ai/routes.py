from fastapi import APIRouter, Query
from pydantic import BaseModel

from modules.ai.service import get_ai_client

router = APIRouter(prefix='/ai', tags=['ai'])


class AIModelResponse(BaseModel):
    name: str
    detail: str = ''


class AIConnectionResponse(BaseModel):
    ok: bool
    detail: str


@router.get('/models', response_model=list[AIModelResponse])
def list_models(
    provider: str = Query('ollama'),
    endpoint_url: str | None = Query(None),
    api_key: str | None = Query(None),
) -> list[AIModelResponse]:
    """List available models from the configured AI provider."""
    try:
        client = get_ai_client(provider, endpoint_url=endpoint_url, api_key=api_key)
    except ValueError as exc:
        return [AIModelResponse(name='', detail=str(exc))]
    raw = client.list_models()
    return [AIModelResponse(name=m.get('name', ''), detail=str({k: v for k, v in m.items() if k != 'name'})) for m in raw]


@router.get('/test', response_model=AIConnectionResponse)
def test_connection(
    provider: str = Query('ollama'),
    endpoint_url: str | None = Query(None),
    api_key: str | None = Query(None),
) -> AIConnectionResponse:
    """Test connectivity to the AI provider."""
    try:
        client = get_ai_client(provider, endpoint_url=endpoint_url, api_key=api_key)
    except ValueError as exc:
        return AIConnectionResponse(ok=False, detail=str(exc))
    result = client.test_connection()
    return AIConnectionResponse(**result)
