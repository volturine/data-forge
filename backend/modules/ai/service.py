import json
import logging
from collections.abc import Sequence

import httpx

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
            response = httpx.request(method, url, json=payload, headers=headers, timeout=_TIMEOUT)
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
            response = httpx.get(f'{self.base_url}/api/tags', timeout=_TIMEOUT)
            response.raise_for_status()
            models = response.json().get('models', [])
            return {'ok': True, 'detail': f'{len(models)} model(s) available'}
        except Exception as exc:
            return {'ok': False, 'detail': str(exc)}


class OpenAIClient(AIClient):
    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.base_url = (base_url or 'https://api.openai.com').rstrip('/')

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
            f'{self.base_url}/v1/chat/completions',
            headers=self._headers(),
            payload=payload,
        )
        data = response.json()
        choices = data.get('choices', [])
        if not choices:
            return ''
        message = choices[0].get('message', {})
        return str(message.get('content', ''))

    def list_models(self) -> list[dict]:
        try:
            response = _retry_request('GET', f'{self.base_url}/v1/models', headers=self._headers(), retries=0)
            data = response.json()
            return [{'name': m.get('id', ''), 'owned_by': m.get('owned_by', '')} for m in data.get('data', [])]
        except AIError:
            return []

    def test_connection(self) -> dict:
        try:
            response = httpx.get(
                f'{self.base_url}/v1/models',
                headers=self._headers(),
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
            models = response.json().get('data', [])
            return {'ok': True, 'detail': f'{len(models)} model(s) available'}
        except Exception as exc:
            return {'ok': False, 'detail': str(exc)}


def get_ai_client(
    provider: str,
    *,
    endpoint_url: str | None = None,
    api_key: str | None = None,
) -> AIClient:
    if provider == 'ollama':
        return OllamaClient(endpoint_url or settings.ollama_base_url)
    if provider == 'openai':
        key = api_key or settings.openai_api_key
        if not key:
            raise ValueError('OPENAI_API_KEY not configured')
        return OpenAIClient(key, base_url=endpoint_url)
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
