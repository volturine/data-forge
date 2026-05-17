import pytest

from modules.analysis import service


def test_requested_generation_provider_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown AI provider"):
        service._resolved_generation_provider("anthropic")


def test_requested_generation_provider_uses_requested_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "get_resolved_openrouter_key", lambda: "sk-or")

    provider, model, kwargs = service._resolved_generation_provider("openrouter")

    assert provider == "openrouter"
    assert model == ""
    assert kwargs == {"api_key": "sk-or"}


def test_default_generation_provider_follows_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "get_resolved_openrouter_key", lambda: "")
    monkeypatch.setattr(
        service,
        "get_resolved_openai_settings",
        lambda: {
            "api_key": "",
            "endpoint_url": "https://api.openai.example",
            "default_model": "gpt-test",
            "organization_id": "org-test",
        },
    )
    monkeypatch.setattr(
        service,
        "get_resolved_ollama_settings",
        lambda: {"endpoint_url": "http://ollama.local", "default_model": "llama-test"},
    )
    monkeypatch.setattr(
        service,
        "get_resolved_huggingface_settings",
        lambda: {"api_token": "hf-test", "default_model": "hf-model"},
    )

    provider, model, kwargs = service._resolved_generation_provider()

    assert provider == "ollama"
    assert model == "llama-test"
    assert kwargs == {"endpoint_url": "http://ollama.local"}
