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
    organization_id: str | None = None


class AIProviderStatus(BaseModel):
    provider: str
    configured: bool
    endpoint_url: str
    default_model: str


@router.post('/providers', response_model=list[AIProviderStatus], mcp=True)
@handle_errors(operation='list ai providers')
def list_providers() -> list[AIProviderStatus]:
    from modules.settings.service import (
        get_resolved_huggingface_settings,
        get_resolved_ollama_settings,
        get_resolved_openai_settings,
        get_resolved_openrouter_key,
    )

    openai = get_resolved_openai_settings()
    ollama = get_resolved_ollama_settings()
    huggingface = get_resolved_huggingface_settings()
    openrouter_key = get_resolved_openrouter_key()

    return [
        AIProviderStatus(
            provider='openrouter',
            configured=bool(openrouter_key),
            endpoint_url='https://openrouter.ai/api/v1',
            default_model='',
        ),
        AIProviderStatus(
            provider='openai',
            configured=bool(openai['endpoint_url']),
            endpoint_url=openai['endpoint_url'],
            default_model=openai['default_model'],
        ),
        AIProviderStatus(
            provider='ollama',
            configured=bool(ollama['endpoint_url']),
            endpoint_url=ollama['endpoint_url'],
            default_model=ollama['default_model'],
        ),
        AIProviderStatus(
            provider='huggingface',
            configured=bool(huggingface['api_token']),
            endpoint_url='https://api-inference.huggingface.co',
            default_model=huggingface['default_model'],
        ),
    ]


@router.post('/models', response_model=list[AIModelResponse], mcp=True)
@handle_errors(operation='list ai models', value_error_status=400)
def list_models(body: AIProviderRequest) -> list[AIModelResponse]:
    """List available AI models from the configured provider.

    Returns model names and details. Use provider='ollama' for local models
    or provider='openrouter' with an api_key for cloud models.
    """
    client = get_ai_client(
        body.provider,
        endpoint_url=body.endpoint_url,
        api_key=body.api_key,
        organization_id=body.organization_id,
    )
    raw = client.list_models()
    return [AIModelResponse(name=m.get('name', ''), detail=str({k: v for k, v in m.items() if k != 'name'})) for m in raw]


@router.post('/test', response_model=AIConnectionResponse, mcp=True)
@handle_errors(operation='test ai connection', value_error_status=400)
def test_connection(body: AIProviderRequest) -> AIConnectionResponse:
    """Test connectivity to an AI provider.

    Returns {ok: true/false, detail: message}. Use this to verify
    provider/endpoint_url/api_key settings before using AI features.
    """
    client = get_ai_client(
        body.provider,
        endpoint_url=body.endpoint_url,
        api_key=body.api_key,
        organization_id=body.organization_id,
    )
    result = client.test_connection()
    return AIConnectionResponse(**result)
