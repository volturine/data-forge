from __future__ import annotations

import logging
from threading import Lock

from sqlmodel import Session

from contracts.settings_models import AppSettings
from core.secrets import decrypt_secret

logger = logging.getLogger(__name__)

_RESOLVED_LOCK = Lock()
_RESOLVED_CACHE: dict[int, dict[str, object]] = {}


def invalidate_resolved_settings_cache() -> None:
    with _RESOLVED_LOCK:
        _RESOLVED_CACHE.clear()


def _read_secret(row: AppSettings, field: str) -> str:
    stored = str(getattr(row, field, '') or '')
    if not stored:
        return ''
    return decrypt_secret(stored)


def _active_settings_engine_id() -> int:
    from core.database import get_settings_engine

    return id(get_settings_engine())


def _load_resolved_snapshot(session: Session) -> dict[str, object]:
    row = session.get(AppSettings, 1)
    if not row:
        return {
            'exists': False,
            'smtp_host': '',
            'smtp_port': 587,
            'smtp_user': '',
            'smtp_password': '',
            'telegram_bot_enabled': False,
            'telegram_bot_token': '',
            'openrouter_api_key': '',
            'openrouter_default_model': '',
            'openai_api_key': '',
            'openai_endpoint_url': 'https://api.openai.com',
            'openai_default_model': 'gpt-4o-mini',
            'openai_organization_id': '',
            'ollama_endpoint_url': 'http://localhost:11434',
            'ollama_default_model': 'llama3.2',
            'huggingface_api_token': '',
            'huggingface_default_model': 'google/flan-t5-base',
        }

    return {
        'exists': True,
        'smtp_host': row.smtp_host,
        'smtp_port': row.smtp_port,
        'smtp_user': row.smtp_user,
        'smtp_password': _read_secret(row, 'smtp_password'),
        'telegram_bot_enabled': row.telegram_bot_enabled,
        'telegram_bot_token': _read_secret(row, 'telegram_bot_token'),
        'openrouter_api_key': _read_secret(row, 'openrouter_api_key'),
        'openrouter_default_model': row.openrouter_default_model,
        'openai_api_key': _read_secret(row, 'openai_api_key'),
        'openai_endpoint_url': row.openai_endpoint_url or 'https://api.openai.com',
        'openai_default_model': row.openai_default_model or 'gpt-4o-mini',
        'openai_organization_id': row.openai_organization_id or '',
        'ollama_endpoint_url': row.ollama_endpoint_url or 'http://localhost:11434',
        'ollama_default_model': row.ollama_default_model or 'llama3.2',
        'huggingface_api_token': _read_secret(row, 'huggingface_api_token'),
        'huggingface_default_model': row.huggingface_default_model or 'google/flan-t5-base',
    }


def _get_resolved_snapshot() -> dict[str, object]:
    from core.database import run_settings_db

    key = _active_settings_engine_id()
    with _RESOLVED_LOCK:
        cached = _RESOLVED_CACHE.get(key)
    if cached is not None:
        return cached

    snapshot = run_settings_db(_load_resolved_snapshot)
    with _RESOLVED_LOCK:
        _RESOLVED_CACHE[key] = snapshot
    return snapshot


def get_resolved_smtp() -> dict[str, object]:
    resolved = _get_resolved_snapshot()
    port = resolved['smtp_port']
    if bool(resolved['exists']) and bool(resolved['smtp_host']):
        return {
            'host': str(resolved['smtp_host']),
            'port': port if isinstance(port, int) else 587,
            'user': str(resolved['smtp_user']),
            'password': str(resolved['smtp_password']),
        }
    return {'host': '', 'port': 587, 'user': '', 'password': ''}


def get_resolved_telegram_token() -> str:
    resolved = get_resolved_telegram_settings()
    return str(resolved['token'])


def get_resolved_telegram_settings() -> dict[str, object]:
    resolved = _get_resolved_snapshot()
    if not bool(resolved['exists']):
        return {'enabled': False, 'token': ''}
    token = str(resolved['telegram_bot_token'])
    enabled = bool(resolved['telegram_bot_enabled'] and token)
    return {'enabled': enabled, 'token': token}


def get_resolved_openrouter_key() -> str:
    resolved = _get_resolved_snapshot()
    return str(resolved['openrouter_api_key']) if bool(resolved['exists']) else ''


def get_resolved_openai_settings() -> dict[str, str]:
    resolved = _get_resolved_snapshot()
    if not bool(resolved['exists']):
        return {'api_key': '', 'endpoint_url': 'https://api.openai.com', 'default_model': 'gpt-4o-mini', 'organization_id': ''}
    return {
        'api_key': str(resolved['openai_api_key']),
        'endpoint_url': str(resolved['openai_endpoint_url']),
        'default_model': str(resolved['openai_default_model']),
        'organization_id': str(resolved['openai_organization_id']),
    }


def get_resolved_ollama_settings() -> dict[str, str]:
    resolved = _get_resolved_snapshot()
    if not bool(resolved['exists']):
        return {'endpoint_url': 'http://localhost:11434', 'default_model': 'llama3.2'}
    return {'endpoint_url': str(resolved['ollama_endpoint_url']), 'default_model': str(resolved['ollama_default_model'])}


def get_resolved_huggingface_settings() -> dict[str, str]:
    resolved = _get_resolved_snapshot()
    if not bool(resolved['exists']):
        return {'api_token': '', 'default_model': 'google/flan-t5-base'}
    return {'api_token': str(resolved['huggingface_api_token']), 'default_model': str(resolved['huggingface_default_model'])}


def get_resolved_default_model() -> str:
    resolved = _get_resolved_snapshot()
    return str(resolved['openrouter_default_model']) if bool(resolved['exists']) else ''
