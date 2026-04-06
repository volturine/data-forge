# PRD: AI Chat API Support

## Overview

Expand Data-Forge's AI capabilities to support multiple LLM providers for both in-app chat and per-row pipeline transformations. Add support for OpenRouter (remote), OpenAI (local/self-hosted and remote), Ollama (local/self-hosted and remote), and Hugging Face Inference API (remote) as unified AI providers.

## Problem Statement

Data-Forge currently has partial AI integration: Ollama and OpenAI are supported in the AI pipeline operation, and OpenRouter is used for the chat module. However, these integrations are fragmented — each has its own client, configuration, and error handling patterns. Users cannot easily switch providers, there is no unified provider abstraction, and some combinations (e.g., using Ollama for chat, or OpenAI self-hosted for pipeline transforms) are not supported.

### Current State

| Provider | Chat | Pipeline AI Step | Configuration |
|----------|------|-----------------|---------------|
| OpenRouter | ✅ (`chat/openrouter.py`) | ❌ | `AppSettings.openrouter_api_key` |
| OpenAI | ❌ | ✅ (`operations/ai.py`) | Per-step config |
| Ollama | ❌ | ✅ (`operations/ai.py`) | Per-step config |
| Hugging Face | ❌ | ❌ | Not integrated |

### Target State

| Provider | Chat | Pipeline AI Step | Configuration |
|----------|------|-----------------|---------------|
| OpenRouter | ✅ | ✅ | `AppSettings` + per-step override |
| OpenAI (remote) | ✅ | ✅ | `AppSettings` + per-step override |
| OpenAI (local/self-hosted) | ✅ | ✅ | Custom endpoint URL |
| Ollama (local) | ✅ | ✅ | `AppSettings` + per-step override |
| Ollama (remote) | ✅ | ✅ | Custom endpoint URL |
| Hugging Face API | ✅ | ✅ | `AppSettings` + per-step override |

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Unified provider abstraction | Single interface for all providers, both chat and pipeline |
| G-2 | Provider switching without data loss | User can change provider mid-conversation or mid-pipeline |
| G-3 | Self-hosted support for OpenAI-compatible APIs | Custom endpoint URLs work for LocalAI, vLLM, text-gen-webui, etc. |
| G-4 | Per-row LLM transformation at scale | Batch processing with rate limiting, retries, and progress |
| G-5 | In-app chat with any provider | Chat panel works with all 4 provider families |

## Non-Goals

- Building a custom model serving layer (defer to provider APIs)
- Multi-model orchestration (e.g., routing queries to different models)
- Fine-tuning via any provider
- Embedding generation (separate feature)

## User Stories

### US-1: Configure AI Providers Globally

> As a user, I want to configure API keys and endpoints for all AI providers in one place.

**Acceptance Criteria:**

1. Settings page has an "AI Providers" section with expandable panels per provider.
2. Each provider panel shows: API key (password field), endpoint URL (with defaults), default model selector, "Test" button.
3. Provider-specific fields:
   - **OpenRouter**: API key, default model.
   - **OpenAI**: API key, endpoint URL (default: `https://api.openai.com`), default model, organization ID (optional).
   - **Ollama**: Endpoint URL (default: `http://localhost:11434`), default model.
   - **Hugging Face**: API token, default model.
4. Test button validates connectivity and lists available models.
5. Settings persist in `AppSettings` DB record.

### US-2: Use Any Provider for In-App Chat

> As a user, I want to select which AI provider to use for the chat panel, and switch between them.

**Acceptance Criteria:**

1. Chat panel header has a provider/model selector dropdown.
2. Selector shows configured providers with their available models.
3. Switching provider mid-conversation preserves message history.
4. Streaming responses work for all providers that support it.
5. Tool/function calling works for providers that support it (OpenRouter, OpenAI, Ollama with tool-capable models).
6. Error messages clearly identify provider-specific issues.

### US-3: Use Any Provider for Per-Row LLM Transformation

> As a user, I want to use any configured AI provider for the AI pipeline operation step.

**Acceptance Criteria:**

1. AI step config dropdown shows all configured and valid providers.
2. Per-step override: user can specify different endpoint URL, API key, or model for this step.
3. Batch processing with configurable batch size (default 10).
4. Rate limiting per provider (configurable requests per minute).
5. Retry logic with exponential backoff (configurable max retries).
6. Progress tracking: show processed/total rows during execution.
7. Error column: failed rows get error message in a designated column instead of failing the whole step.

### US-4: Self-Hosted OpenAI-Compatible APIs

> As a user, I want to point OpenAI provider to a local/self-hosted endpoint (LocalAI, vLLM, text-generation-webui, LM Studio).

**Acceptance Criteria:**

1. OpenAI provider endpoint URL is editable (not just `api.openai.com`).
2. API key field is optional for local endpoints that don't require auth.
3. Model listing works against custom endpoints (`GET /v1/models`).
4. Chat completions and tool calling work against custom endpoints.
5. Connection test validates the custom endpoint.

### US-5: Remote Ollama Support

> As a user, I want to connect to a remote Ollama instance (not just localhost).

**Acceptance Criteria:**

1. Ollama endpoint URL is editable (default: `http://localhost:11434`).
2. Model listing works against remote Ollama (`GET /api/tags`).
3. Chat and generate work against remote Ollama.
4. Connection test validates the remote endpoint.

## Technical Design

### Backend

#### Unified Provider Abstraction

Create `backend/modules/ai/providers/` with a common interface:

```
modules/ai/providers/
├── __init__.py
├── base.py           # Abstract base: AIProvider
├── openrouter.py     # OpenRouter provider
├── openai_provider.py # OpenAI (local + remote)
├── ollama_provider.py # Ollama (local + remote)
├── huggingface.py    # Hugging Face Inference API
└── factory.py        # Provider factory
```

#### Provider Interface

```python
class AIProvider(ABC):
    """Unified interface for all AI providers."""

    @abstractmethod
    async def chat_completion(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[ToolDefinition] | None = None,
        stream: bool = False,
    ) -> ChatResponse | AsyncIterator[ChatChunk]:
        ...

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> GenerateResponse:
        ...

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        ...

    @abstractmethod
    async def test_connection(self) -> ConnectionTestResult:
        ...
```

#### Provider Factory

```python
def get_provider(
    provider_type: ProviderType,
    endpoint_url: str | None = None,
    api_key: str | None = None,
    **kwargs,
) -> AIProvider:
    """Create provider instance with fallback to AppSettings defaults."""
    match provider_type:
        case "openrouter":
            return OpenRouterProvider(api_key=api_key or settings.openrouter_api_key)
        case "openai":
            return OpenAIProvider(
                api_key=api_key or settings.openai_api_key,
                endpoint_url=endpoint_url or settings.openai_endpoint_url,
            )
        case "ollama":
            return OllamaProvider(
                endpoint_url=endpoint_url or settings.ollama_endpoint_url,
            )
        case "huggingface":
            return HuggingFaceProvider(
                api_token=api_key or settings.hf_api_token,
            )
```

#### Updated AI Pipeline Operation

Refactor `backend/modules/compute/operations/ai.py`:

```python
class AIParams(OperationParams):
    provider: Literal['openrouter', 'openai', 'ollama', 'huggingface'] = 'ollama'
    model: str = 'llama2'
    input_columns: list[str] = []
    output_column: str = 'ai_result'
    error_column: str = 'ai_error'          # NEW: error capture per row
    prompt_template: str = 'Classify: {{text}}'
    batch_size: int = 10
    max_retries: int = 3                     # NEW: retry logic
    rate_limit_rpm: int | None = None        # NEW: rate limiting
    endpoint_url: str | None = None
    api_key: str | None = None
    temperature: float = 0.7                 # NEW: temperature control
    max_tokens: int | None = None            # NEW: token limit
```

#### Updated Chat Module

Refactor `backend/modules/chat/routes.py` to use the unified provider:

```python
@router.post("/chat/messages")
async def send_message(
    request: ChatRequest,
    session: AsyncSession = Depends(get_session),
):
    provider = get_provider(
        provider_type=request.provider,
        endpoint_url=request.endpoint_url,
        api_key=request.api_key,
    )
    # Use provider.chat_completion() with streaming
```

#### API Endpoints (Updated)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/ai/providers` | List configured providers with status |
| `POST` | `/api/v1/ai/models` | List models for a provider (updated) |
| `POST` | `/api/v1/ai/test` | Test provider connectivity (updated) |
| `POST` | `/api/v1/chat/messages` | Send chat message (provider-aware) |

### Frontend

#### Settings Page Updates

- Replace individual provider settings with unified "AI Providers" panel.
- Collapsible sections per provider.
- Each section: enabled toggle, API key, endpoint URL, default model, test button.
- Model selector with live search (queries `POST /ai/models`).

#### Chat Panel Updates

- Add provider/model selector to chat header.
- Show provider icon (Ollama, OpenAI, OpenRouter, HF logos).
- Persist last-used provider/model in session.
- Handle provider-specific streaming differences transparently.

#### AI Step Config Updates

- Provider dropdown with all 4 options + icons.
- Conditional fields per provider (endpoint URL, API key overrides).
- Advanced section: batch size, rate limit, max retries, temperature, max tokens.
- Error column configuration.

### Data Model Changes

Extend `AppSettings`:

```python
# OpenAI
openai_api_key: str = ""
openai_endpoint_url: str = "https://api.openai.com"
openai_default_model: str = ""
openai_organization: str = ""

# Ollama
ollama_endpoint_url: str = "http://localhost:11434"
ollama_default_model: str = ""

# Hugging Face (if not already added via HF Connection PRD)
hf_api_token: str = ""
hf_default_model: str = ""
```

### Security Considerations

- All API keys stored encrypted at rest.
- Per-step API key overrides are transient (not persisted in pipeline definition) — users must use settings for persistent keys.
- Self-hosted endpoint URLs validated for format (must be valid URL).
- Rate limiting enforced server-side to prevent API abuse.
- Streaming responses validated for content safety markers (provider-dependent).

## Migration

- Alembic migration to add new columns to `app_settings`.
- Refactor existing `chat/openrouter.py` to use new provider abstraction (backward compatible).
- Refactor existing `ai/service.py` to use new provider abstraction (backward compatible).
- Existing AI pipeline steps with `provider: 'ollama'` or `provider: 'openai'` continue to work.

## Rollout Plan

| Phase | Scope | Duration |
|-------|-------|----------|
| 1 | Backend: Provider abstraction, factory, interface | 2 days |
| 2 | Backend: OpenRouter + OpenAI providers (migrate existing) | 2 days |
| 3 | Backend: Ollama + HF providers | 2 days |
| 4 | Backend: Updated AI operation with retries, rate limiting, error column | 3 days |
| 5 | Backend: Updated chat with provider selection | 2 days |
| 6 | Frontend: Settings page provider panels | 2 days |
| 7 | Frontend: Chat provider selector, AI step config | 2 days |
| 8 | Testing: All providers, self-hosted, error scenarios | 3 days |

## Open Questions

1. Should we support multiple simultaneous providers in a single pipeline (e.g., use GPT-4 for classification and Ollama for summarization in different steps)?
2. How do we handle provider-specific features (e.g., OpenAI function calling vs. Ollama's different tool format)?
3. Should per-step API key overrides be encrypted in the pipeline definition or must users always use global settings?
4. Do we want a cost tracking/estimation feature for paid providers (OpenRouter, OpenAI, HF)?
