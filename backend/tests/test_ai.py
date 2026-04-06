"""Tests for AI module: service, handler, routes, step converter."""

from unittest.mock import MagicMock, patch

import polars as pl
import pytest
from pydantic import ValidationError

from modules.ai.service import (
    AIError,
    OllamaClient,
    OpenAIClient,
    get_ai_client,
    parse_request_options,
)
from modules.compute.operations.ai import AIHandler, AIParams
from modules.compute.step_converter import convert_ai_config

# ---------------------------------------------------------------------------
# parse_request_options
# ---------------------------------------------------------------------------


class TestParseRequestOptions:
    def test_none(self):
        assert parse_request_options(None) is None

    def test_empty_string(self):
        assert parse_request_options('') is None

    def test_whitespace_string(self):
        assert parse_request_options('   ') is None

    def test_valid_json_string(self):
        result = parse_request_options('{"temperature": 0.2}')
        assert result == {'temperature': 0.2}

    def test_dict_passthrough(self):
        d = {'temperature': 0.5, 'top_p': 0.9}
        assert parse_request_options(d) is d

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match='Invalid JSON'):
            parse_request_options('{bad json}')

    def test_json_array_raises(self):
        with pytest.raises(ValueError, match='must be a JSON object'):
            parse_request_options('[1, 2, 3]')

    def test_json_string_value_raises(self):
        with pytest.raises(ValueError, match='must be a JSON object'):
            parse_request_options('"hello"')


# ---------------------------------------------------------------------------
# AIParams validation
# ---------------------------------------------------------------------------


class TestAIParams:
    def test_basic_validation(self):
        params = AIParams.model_validate(
            {
                'input_column': 'text',
                'output_column': 'result',
            },
        )
        assert params.provider == 'ollama'
        assert params.model == 'llama2'
        assert params.input_columns == ['text']
        assert params.input_column is None  # legacy field cleared
        assert params.output_column == 'result'
        assert params.batch_size == 10
        assert params.request_options is None

    def test_multi_column_input(self):
        params = AIParams.model_validate(
            {
                'input_columns': ['title', 'body'],
                'output_column': 'result',
            },
        )
        assert params.input_columns == ['title', 'body']

    def test_legacy_input_column_promoted(self):
        params = AIParams.model_validate(
            {
                'input_column': 'text',
                'output_column': 'result',
            },
        )
        assert params.input_columns == ['text']
        assert params.input_column is None

    def test_no_input_raises(self):
        with pytest.raises(ValidationError, match='input'):
            AIParams.model_validate(
                {
                    'output_column': 'result',
                },
            )

    def test_request_options_string_to_dict(self):
        params = AIParams.model_validate(
            {
                'input_column': 'text',
                'output_column': 'result',
                'request_options': '{"temperature": 0.3}',
            },
        )
        assert params.request_options == {'temperature': 0.3}

    def test_request_options_dict_passthrough(self):
        params = AIParams.model_validate(
            {
                'input_column': 'text',
                'output_column': 'result',
                'request_options': {'temperature': 0.3},
            },
        )
        assert params.request_options == {'temperature': 0.3}

    def test_request_options_none(self):
        params = AIParams.model_validate(
            {
                'input_column': 'text',
                'output_column': 'result',
                'request_options': None,
            },
        )
        assert params.request_options is None

    def test_request_options_empty_string(self):
        params = AIParams.model_validate(
            {
                'input_column': 'text',
                'output_column': 'result',
                'request_options': '',
            },
        )
        assert params.request_options is None

    def test_invalid_provider(self):
        with pytest.raises(ValidationError):
            AIParams.model_validate(
                {
                    'provider': 'invalid',
                    'input_column': 'text',
                    'output_column': 'result',
                },
            )

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            AIParams.model_validate(
                {
                    'input_column': 'text',
                    'output_column': 'result',
                    'unknown_field': 'value',
                },
            )


# ---------------------------------------------------------------------------
# get_ai_client
# ---------------------------------------------------------------------------


class TestGetAIClient:
    def test_ollama_default(self):
        client = get_ai_client('ollama')
        assert isinstance(client, OllamaClient)

    def test_ollama_custom_url(self):
        client = get_ai_client('ollama', endpoint_url='http://myhost:11434')
        assert isinstance(client, OllamaClient)
        assert client.base_url == 'http://myhost:11434'

    def test_openai_with_key(self):
        client = get_ai_client('openai', api_key='sk-test')
        assert isinstance(client, OpenAIClient)
        assert client.api_key == 'sk-test'

    def test_openai_custom_url(self):
        client = get_ai_client('openai', api_key='sk-test', endpoint_url='https://custom.api.com/')
        assert isinstance(client, OpenAIClient)
        assert client.base_url == 'https://custom.api.com'

    def test_openai_no_key_raises(self):
        with patch('modules.ai.service.settings') as mock_settings:
            mock_settings.openai_api_key = ''
            with pytest.raises(ValueError, match='OPENAI_API_KEY'):
                get_ai_client('openai')

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match='Unknown AI provider'):
            get_ai_client('anthropic')


# ---------------------------------------------------------------------------
# OllamaClient
# ---------------------------------------------------------------------------


class TestOllamaClient:
    def test_generate_calls_api(self):
        client = OllamaClient('http://localhost:11434')
        mock_response = MagicMock()
        mock_response.json.return_value = {'response': 'Hello world'}
        mock_response.raise_for_status = MagicMock()

        with patch('modules.ai.service._retry_request', return_value=mock_response) as mock_req:
            result = client.generate('Say hello', model='llama2')
            assert result == 'Hello world'
            mock_req.assert_called_once_with(
                'POST',
                'http://localhost:11434/api/generate',
                payload={'model': 'llama2', 'prompt': 'Say hello', 'stream': False},
            )

    def test_generate_with_options(self):
        client = OllamaClient('http://localhost:11434')
        mock_response = MagicMock()
        mock_response.json.return_value = {'response': 'result'}
        mock_response.raise_for_status = MagicMock()

        with patch('modules.ai.service._retry_request', return_value=mock_response) as mock_req:
            client.generate('prompt', model='llama2', options={'temperature': 0.1})
            call_payload = mock_req.call_args[1]['payload']
            assert call_payload['options'] == {'temperature': 0.1}

    def test_generate_empty_response(self):
        client = OllamaClient('http://localhost:11434')
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_response.raise_for_status = MagicMock()

        with patch('modules.ai.service._retry_request', return_value=mock_response):
            result = client.generate('prompt', model='llama2')
            assert result == ''

    def test_list_models(self):
        client = OllamaClient('http://localhost:11434')
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'models': [
                {'name': 'llama2', 'size': 3800000000},
                {'name': 'mistral', 'size': 4100000000},
            ],
        }
        mock_response.raise_for_status = MagicMock()

        with patch('modules.ai.service._retry_request', return_value=mock_response):
            models = client.list_models()
            assert len(models) == 2
            assert models[0]['name'] == 'llama2'
            assert models[1]['name'] == 'mistral'

    def test_list_models_error_returns_empty(self):
        client = OllamaClient('http://localhost:11434')
        with patch('modules.ai.service._retry_request', side_effect=AIError('connection failed')):
            models = client.list_models()
            assert models == []

    def test_test_connection_success(self):
        client = OllamaClient('http://localhost:11434')
        mock_response = MagicMock()
        mock_response.json.return_value = {'models': [{'name': 'llama2'}]}
        mock_response.raise_for_status = MagicMock()

        with patch('modules.ai.service.http_client.get', return_value=mock_response):
            result = client.test_connection()
            assert result['ok'] is True
            assert '1 model(s)' in result['detail']

    def test_test_connection_failure(self):
        client = OllamaClient('http://localhost:11434')
        with patch('modules.ai.service.http_client.get', side_effect=ConnectionError('refused')):
            result = client.test_connection()
            assert result['ok'] is False


# ---------------------------------------------------------------------------
# OpenAIClient
# ---------------------------------------------------------------------------


class TestOpenAIClient:
    def test_generate_calls_api(self):
        client = OpenAIClient('sk-test')
        mock_response = MagicMock()
        mock_response.json.return_value = {'choices': [{'message': {'content': 'AI response'}}]}
        mock_response.raise_for_status = MagicMock()

        with patch('modules.ai.service._retry_request', return_value=mock_response) as mock_req:
            result = client.generate('Hello', model='gpt-4o')
            assert result == 'AI response'
            call_args = mock_req.call_args
            assert call_args[0][0] == 'POST'
            assert '/v1/chat/completions' in call_args[0][1]
            assert call_args[1]['headers']['Authorization'] == 'Bearer sk-test'

    def test_generate_with_options(self):
        client = OpenAIClient('sk-test')
        mock_response = MagicMock()
        mock_response.json.return_value = {'choices': [{'message': {'content': 'result'}}]}
        mock_response.raise_for_status = MagicMock()

        with patch('modules.ai.service._retry_request', return_value=mock_response) as mock_req:
            client.generate('prompt', model='gpt-4o', options={'temperature': 0.5})
            call_payload = mock_req.call_args[1]['payload']
            assert call_payload['temperature'] == 0.5

    def test_generate_empty_choices(self):
        client = OpenAIClient('sk-test')
        mock_response = MagicMock()
        mock_response.json.return_value = {'choices': []}
        mock_response.raise_for_status = MagicMock()

        with patch('modules.ai.service._retry_request', return_value=mock_response):
            result = client.generate('prompt', model='gpt-4o')
            assert result == ''

    def test_list_models(self):
        client = OpenAIClient('sk-test')
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'data': [
                {'id': 'gpt-4o', 'owned_by': 'openai'},
                {'id': 'gpt-3.5-turbo', 'owned_by': 'openai'},
            ],
        }
        mock_response.raise_for_status = MagicMock()

        with patch('modules.ai.service._retry_request', return_value=mock_response):
            models = client.list_models()
            assert len(models) == 2
            assert models[0]['name'] == 'gpt-4o'

    def test_list_models_error_returns_empty(self):
        client = OpenAIClient('sk-test')
        with patch('modules.ai.service._retry_request', side_effect=AIError('auth failed')):
            models = client.list_models()
            assert models == []

    def test_custom_base_url(self):
        client = OpenAIClient('sk-test', base_url='https://custom.ai/')
        assert client.base_url == 'https://custom.ai'

    def test_test_connection_success(self):
        client = OpenAIClient('sk-test')
        mock_response = MagicMock()
        mock_response.json.return_value = {'data': [{'id': 'gpt-4o'}]}
        mock_response.raise_for_status = MagicMock()

        with patch('modules.ai.service.http_client.get', return_value=mock_response):
            result = client.test_connection()
            assert result['ok'] is True

    def test_test_connection_failure(self):
        client = OpenAIClient('sk-test')
        with patch('modules.ai.service.http_client.get', side_effect=Exception('timeout')):
            result = client.test_connection()
            assert result['ok'] is False


# ---------------------------------------------------------------------------
# AIClient.generate_batch
# ---------------------------------------------------------------------------


class TestAIClientBatch:
    def test_generate_batch_delegates(self):
        client = OllamaClient('http://localhost:11434')
        responses = ['resp1', 'resp2', 'resp3']

        with patch.object(client, 'generate', side_effect=responses):
            results = client.generate_batch(
                ['prompt1', 'prompt2', 'prompt3'],
                model='llama2',
            )
            assert results == ['resp1', 'resp2', 'resp3']


# ---------------------------------------------------------------------------
# AIHandler
# ---------------------------------------------------------------------------


class TestAIHandler:
    def test_basic_execution(self):
        handler = AIHandler()
        df = pl.DataFrame({'text': ['Hello', 'World']})

        mock_client = MagicMock()
        mock_client.generate_batch.return_value = ['classified: Hello', 'classified: World']

        with patch('modules.compute.operations.ai.get_ai_client', return_value=mock_client):
            result = handler(
                df.lazy(),
                {
                    'provider': 'ollama',
                    'model': 'llama2',
                    'input_column': 'text',
                    'output_column': 'result',
                    'prompt_template': 'Classify: {{text}}',
                    'batch_size': 10,
                },
            )
            collected = result.collect()
            assert 'result' in collected.columns
            assert collected['result'].to_list() == ['classified: Hello', 'classified: World']

    def test_lazy_execution_defers_side_effects(self):
        handler = AIHandler()
        df = pl.DataFrame({'text': ['Hello', 'World']})

        mock_client = MagicMock()
        mock_client.generate_batch.return_value = ['ok1', 'ok2']

        with patch('modules.compute.operations.ai.get_ai_client', return_value=mock_client):
            result = handler(
                df.lazy(),
                {
                    'provider': 'ollama',
                    'model': 'llama2',
                    'input_column': 'text',
                    'output_column': 'result',
                    'prompt_template': '{{text}}',
                    'batch_size': 10,
                },
            )
            mock_client.generate_batch.assert_not_called()
            result.collect()
            mock_client.generate_batch.assert_called_once()

    def test_empty_dataframe(self):
        handler = AIHandler()
        df = pl.DataFrame({'text': []}).cast({'text': pl.Utf8})

        result = handler(
            df.lazy(),
            {
                'input_column': 'text',
                'output_column': 'result',
                'prompt_template': '{{text}}',
                'batch_size': 5,
            },
        )
        collected = result.collect()
        assert 'result' in collected.columns
        assert len(collected) == 0

    def test_missing_column_raises(self):
        handler = AIHandler()
        df = pl.DataFrame({'name': ['Alice']})

        with pytest.raises(ValueError, match=r'Input column\(s\) not found'):
            handler(
                df.lazy(),
                {
                    'input_column': 'text',
                    'output_column': 'result',
                    'prompt_template': '{{text}}',
                    'batch_size': 5,
                },
            )

    def test_batch_size_validation(self):
        handler = AIHandler()
        df = pl.DataFrame({'text': ['Hello']})

        with pytest.raises(ValueError, match='batch_size must be at least 1'):
            handler(
                df.lazy(),
                {
                    'input_column': 'text',
                    'output_column': 'result',
                    'prompt_template': '{{text}}',
                    'batch_size': 0,
                },
            )

    def test_error_handling_per_batch(self):
        handler = AIHandler()
        df = pl.DataFrame({'text': ['a', 'b', 'c', 'd']})

        mock_client = MagicMock()
        mock_client.generate_batch.side_effect = [
            ['ok1', 'ok2'],
            AIError('API timeout'),
        ]

        with (
            patch('modules.compute.operations.ai.get_ai_client', return_value=mock_client),
            patch('modules.compute.operations.ai.time.sleep'),
        ):
            result = handler(
                df.lazy(),
                {
                    'input_column': 'text',
                    'output_column': 'result',
                    'prompt_template': '{{text}}',
                    'batch_size': 2,
                },
            )
            collected = result.collect()
            results = collected['result'].to_list()
            assert results[0] == 'ok1'
            assert results[1] == 'ok2'
            assert '[error:' in results[2]
            assert '[error:' in results[3]

    def test_batching_respects_size(self):
        handler = AIHandler()
        df = pl.DataFrame({'text': ['a', 'b', 'c', 'd', 'e']})

        mock_client = MagicMock()
        mock_client.generate_batch.side_effect = [
            ['r1', 'r2'],
            ['r3', 'r4'],
            ['r5'],
        ]

        with patch('modules.compute.operations.ai.get_ai_client', return_value=mock_client):
            result = handler(
                df.lazy(),
                {
                    'input_column': 'text',
                    'output_column': 'result',
                    'prompt_template': '{{text}}',
                    'batch_size': 2,
                },
            )
            collected = result.collect()
            assert collected['result'].to_list() == ['r1', 'r2', 'r3', 'r4', 'r5']
            assert mock_client.generate_batch.call_count == 3

    def test_prompt_template_substitution(self):
        handler = AIHandler()
        df = pl.DataFrame({'text': ['hello']})

        mock_client = MagicMock()
        mock_client.generate_batch.return_value = ['result']

        with patch('modules.compute.operations.ai.get_ai_client', return_value=mock_client):
            result = handler(
                df.lazy(),
                {
                    'input_column': 'text',
                    'output_column': 'result',
                    'prompt_template': 'Analyze: {{text}} now',
                    'batch_size': 10,
                },
            )
            result.collect()
            prompts = mock_client.generate_batch.call_args[0][0]
            assert prompts == ['Analyze: hello now']

    def test_request_options_passed_to_client(self):
        handler = AIHandler()
        df = pl.DataFrame({'text': ['test']})

        mock_client = MagicMock()
        mock_client.generate_batch.return_value = ['result']

        with patch('modules.compute.operations.ai.get_ai_client', return_value=mock_client):
            result = handler(
                df.lazy(),
                {
                    'input_column': 'text',
                    'output_column': 'result',
                    'prompt_template': '{{text}}',
                    'batch_size': 10,
                    'request_options': '{"temperature": 0.1}',
                },
            )
            result.collect()
            call_kwargs = mock_client.generate_batch.call_args[1]
            assert call_kwargs['options'] == {'temperature': 0.1}

    def test_multi_column_prompt(self):
        handler = AIHandler()
        df = pl.DataFrame({'title': ['Hello'], 'body': ['World']})

        mock_client = MagicMock()
        mock_client.generate_batch.return_value = ['result']

        with patch('modules.compute.operations.ai.get_ai_client', return_value=mock_client):
            result = handler(
                df.lazy(),
                {
                    'input_columns': ['title', 'body'],
                    'output_column': 'result',
                    'prompt_template': 'Title: {{title}} Body: {{body}}',
                    'batch_size': 10,
                },
            )
            result.collect()
            prompts = mock_client.generate_batch.call_args[0][0]
            assert prompts == ['Title: Hello Body: World']

    def test_missing_multi_column_raises(self):
        handler = AIHandler()
        df = pl.DataFrame({'title': ['Hello']})

        with pytest.raises(ValueError, match='Input column'):
            handler(
                df.lazy(),
                {
                    'input_columns': ['title', 'body'],
                    'output_column': 'result',
                    'prompt_template': '{{title}} {{body}}',
                    'batch_size': 5,
                },
            )


# ---------------------------------------------------------------------------
# convert_ai_config (step converter)
# ---------------------------------------------------------------------------


class TestConvertAIConfig:
    def test_basic_conversion(self):
        config = {
            'provider': 'openai',
            'model': 'gpt-4o',
            'input_column': 'text',
            'output_column': 'result',
            'prompt_template': 'Classify: {{text}}',
            'batch_size': 5,
            'endpoint_url': 'https://api.openai.com',
            'api_key': 'sk-test',
            'request_options': '{"temperature": 0.2}',
        }
        result = convert_ai_config(config)
        assert result['provider'] == 'openai'
        assert result['model'] == 'gpt-4o'
        assert result['input_columns'] == ['text']
        assert result['output_column'] == 'result'
        assert result['batch_size'] == 5
        assert result['request_options'] == '{"temperature": 0.2}'

    def test_camelcase_fallback(self):
        config = {
            'inputColumn': 'text',
            'outputColumn': 'result',
            'promptTemplate': 'Hello {{text}}',
            'requestOptions': '{"temperature": 0.5}',
        }
        result = convert_ai_config(config)
        assert result['input_columns'] == ['text']
        assert result['output_column'] == 'result'
        assert result['prompt_template'] == 'Hello {{text}}'
        assert result['request_options'] == '{"temperature": 0.5}'

    def test_multi_column_conversion(self):
        config = {
            'input_columns': ['title', 'body'],
            'output_column': 'result',
            'prompt_template': 'Title: {{title}} Body: {{body}}',
        }
        result = convert_ai_config(config)
        assert result['input_columns'] == ['title', 'body']

    def test_legacy_and_multi_merged(self):
        config = {
            'input_column': 'extra',
            'input_columns': ['title', 'body'],
            'output_column': 'result',
        }
        result = convert_ai_config(config)
        assert result['input_columns'] == ['extra', 'title', 'body']

    def test_legacy_no_duplicate(self):
        config = {
            'input_column': 'title',
            'input_columns': ['title', 'body'],
            'output_column': 'result',
        }
        result = convert_ai_config(config)
        assert result['input_columns'] == ['title', 'body']

    def test_empty_request_options(self):
        config = {
            'input_column': 'text',
            'output_column': 'result',
            'request_options': '',
        }
        result = convert_ai_config(config)
        assert result['request_options'] is None

    def test_defaults(self):
        result = convert_ai_config({})
        assert result['provider'] == 'ollama'
        assert result['model'] == 'llama2'
        assert result['output_column'] == 'ai_result'
        assert result['batch_size'] == 10

    def test_none_request_options(self):
        config = {'input_column': 'text', 'request_options': None}
        result = convert_ai_config(config)
        assert result['request_options'] is None


# ---------------------------------------------------------------------------
# AI Routes (via TestClient)
# ---------------------------------------------------------------------------


class TestAIRoutes:
    def test_list_models_ollama(self, client):
        mock_models = [{'name': 'llama2', 'size': 3800000000}]
        with patch('modules.ai.routes.get_ai_client') as mock_get:
            mock_client = MagicMock()
            mock_client.list_models.return_value = mock_models
            mock_get.return_value = mock_client
            response = client.post('/api/v1/ai/models', json={'provider': 'ollama'})
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]['name'] == 'llama2'

    def test_list_models_invalid_provider(self, client):
        with patch('modules.ai.routes.get_ai_client', side_effect=ValueError('Unknown provider')):
            response = client.post('/api/v1/ai/models', json={'provider': 'bad'})
            assert response.status_code == 400
            data = response.json()
            assert 'Unknown provider' in data['detail']

    def test_test_connection_success(self, client):
        with patch('modules.ai.routes.get_ai_client') as mock_get:
            mock_client = MagicMock()
            mock_client.test_connection.return_value = {'ok': True, 'detail': '3 model(s) available'}
            mock_get.return_value = mock_client
            response = client.post('/api/v1/ai/test', json={'provider': 'ollama'})
            assert response.status_code == 200
            data = response.json()
            assert data['ok'] is True

    def test_test_connection_failure(self, client):
        with patch('modules.ai.routes.get_ai_client') as mock_get:
            mock_client = MagicMock()
            mock_client.test_connection.return_value = {'ok': False, 'detail': 'Connection refused'}
            mock_get.return_value = mock_client
            response = client.post('/api/v1/ai/test', json={'provider': 'ollama'})
            assert response.status_code == 200
            data = response.json()
            assert data['ok'] is False
            assert 'Connection refused' in data['detail']

    def test_test_connection_no_key(self, client):
        with patch('modules.ai.routes.get_ai_client', side_effect=ValueError('OPENAI_API_KEY not configured')):
            response = client.post('/api/v1/ai/test', json={'provider': 'openai'})
            assert response.status_code == 400
            data = response.json()
            assert 'OPENAI_API_KEY' in data['detail']
