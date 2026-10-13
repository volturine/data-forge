import pytest

from backend_core import ai_clients
from dataforge_protocol import enums_pb2


def test_get_ai_client_ollama_prefers_request_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        'backend_core.settings_projection.get_resolved_ollama_settings',
        lambda: {'endpoint_url': 'http://saved.example', 'default_model': 'saved-model'},
    )

    client = ai_clients.get_ai_client(
        enums_pb2.AI_PROVIDER_OLLAMA,
        endpoint_url='http://request.example',
        organization_id='unused',
    )

    assert isinstance(client, ai_clients.OllamaClient)
    assert client.base_url == 'http://request.example'


def test_get_ai_client_ollama_uses_saved_endpoint_before_deployment_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_clients.settings, 'ollama_base_url', 'http://deployment.example')
    monkeypatch.setattr(
        'backend_core.settings_projection.get_resolved_ollama_settings',
        lambda: {'endpoint_url': 'http://saved.example', 'default_model': 'saved-model'},
    )

    client = ai_clients.get_ai_client('ollama')

    assert isinstance(client, ai_clients.OllamaClient)
    assert client.base_url == 'http://saved.example'


def test_get_ai_client_ollama_uses_deployment_endpoint_when_saved_endpoint_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_clients.settings, 'ollama_base_url', 'http://deployment.example')
    monkeypatch.setattr(
        'backend_core.settings_projection.get_resolved_ollama_settings',
        lambda: {'endpoint_url': '', 'default_model': 'saved-model'},
    )

    client = ai_clients.get_ai_client('ollama')

    assert isinstance(client, ai_clients.OllamaClient)
    assert client.base_url == 'http://deployment.example'


def test_get_ai_client_openrouter_prefers_request_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('backend_core.settings_projection.get_resolved_openrouter_key', lambda: 'saved-key')

    client = ai_clients.get_ai_client('openrouter', api_key='request-key')

    assert isinstance(client, ai_clients.OpenRouterClient)
    assert client.api_key == 'request-key'


def test_get_ai_client_openrouter_uses_saved_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('backend_core.settings_projection.get_resolved_openrouter_key', lambda: 'saved-key')

    client = ai_clients.get_ai_client(enums_pb2.AI_PROVIDER_OPENROUTER)

    assert isinstance(client, ai_clients.OpenRouterClient)
    assert client.api_key == 'saved-key'


def test_get_ai_client_openrouter_requires_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('backend_core.settings_projection.get_resolved_openrouter_key', lambda: '')

    with pytest.raises(ValueError, match='OPENROUTER_API_KEY not configured'):
        ai_clients.get_ai_client('openrouter')


def test_get_ai_client_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match='Unknown AI provider'):
        ai_clients.get_ai_client('openai')
