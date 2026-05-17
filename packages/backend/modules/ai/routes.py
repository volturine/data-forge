from collections.abc import Callable
from dataclasses import dataclass

from contracts.step_config_enums import AIProvider
from core.ai_clients import get_ai_client, resolve_ai_provider
from pydantic import BaseModel

from backend_core.error_handlers import handle_errors
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix="/ai", tags=["ai"])


@dataclass(frozen=True, slots=True)
class AIProviderStatusDefinition:
    provider: AIProvider
    resolve_status: Callable[[], "AIProviderStatus"]


class AIModelResponse(BaseModel):
    name: str
    detail: str = ""


class AIConnectionResponse(BaseModel):
    ok: bool
    detail: str


class AIProviderRequest(BaseModel):
    provider: str = "ollama"
    endpoint_url: str | None = None
    api_key: str | None = None
    organization_id: str | None = None


class AIProviderStatus(BaseModel):
    provider: str
    configured: bool
    endpoint_url: str
    default_model: str


def resolve_openrouter_status() -> AIProviderStatus:
    from backend_core.settings_store import get_resolved_openrouter_key

    openrouter_key = get_resolved_openrouter_key()
    return AIProviderStatus(
        provider=AIProvider.OPENROUTER.value,
        configured=bool(openrouter_key),
        endpoint_url="https://openrouter.ai/api/v1",
        default_model="",
    )


def resolve_openai_status() -> AIProviderStatus:
    from backend_core.settings_store import get_resolved_openai_settings

    openai = get_resolved_openai_settings()
    return AIProviderStatus(
        provider=AIProvider.OPENAI.value,
        configured=bool(openai["endpoint_url"]),
        endpoint_url=openai["endpoint_url"],
        default_model=openai["default_model"],
    )


def resolve_ollama_status() -> AIProviderStatus:
    from backend_core.settings_store import get_resolved_ollama_settings

    ollama = get_resolved_ollama_settings()
    return AIProviderStatus(
        provider=AIProvider.OLLAMA.value,
        configured=bool(ollama["endpoint_url"]),
        endpoint_url=ollama["endpoint_url"],
        default_model=ollama["default_model"],
    )


def resolve_huggingface_status() -> AIProviderStatus:
    from backend_core.settings_store import get_resolved_huggingface_settings

    huggingface = get_resolved_huggingface_settings()
    return AIProviderStatus(
        provider=AIProvider.HUGGINGFACE.value,
        configured=bool(huggingface["api_token"]),
        endpoint_url="https://api-inference.huggingface.co",
        default_model=huggingface["default_model"],
    )


AI_PROVIDER_STATUS_DEFINITIONS: tuple[AIProviderStatusDefinition, ...] = (
    AIProviderStatusDefinition(AIProvider.OPENROUTER, resolve_openrouter_status),
    AIProviderStatusDefinition(AIProvider.OPENAI, resolve_openai_status),
    AIProviderStatusDefinition(AIProvider.OLLAMA, resolve_ollama_status),
    AIProviderStatusDefinition(AIProvider.HUGGINGFACE, resolve_huggingface_status),
)


@router.post("/providers", response_model=list[AIProviderStatus], mcp=True)
@handle_errors(operation="list ai providers")
def list_providers() -> list[AIProviderStatus]:
    return [definition.resolve_status() for definition in AI_PROVIDER_STATUS_DEFINITIONS]


@router.post("/models", response_model=list[AIModelResponse], mcp=True)
@handle_errors(operation="list ai models", value_error_status=400)
def list_models(body: AIProviderRequest) -> list[AIModelResponse]:
    """List available AI models from the configured provider.

    Returns model names and details. Use provider='ollama' for local models
    or provider='openrouter' with an api_key for cloud models.
    """
    client = get_ai_client(
        resolve_ai_provider(body.provider),
        endpoint_url=body.endpoint_url,
        api_key=body.api_key,
        organization_id=body.organization_id,
    )
    raw = client.list_models()
    return [
        AIModelResponse(
            name=m.get("name", ""),
            detail=str({k: v for k, v in m.items() if k != "name"}),
        )
        for m in raw
    ]


@router.post("/test", response_model=AIConnectionResponse, mcp=True)
@handle_errors(operation="test ai connection", value_error_status=400)
def test_connection(body: AIProviderRequest) -> AIConnectionResponse:
    """Test connectivity to an AI provider.

    Returns {ok: true/false, detail: message}. Use this to verify
    provider/endpoint_url/api_key settings before using AI features.
    """
    client = get_ai_client(
        resolve_ai_provider(body.provider),
        endpoint_url=body.endpoint_url,
        api_key=body.api_key,
        organization_id=body.organization_id,
    )
    result = client.test_connection()
    return AIConnectionResponse(**result)
