from pydantic import BaseModel

from core.error_handlers import handle_errors
from modules.ai.service import get_ai_client
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix='/ai', tags=['ai'])


class AIModelResponse(BaseModel):
    name: str
    detail: str = ''


class AIConnectionResponse(BaseModel):
    ok: bool
    detail: str


class AIProviderRequest(BaseModel):
    provider: str = 'ollama'
    endpoint_url: str | None = None
    api_key: str | None = None


@router.post('/models', response_model=list[AIModelResponse], mcp=True)
@handle_errors(operation='list ai models', value_error_status=400)
def list_models(body: AIProviderRequest) -> list[AIModelResponse]:
    """List available AI models from the configured provider.

    Returns model names and details. Use provider='ollama' for local models
    or provider='openrouter' with an api_key for cloud models.
    """
    client = get_ai_client(body.provider, endpoint_url=body.endpoint_url, api_key=body.api_key)
    raw = client.list_models()
    return [AIModelResponse(name=m.get('name', ''), detail=str({k: v for k, v in m.items() if k != 'name'})) for m in raw]


@router.post('/test', response_model=AIConnectionResponse, mcp=True)
@handle_errors(operation='test ai connection', value_error_status=400)
def test_connection(body: AIProviderRequest) -> AIConnectionResponse:
    """Test connectivity to an AI provider.

    Returns {ok: true/false, detail: message}. Use this to verify
    provider/endpoint_url/api_key settings before using AI features.
    """
    client = get_ai_client(body.provider, endpoint_url=body.endpoint_url, api_key=body.api_key)
    result = client.test_connection()
    return AIConnectionResponse(**result)
