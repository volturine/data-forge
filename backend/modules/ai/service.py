import json
import logging
from collections.abc import Sequence

import httpx

from core import http as http_client
from core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=10, read=120, write=10, pool=10)
_MAX_RETRIES = 2


class AIError(Exception):
    """Raised when an AI API call fails after retries."""


class AIClient:
    def generate(self, prompt: str, *, model: str, options: dict | None = None) -> str:
        raise NotImplementedError

    def generate_batch(self, prompts: Sequence[str], *, model: str, options: dict | None = None) -> list[str]:
        return [self.generate(prompt, model=model, options=options) for prompt in prompts]

    def list_models(self) -> list[dict]:
        raise NotImplementedError

    def test_connection(self) -> dict:
        """Return {'ok': True/False, 'detail': str}."""
        raise NotImplementedError


def _retry_request(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    payload: dict | None = None,
    retries: int = _MAX_RETRIES,
) -> httpx.Response:
    """Make an HTTP request with retry logic."""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = http_client.request(method, url, json=payload, headers=headers, timeout=_TIMEOUT)
            response.raise_for_status()
            return response
        except httpx.TimeoutException as exc:
            last_error = exc
            logger.warning('AI request timeout (attempt %d/%d): %s', attempt + 1, retries + 1, url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                last_error = exc
                logger.warning(
                    'AI server error %d (attempt %d/%d): %s',
                    exc.response.status_code,
                    attempt + 1,
                    retries + 1,
                    url,
                )
            else:
                raise AIError(f'AI API returned {exc.response.status_code}: {exc.response.text[:500]}') from exc
        except httpx.ConnectError as exc:
            raise AIError(f'Cannot connect to AI provider at {url}') from exc
    raise AIError(f'AI request failed after {retries + 1} attempts: {last_error}')


class OllamaClient(AIClient):
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip('/')

    def generate(self, prompt: str, *, model: str, options: dict | None = None) -> str:
        payload: dict[str, object] = {'model': model, 'prompt': prompt, 'stream': False}
        if options:
            payload['options'] = options
        response = _retry_request('POST', f'{self.base_url}/api/generate', payload=payload)
        data = response.json()
        return str(data.get('response', ''))

    def list_models(self) -> list[dict]:
        try:
            response = _retry_request('GET', f'{self.base_url}/api/tags', retries=0)
            data = response.json()
            return [{'name': m.get('name', ''), 'size': m.get('size', 0)} for m in data.get('models', [])]
        except AIError:
            return []

    def test_connection(self) -> dict:
        try:
            response = http_client.get(f'{self.base_url}/api/tags', timeout=_TIMEOUT)
            response.raise_for_status()
            models = response.json().get('models', [])
            return {'ok': True, 'detail': f'{len(models)} model(s) available'}
        except Exception as exc:
            return {'ok': False, 'detail': str(exc)}


class OpenAIClient(AIClient):
    def __init__(self, api_key: str = '', base_url: str | None = None, organization_id: str = '') -> None:
        self.api_key = api_key
        self.base_url = (base_url or 'https://api.openai.com').rstrip('/')
        self.organization_id = organization_id

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        if self.organization_id:
            headers['OpenAI-Organization'] = self.organization_id
        return headers

    def generate(self, prompt: str, *, model: str, options: dict | None = None) -> str:
        payload: dict[str, object] = {
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
        }
        if options:
            payload.update(options)
        response = _retry_request(
            'POST',
            f'{self.base_url}/v1/chat/completions',
            headers=self._headers(),
            payload=payload,
        )
        data = response.json()
        choices = data.get('choices', [])
        if not choices:
            return ''
        message = choices[0].get('message', {})
        content = message.get('content', '')
        if isinstance(content, list):
            chunks = [str(part.get('text', '')) for part in content if isinstance(part, dict)]
            return ''.join(chunks)
        return str(content)

    def list_models(self) -> list[dict]:
        try:
            response = _retry_request('GET', f'{self.base_url}/v1/models', headers=self._headers(), retries=0)
            data = response.json()
            return [{'name': m.get('id', ''), 'owned_by': m.get('owned_by', '')} for m in data.get('data', [])]
        except AIError:
            return []

    def test_connection(self) -> dict:
        try:
            response = http_client.get(
                f'{self.base_url}/v1/models',
                headers=self._headers(),
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
            models = response.json().get('data', [])
            return {'ok': True, 'detail': f'{len(models)} model(s) available'}
        except Exception as exc:
            return {'ok': False, 'detail': str(exc)}


class OpenRouterClient(AIClient):
    def __init__(self, api_key: str, base_url: str = 'https://openrouter.ai/api/v1') -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')

    def _headers(self) -> dict[str, str]:
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

    def generate(self, prompt: str, *, model: str, options: dict | None = None) -> str:
        payload: dict[str, object] = {
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
        }
        if options:
            payload.update(options)
        response = _retry_request(
            'POST',
            f'{self.base_url}/chat/completions',
            headers=self._headers(),
            payload=payload,
        )
        data = response.json()
        choices = data.get('choices', [])
        if not choices:
            return ''
        content = choices[0].get('message', {}).get('content', '')
        return str(content)

    def list_models(self) -> list[dict]:
        try:
            response = _retry_request('GET', f'{self.base_url}/models', headers=self._headers(), retries=0)
            data = response.json()
            models = data.get('data', [])
            return [
                {
                    'name': m.get('id', ''),
                    'label': m.get('name', ''),
                    'context_length': m.get('context_length', 0),
                }
                for m in models
            ]
        except AIError:
            return []

    def test_connection(self) -> dict:
        try:
            response = http_client.get(f'{self.base_url}/models', headers=self._headers(), timeout=_TIMEOUT)
            response.raise_for_status()
            models = response.json().get('data', [])
            return {'ok': True, 'detail': f'{len(models)} model(s) available'}
        except Exception as exc:
            return {'ok': False, 'detail': str(exc)}


class HuggingFaceClient(AIClient):
    def __init__(
        self,
        api_token: str = '',
        base_url: str = 'https://api-inference.huggingface.co',
    ) -> None:
        self.api_token = api_token
        self.base_url = base_url.rstrip('/')

    def _headers(self) -> dict[str, str]:
        headers = {'Content-Type': 'application/json'}
        if self.api_token:
            headers['Authorization'] = f'Bearer {self.api_token}'
        return headers

    @staticmethod
    def _extract_generated_text(payload: object) -> str:
        if isinstance(payload, list):
            first = payload[0] if payload else None
            if isinstance(first, dict):
                if isinstance(first.get('generated_text'), str):
                    return first['generated_text']
                if isinstance(first.get('summary_text'), str):
                    return first['summary_text']
                if isinstance(first.get('translation_text'), str):
                    return first['translation_text']
        if isinstance(payload, dict):
            if isinstance(payload.get('generated_text'), str):
                return payload['generated_text']
            if isinstance(payload.get('summary_text'), str):
                return payload['summary_text']
            if isinstance(payload.get('translation_text'), str):
                return payload['translation_text']
            if isinstance(payload.get('error'), str):
                raise AIError(payload['error'])
        return ''

    def generate(self, prompt: str, *, model: str, options: dict | None = None) -> str:
        payload: dict[str, object] = {'inputs': prompt}
        if options:
            payload['parameters'] = options
        response = _retry_request(
            'POST',
            f'{self.base_url}/models/{model}',
            headers=self._headers(),
            payload=payload,
        )
        return self._extract_generated_text(response.json())

    def list_models(self) -> list[dict]:
        # The searchable HF model index lives on huggingface.co, not the inference host.
        hub_url = 'https://huggingface.co/api/models?sort=downloads&direction=-1&limit=100'
        try:
            response = _retry_request('GET', hub_url, headers=self._headers(), retries=0)
            models = response.json()
            if not isinstance(models, list):
                return []
            return [
                {
                    'name': m.get('id', ''),
                    'pipeline_tag': m.get('pipeline_tag', ''),
                    'downloads': m.get('downloads', 0),
                }
                for m in models
            ]
        except AIError:
            return []

    def test_connection(self) -> dict:
        if not self.api_token:
            return {'ok': False, 'detail': 'Hugging Face API token is required'}
        try:
            response = http_client.get(
                'https://huggingface.co/api/whoami-v2',
                headers=self._headers(),
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            name = data.get('name') or data.get('fullname') or 'authenticated'
            return {'ok': True, 'detail': f'Connected as {name}'}
        except Exception as exc:
            return {'ok': False, 'detail': str(exc)}


def get_ai_client(
    provider: str,
    *,
    endpoint_url: str | None = None,
    api_key: str | None = None,
    organization_id: str | None = None,
) -> AIClient:
    normalized = provider.strip().lower()

    if normalized == 'ollama':
        from modules.settings.service import get_resolved_ollama_settings

        resolved = get_resolved_ollama_settings()
        return OllamaClient(endpoint_url or resolved['endpoint_url'] or settings.ollama_base_url)

    if normalized == 'openai':
        from modules.settings.service import get_resolved_openai_settings

        resolved = get_resolved_openai_settings()
        resolved_key = api_key if api_key is not None else resolved['api_key'] or settings.openai_api_key
        if not resolved_key:
            raise ValueError('OPENAI_API_KEY not configured')
        return OpenAIClient(
            api_key=resolved_key,
            base_url=endpoint_url or resolved['endpoint_url'] or settings.openai_base_url,
            organization_id=organization_id if organization_id is not None else resolved['organization_id'],
        )

    if normalized == 'openrouter':
        from modules.settings.service import get_resolved_openrouter_key

        resolved_key = api_key if api_key is not None else get_resolved_openrouter_key() or settings.openrouter_api_key
        if not resolved_key:
            raise ValueError('OPENROUTER_API_KEY not configured')
        return OpenRouterClient(resolved_key)

    if normalized in {'huggingface', 'huggingface-api'}:
        from modules.settings.service import get_resolved_huggingface_settings

        resolved = get_resolved_huggingface_settings()
        return HuggingFaceClient(
            api_token=api_key if api_key is not None else resolved['api_token'] or settings.huggingface_api_token,
            base_url=endpoint_url or settings.huggingface_api_base_url,
        )

    raise ValueError(f'Unknown AI provider: {provider}')


def parse_request_options(raw: str | dict | None) -> dict | None:
    """Parse request_options from frontend (may be JSON string or dict)."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f'Invalid JSON in request_options: {exc}') from exc
        if not isinstance(parsed, dict):
            raise ValueError('request_options must be a JSON object')
        return parsed
    return None
