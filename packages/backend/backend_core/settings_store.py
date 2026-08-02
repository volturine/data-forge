import logging

from sqlmodel import Session

from backend_core.exceptions import SettingsConfigurationError
from backend_core.persistence.settings.models import AppSettings
from backend_core.secrets import decrypt_secret, encrypt_secret, is_masked_secret, mask_secret
from backend_core.settings_projection import (
    get_resolved_default_model as get_resolved_default_model,
    get_resolved_ollama_settings as get_resolved_ollama_settings,
    get_resolved_openai_settings as get_resolved_openai_settings,
    get_resolved_openrouter_key as get_resolved_openrouter_key,
    get_resolved_smtp as get_resolved_smtp,
    get_resolved_telegram_settings as get_resolved_telegram_settings,
    get_resolved_telegram_token as get_resolved_telegram_token,
    invalidate_resolved_settings_cache,
)
from backend_core.settings_schemas import SettingsResponse, SettingsUpdate

logger = logging.getLogger(__name__)

_SECRET_FIELDS = (
    'smtp_password',
    'telegram_bot_token',
    'openrouter_api_key',
    'openai_api_key',
)
_RESPONSE_VALUE_FIELDS = (
    'smtp_host',
    'smtp_port',
    'smtp_user',
    'telegram_bot_enabled',
    'openrouter_default_model',
    'openai_endpoint_url',
    'openai_default_model',
    'openai_organization_id',
    'ollama_endpoint_url',
    'ollama_default_model',
    'public_idb_debug',
)
_UPDATE_VALUE_FIELDS = _RESPONSE_VALUE_FIELDS
_BOOTSTRAP_STRING_FIELDS = (
    ('smtp_host', 'smtp_host'),
    ('smtp_user', 'smtp_user'),
    ('openrouter_default_model', 'openrouter_default_model'),
    ('openai_endpoint_url', 'openai_base_url'),
    ('openai_default_model', 'openai_default_model'),
    ('openai_organization_id', 'openai_organization_id'),
    ('ollama_endpoint_url', 'ollama_base_url'),
    ('ollama_default_model', 'ollama_default_model'),
)
_BOOTSTRAP_SECRET_FIELDS = (
    ('smtp_password', 'smtp_password', 'SMTP password'),
    ('telegram_bot_token', 'telegram_bot_token', 'Telegram token'),
    ('openrouter_api_key', 'openrouter_api_key', 'OpenRouter key'),
    ('openai_api_key', 'openai_api_key', 'OpenAI key'),
)


def _warn_bootstrap_secret_missing(name: str) -> None:
    logging.warning('Skipping %s bootstrap because SETTINGS_ENCRYPTION_KEY is not set', name)


def _read_secret(row: AppSettings, field: str) -> str:
    stored = str(getattr(row, field, '') or '')
    if not stored:
        return ''
    return decrypt_secret(stored)


def _write_secret(row: AppSettings, field: str, value: str) -> None:
    setattr(row, field, encrypt_secret(value))


def _resolve_updated_secret(row: AppSettings, field: str, value: str | None) -> str:
    if value is None:
        return _read_secret(row, field)
    if is_masked_secret(value):
        return _read_secret(row, field)
    return value


def _masked_settings_response(row: AppSettings) -> SettingsResponse:
    payload = {field: getattr(row, field) for field in _RESPONSE_VALUE_FIELDS}
    payload.update({field: mask_secret(_read_secret(row, field)) for field in _SECRET_FIELDS})
    return SettingsResponse(**payload)


def seed_settings_from_env(session: Session) -> None:
    """Seed app_settings from ENV vars on first run.

    Bootstrap ENV-backed settings into the DB once for a new settings row.

    Existing rows are treated as user-owned state and are not re-seeded on
    restart, even when a saved value is empty, False, or a default like 587.
    """
    from backend_core.config import settings as app_settings

    row = session.get(AppSettings, 1)
    if row and row.env_bootstrap_complete:
        return
    if not row:
        row = AppSettings(id=1, env_bootstrap_complete=False)
        session.add(row)

    changed = False

    for row_field, settings_field in _BOOTSTRAP_STRING_FIELDS:
        value = getattr(app_settings, settings_field)
        if not getattr(row, row_field) and value:
            setattr(row, row_field, value)
            changed = True
    if row.smtp_port == 587 and app_settings.smtp_port != 587:
        row.smtp_port = app_settings.smtp_port
        changed = True
    bootstrap_complete = True
    for row_field, settings_field, label in _BOOTSTRAP_SECRET_FIELDS:
        value = getattr(app_settings, settings_field)
        if not getattr(row, row_field) and value:
            try:
                _write_secret(row, row_field, value)
                changed = True
            except SettingsConfigurationError:
                bootstrap_complete = False
                _warn_bootstrap_secret_missing(label)
    if not row.telegram_bot_enabled and app_settings.telegram_bot_enabled:
        row.telegram_bot_enabled = app_settings.telegram_bot_enabled
        changed = True
    if row.env_bootstrap_complete != bootstrap_complete:
        row.env_bootstrap_complete = bootstrap_complete
        changed = True

    if changed:
        session.commit()
        session.refresh(row)
        invalidate_resolved_settings_cache()


def get_settings(session: Session) -> SettingsResponse:
    row = session.get(AppSettings, 1)
    if not row:
        row = AppSettings(
            id=1,
            public_idb_debug=False,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        invalidate_resolved_settings_cache()

    return _masked_settings_response(row)


def update_settings(session: Session, data: SettingsUpdate) -> SettingsResponse:
    row = session.get(AppSettings, 1)
    if not row:
        row = AppSettings(id=1)
        session.add(row)

    for field in _UPDATE_VALUE_FIELDS:
        value = getattr(data, field)
        if value is not None:
            setattr(row, field, value)
    for field in _SECRET_FIELDS:
        _write_secret(row, field, _resolve_updated_secret(row, field, getattr(data, field)))
    row.env_bootstrap_complete = True

    session.commit()
    session.refresh(row)
    invalidate_resolved_settings_cache()
    return _masked_settings_response(row)
