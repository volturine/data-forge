from unittest.mock import MagicMock, patch


class TestAIRoutes:
    def test_list_models_ollama(self, client):
        mock_models = [{"name": "llama2", "size": 3800000000}]
        with patch("modules.ai.routes.get_ai_client") as mock_get:
            mock_client = MagicMock()
            mock_client.list_models.return_value = mock_models
            mock_get.return_value = mock_client
            response = client.post("/api/v1/ai/models", json={"provider": "ollama"})
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["name"] == "llama2"

    def test_list_models_invalid_provider(self, client):
        response = client.post("/api/v1/ai/models", json={"provider": "bad"})
        assert response.status_code == 400
        data = response.json()
        assert "Unknown AI provider" in data["detail"]

    def test_list_providers_returns_ordered_statuses(self, client):
        response = client.post("/api/v1/ai/providers", json={})
        assert response.status_code == 200
        data = response.json()
        assert [entry["provider"] for entry in data] == [
            "openrouter",
            "openai",
            "ollama",
            "huggingface",
        ]

    def test_test_connection_success(self, client):
        with patch("modules.ai.routes.get_ai_client") as mock_get:
            mock_client = MagicMock()
            mock_client.test_connection.return_value = {
                "ok": True,
                "detail": "3 model(s) available",
            }
            mock_get.return_value = mock_client
            response = client.post("/api/v1/ai/test", json={"provider": "ollama"})
            assert response.status_code == 200
            assert response.json()["ok"] is True

    def test_test_connection_failure(self, client):
        with patch("modules.ai.routes.get_ai_client") as mock_get:
            mock_client = MagicMock()
            mock_client.test_connection.return_value = {
                "ok": False,
                "detail": "Connection refused",
            }
            mock_get.return_value = mock_client
            response = client.post("/api/v1/ai/test", json={"provider": "ollama"})
            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is False
            assert "Connection refused" in data["detail"]

    def test_test_connection_no_key(self, client):
        with patch(
            "modules.ai.routes.get_ai_client",
            side_effect=ValueError("OPENAI_API_KEY not configured"),
        ):
            response = client.post("/api/v1/ai/test", json={"provider": "openai"})
            assert response.status_code == 400
            assert "OPENAI_API_KEY" in response.json()["detail"]
