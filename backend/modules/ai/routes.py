from fastapi import APIRouter, Query
from pydantic import BaseModel

from core.error_handlers import handle_errors
from modules.ai.service import get_ai_client
from modules.mcp.decorators import deterministic_tool

router = APIRouter(prefix='/ai', tags=['ai'])


class AIModelResponse(BaseModel):
    name: str
    detail: str = ''


class AIConnectionResponse(BaseModel):
    ok: bool
    detail: str


@router.get('/models', response_model=list[AIModelResponse])
@handle_errors(operation='list ai models', value_error_status=400)
@deterministic_tool
def list_models(
    provider: str = Query('ollama'),
    endpoint_url: str | None = Query(None),
    api_key: str | None = Query(None),
) -> list[AIModelResponse]:
    """List available AI models from the configured provider.

    Returns model names and details. Use provider='ollama' for local models
    or provider='openrouter' with an api_key for cloud models.
    """
    client = get_ai_client(provider, endpoint_url=endpoint_url, api_key=api_key)
    raw = client.list_models()
    return [AIModelResponse(name=m.get('name', ''), detail=str({k: v for k, v in m.items() if k != 'name'})) for m in raw]


@router.get('/test', response_model=AIConnectionResponse)
@handle_errors(operation='test ai connection', value_error_status=400)
@deterministic_tool
def test_connection(
    provider: str = Query('ollama'),
    endpoint_url: str | None = Query(None),
    api_key: str | None = Query(None),
) -> AIConnectionResponse:
    """Test connectivity to an AI provider.

    Returns {ok: true/false, detail: message}. Use this to verify
    provider/endpoint_url/api_key settings before using AI features.
    """
    client = get_ai_client(provider, endpoint_url=endpoint_url, api_key=api_key)
    result = client.test_connection()
    return AIConnectionResponse(**result)
