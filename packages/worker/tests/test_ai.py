"""Tests for AI module: service, handler, routes, step converter."""

from unittest.mock import MagicMock, patch

import polars as pl
import pytest
from pydantic import ValidationError

from operations.ai import AIError, AIHandler, AIParams, InternalAIClient, get_ai_client, parse_request_options
from operations.step_converter import convert_ai_config
from worker_models.step_config_enums import AIProvider

# ---------------------------------------------------------------------------
# parse_request_options
# ---------------------------------------------------------------------------


class TestParseRequestOptions:
    def test_none(self):
        assert parse_request_options(None) is None

    def test_empty_string(self):
        assert parse_request_options("") is None

    def test_whitespace_string(self):
        assert parse_request_options("   ") is None

    def test_valid_json_string(self):
        result = parse_request_options('{"temperature": 0.2}')
        assert result == {"temperature": 0.2}

    def test_dict_passthrough(self):
        d = {"temperature": 0.5, "top_p": 0.9}
        assert parse_request_options(d) is d

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError):
            parse_request_options("{bad json}")

    def test_json_array_raises(self):
        with pytest.raises(ValueError, match="must be a JSON object"):
            parse_request_options("[1, 2, 3]")

    def test_json_string_value_raises(self):
        with pytest.raises(ValueError, match="must be a JSON object"):
            parse_request_options('"hello"')


# ---------------------------------------------------------------------------
# AIParams validation
# ---------------------------------------------------------------------------


class TestAIParams:
    def test_basic_validation(self):
        params = AIParams.model_validate(
            {
                "input_columns": ["text"],
                "output_column": "result",
            },
        )
        assert params.provider == "ollama"
        assert params.model == "llama2"
        assert params.input_columns == ["text"]
        assert params.output_column == "result"
        assert params.batch_size == 10
        assert params.request_options is None

    def test_multi_column_input(self):
        params = AIParams.model_validate(
            {
                "input_columns": ["title", "body"],
                "output_column": "result",
            },
        )
        assert params.input_columns == ["title", "body"]

    def test_no_input_raises(self):
        with pytest.raises(ValidationError, match="input"):
            AIParams.model_validate(
                {
                    "output_column": "result",
                },
            )

    def test_request_options_string_to_dict(self):
        params = AIParams.model_validate(
            {
                "input_columns": ["text"],
                "output_column": "result",
                "request_options": '{"temperature": 0.3}',
            },
        )
        assert params.request_options == {"temperature": 0.3}

    def test_request_options_dict_passthrough(self):
        params = AIParams.model_validate(
            {
                "input_columns": ["text"],
                "output_column": "result",
                "request_options": {"temperature": 0.3},
            },
        )
        assert params.request_options == {"temperature": 0.3}

    def test_request_options_none(self):
        params = AIParams.model_validate(
            {
                "input_columns": ["text"],
                "output_column": "result",
                "request_options": None,
            },
        )
        assert params.request_options is None

    def test_request_options_empty_string(self):
        params = AIParams.model_validate(
            {
                "input_columns": ["text"],
                "output_column": "result",
                "request_options": "",
            },
        )
        assert params.request_options is None

    def test_invalid_provider(self):
        with pytest.raises(ValidationError):
            AIParams.model_validate(
                {
                    "provider": "invalid",
                    "input_columns": ["text"],
                    "output_column": "result",
                },
            )

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            AIParams.model_validate(
                {
                    "input_columns": ["text"],
                    "output_column": "result",
                    "unknown_field": "value",
                },
            )


# ---------------------------------------------------------------------------
# get_ai_client
# ---------------------------------------------------------------------------


class TestGetAIClient:
    def test_ollama_default(self):
        client = get_ai_client("ollama")
        assert isinstance(client, InternalAIClient)

    def test_internal_client_delegates_to_worker_api(self):
        api_client = MagicMock()
        api_client.generate_ai.return_value = ["one", "two"]
        client = InternalAIClient(
            provider=AIProvider.OPENAI,
            endpoint_url="https://custom.api.com",
            api_key="sk-test",
            client=api_client,
        )

        result = client.generate_batch(["p1", "p2"], model="gpt-4o", options={"temperature": 0.2})

        assert result == ["one", "two"]
        api_client.generate_ai.assert_called_once_with(
            provider="openai",
            prompts=["p1", "p2"],
            model="gpt-4o",
            endpoint_url="https://custom.api.com",
            api_key="sk-test",
            options={"temperature": 0.2},
        )

    def test_ollama_custom_url(self):
        client = get_ai_client("ollama", endpoint_url="http://myhost:11434")
        assert isinstance(client, InternalAIClient)

    def test_openai_with_key(self):
        client = get_ai_client("openai", api_key="sk-test")
        assert isinstance(client, InternalAIClient)

    def test_openai_custom_url(self):
        client = get_ai_client("openai", api_key="sk-test", endpoint_url="https://custom.api.com/")
        assert isinstance(client, InternalAIClient)

    def test_huggingface_api_alias_uses_internal_client(self):
        client = get_ai_client("huggingface-api")
        assert isinstance(client, InternalAIClient)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown AI provider"):
            get_ai_client("anthropic")


# ---------------------------------------------------------------------------
# AIHandler
# ---------------------------------------------------------------------------


class TestAIHandler:
    def test_basic_execution(self):
        handler = AIHandler()
        df = pl.DataFrame({"text": ["Hello", "World"]})

        mock_client = MagicMock()
        mock_client.generate_batch.return_value = [
            "classified: Hello",
            "classified: World",
        ]

        with patch("operations.ai.get_ai_client", return_value=mock_client):
            result = handler(
                df.lazy(),
                {
                    "provider": "ollama",
                    "model": "llama2",
                    "input_columns": ["text"],
                    "output_column": "result",
                    "prompt_template": "Classify: {{text}}",
                    "batch_size": 10,
                },
            )
            collected = result.collect()
            assert "result" in collected.columns
            assert collected["result"].to_list() == [
                "classified: Hello",
                "classified: World",
            ]

    def test_lazy_execution_defers_side_effects(self):
        handler = AIHandler()
        df = pl.DataFrame({"text": ["Hello", "World"]})

        mock_client = MagicMock()
        mock_client.generate_batch.return_value = ["ok1", "ok2"]

        with patch("operations.ai.get_ai_client", return_value=mock_client):
            result = handler(
                df.lazy(),
                {
                    "provider": "ollama",
                    "model": "llama2",
                    "input_columns": ["text"],
                    "output_column": "result",
                    "prompt_template": "{{text}}",
                    "batch_size": 10,
                },
            )
            mock_client.generate_batch.assert_not_called()
            result.collect()
            mock_client.generate_batch.assert_called_once()

    def test_empty_dataframe(self):
        handler = AIHandler()
        df = pl.DataFrame({"text": []}).cast({"text": pl.Utf8})

        result = handler(
            df.lazy(),
            {
                "input_columns": ["text"],
                "output_column": "result",
                "prompt_template": "{{text}}",
                "batch_size": 5,
            },
        )
        collected = result.collect()
        assert "result" in collected.columns
        assert len(collected) == 0

    def test_missing_column_raises(self):
        handler = AIHandler()
        df = pl.DataFrame({"name": ["Alice"]})

        with pytest.raises(ValueError, match=r"Input column\(s\) not found"):
            handler(
                df.lazy(),
                {
                    "input_columns": ["text"],
                    "output_column": "result",
                    "prompt_template": "{{text}}",
                    "batch_size": 5,
                },
            )

    def test_batch_size_validation(self):
        handler = AIHandler()
        df = pl.DataFrame({"text": ["Hello"]})

        with pytest.raises(ValueError, match="batch_size must be at least 1"):
            handler(
                df.lazy(),
                {
                    "input_columns": ["text"],
                    "output_column": "result",
                    "prompt_template": "{{text}}",
                    "batch_size": 0,
                },
            )

    def test_error_handling_per_batch(self):
        handler = AIHandler()
        df = pl.DataFrame({"text": ["a", "b", "c", "d"]})

        mock_client = MagicMock()
        mock_client.generate_batch.side_effect = [
            ["ok1", "ok2"],
            AIError("API timeout"),
        ]

        with (
            patch("operations.ai.get_ai_client", return_value=mock_client),
            patch("operations.ai.time.sleep"),
        ):
            result = handler(
                df.lazy(),
                {
                    "input_columns": ["text"],
                    "output_column": "result",
                    "prompt_template": "{{text}}",
                    "batch_size": 2,
                },
            )
            collected = result.collect()
            results = collected["result"].to_list()
            assert results[0] == "ok1"
            assert results[1] == "ok2"
            assert "[error:" in results[2]
            assert "[error:" in results[3]

    def test_batching_respects_size(self):
        handler = AIHandler()
        df = pl.DataFrame({"text": ["a", "b", "c", "d", "e"]})

        mock_client = MagicMock()
        mock_client.generate_batch.side_effect = [
            ["r1", "r2"],
            ["r3", "r4"],
            ["r5"],
        ]

        with patch("operations.ai.get_ai_client", return_value=mock_client):
            result = handler(
                df.lazy(),
                {
                    "input_columns": ["text"],
                    "output_column": "result",
                    "prompt_template": "{{text}}",
                    "batch_size": 2,
                },
            )
            collected = result.collect()
            assert collected["result"].to_list() == ["r1", "r2", "r3", "r4", "r5"]
            assert mock_client.generate_batch.call_count == 3

    def test_prompt_template_substitution(self):
        handler = AIHandler()
        df = pl.DataFrame({"text": ["hello"]})

        mock_client = MagicMock()
        mock_client.generate_batch.return_value = ["result"]

        with patch("operations.ai.get_ai_client", return_value=mock_client):
            result = handler(
                df.lazy(),
                {
                    "input_columns": ["text"],
                    "output_column": "result",
                    "prompt_template": "Analyze: {{text}} now",
                    "batch_size": 10,
                },
            )
            result.collect()
            prompts = mock_client.generate_batch.call_args[0][0]
            assert prompts == ["Analyze: hello now"]

    def test_request_options_passed_to_client(self):
        handler = AIHandler()
        df = pl.DataFrame({"text": ["test"]})

        mock_client = MagicMock()
        mock_client.generate_batch.return_value = ["result"]

        with patch("operations.ai.get_ai_client", return_value=mock_client):
            result = handler(
                df.lazy(),
                {
                    "input_columns": ["text"],
                    "output_column": "result",
                    "prompt_template": "{{text}}",
                    "batch_size": 10,
                    "request_options": '{"temperature": 0.1}',
                },
            )
            result.collect()
            call_kwargs = mock_client.generate_batch.call_args[1]
            assert call_kwargs["options"] == {"temperature": 0.1}

    def test_multi_column_prompt(self):
        handler = AIHandler()
        df = pl.DataFrame({"title": ["Hello"], "body": ["World"]})

        mock_client = MagicMock()
        mock_client.generate_batch.return_value = ["result"]

        with patch("operations.ai.get_ai_client", return_value=mock_client):
            result = handler(
                df.lazy(),
                {
                    "input_columns": ["title", "body"],
                    "output_column": "result",
                    "prompt_template": "Title: {{title}} Body: {{body}}",
                    "batch_size": 10,
                },
            )
            result.collect()
            prompts = mock_client.generate_batch.call_args[0][0]
            assert prompts == ["Title: Hello Body: World"]

    def test_missing_multi_column_raises(self):
        handler = AIHandler()
        df = pl.DataFrame({"title": ["Hello"]})

        with pytest.raises(ValueError, match="Input column"):
            handler(
                df.lazy(),
                {
                    "input_columns": ["title", "body"],
                    "output_column": "result",
                    "prompt_template": "{{title}} {{body}}",
                    "batch_size": 5,
                },
            )


# ---------------------------------------------------------------------------
# convert_ai_config (step converter)
# ---------------------------------------------------------------------------


class TestConvertAIConfig:
    def test_basic_conversion(self):
        config = {
            "provider": "openai",
            "model": "gpt-4o",
            "input_columns": ["text"],
            "output_column": "result",
            "prompt_template": "Classify: {{text}}",
            "batch_size": 5,
            "endpoint_url": "https://api.openai.com",
            "api_key": "sk-test",
            "request_options": '{"temperature": 0.2}',
        }
        result = convert_ai_config(config)
        assert result["provider"] == "openai"
        assert result["model"] == "gpt-4o"
        assert result["input_columns"] == ["text"]
        assert result["output_column"] == "result"
        assert result["batch_size"] == 5
        assert result["request_options"] == '{"temperature": 0.2}'

    def test_camelcase_fields_are_ignored(self):
        config = {
            "inputColumn": "text",
            "outputColumn": "result",
            "promptTemplate": "Hello {{text}}",
            "requestOptions": '{"temperature": 0.5}',
        }
        result = convert_ai_config(config)
        assert result["input_columns"] == []
        assert result["output_column"] == "ai_result"
        assert result["prompt_template"] == "Classify this text: {{text}}"
        assert result["request_options"] is None

    def test_multi_column_conversion(self):
        config = {
            "input_columns": ["title", "body"],
            "output_column": "result",
            "prompt_template": "Title: {{title}} Body: {{body}}",
        }
        result = convert_ai_config(config)
        assert result["input_columns"] == ["title", "body"]

    def test_input_columns_preserved_when_present(self):
        config = {
            "input_columns": ["title", "body"],
            "output_column": "result",
        }
        result = convert_ai_config(config)
        assert result["input_columns"] == ["title", "body"]

    def test_empty_request_options(self):
        config = {
            "input_columns": ["text"],
            "output_column": "result",
            "request_options": "",
        }
        result = convert_ai_config(config)
        assert result["request_options"] is None

    def test_defaults(self):
        result = convert_ai_config({})
        assert result["provider"] == "ollama"
        assert result["model"] == "llama2"
        assert result["output_column"] == "ai_result"
        assert result["batch_size"] == 10

    def test_none_request_options(self):
        config = {"input_columns": ["text"], "request_options": None}
        result = convert_ai_config(config)
        assert result["request_options"] is None
