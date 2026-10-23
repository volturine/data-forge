import logging

from sqlmodel import Session

from backend_core.exceptions import SettingsConfigurationError
from backend_core.persistence.settings.models import AppSettings
from backend_core.runtime_ipc import notify_on_commit
from backend_core.secrets import encrypt_secret, is_masked_secret, mask_secret
from backend_core.settings_projection import read_stored_secret
from backend_core.settings_schemas import SettingsResponse, SettingsUpdate

logger = logging.getLogger(__name__)


_SECRET_FIELDS = (
    'smtp_password',
    'telegram_bot_token',
    'openrouter_api_key',
)
_RESPONSE_VALUE_FIELDS = (
    'smtp_host',
    'smtp_port',
    'smtp_user',
    'telegram_bot_enabled',
    'openrouter_default_model',
    'ollama_endpoint_url',
    'ollama_default_model',
    'public_idb_debug',
)
_BOOTSTRAP_STRING_FIELDS = (
    ('smtp_host', 'smtp_host'),
    ('smtp_user', 'smtp_user'),
    ('openrouter_default_model', 'openrouter_default_model'),
    ('ollama_endpoint_url', 'ollama_base_url'),
    ('ollama_default_model', 'ollama_default_model'),
)
_BOOTSTRAP_SECRET_FIELDS = (
    ('smtp_password', 'smtp_password', 'SMTP password'),
    ('telegram_bot_token', 'telegram_bot_token', 'Telegram token'),
    ('openrouter_api_key', 'openrouter_api_key', 'OpenRouter key'),
)


def _warn_bootstrap_secret_missing(name: str) -> None:
    logger.warning('Skipping %s bootstrap because SETTINGS_ENCRYPTION_KEY is not set', name)


def _notify_settings_changed(session: Session) -> None:
    notify_on_commit(session, {'kind': 'settings_changed'})


def _masked_settings_response(row: AppSettings) -> SettingsResponse:
    payload = {field: getattr(row, field) for field in _RESPONSE_VALUE_FIELDS}
    payload.update({field: mask_secret(read_stored_secret(row, field)) for field in _SECRET_FIELDS})
    return SettingsResponse(**payload)


def ensure_openrouter_key_populated(session: Session) -> str:
    """Copy OPENROUTER_API_KEY into settings when the saved key is empty.

    A later profile save writes a different value into the same field. Chat and
    Profile Test then read that saved value and leave the deployment key alone.
    """
    row = session.get(AppSettings, 1)
    if row is None:
        return ''
    if str(row.openrouter_api_key or ''):
        return read_stored_secret(row, 'openrouter_api_key')
    from backend_core.config import settings as app_settings

    deployment = app_settings.openrouter_api_key or ''
    if not deployment:
        return ''
    try:
        row.openrouter_api_key = encrypt_secret(deployment)
    except SettingsConfigurationError:
        _warn_bootstrap_secret_missing('OpenRouter key')
        return ''
    _notify_settings_changed(session)
    session.commit()
    session.refresh(row)
    return deployment


def seed_settings_from_env(session: Session) -> None:
    """Seed app_settings from ENV vars on first run.

    Bootstrap ENV-backed settings into the DB once for a new settings row.

    Existing rows are treated as user-owned state and are not re-seeded on
    restart, even when a saved value is empty, False, or a default like 587.
    """
    from backend_core.config import settings as app_settings

    row = session.get(AppSettings, 1)
    if row and row.env_bootstrap_complete:
        # Other saved settings stay as the user left them. An empty OpenRouter
        # key is still filled from the deployment so chat and Profile Test share it.
        if not str(row.openrouter_api_key or ''):
            ensure_openrouter_key_populated(session)
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
                setattr(row, row_field, encrypt_secret(value))
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
        _notify_settings_changed(session)
        session.commit()
        session.refresh(row)


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

    ensure_openrouter_key_populated(session)
    session.refresh(row)
    return _masked_settings_response(row)


def update_settings(session: Session, data: SettingsUpdate) -> SettingsResponse:
    row = session.get(AppSettings, 1)
    if not row:
        row = AppSettings(id=1)
        session.add(row)

    for field in _RESPONSE_VALUE_FIELDS:
        value = getattr(data, field)
        if value is not None:
            setattr(row, field, value)
    for field in _SECRET_FIELDS:
        submitted = getattr(data, field)
        # An omitted or still-masked secret keeps the stored value.
        secret = read_stored_secret(row, field) if submitted is None or is_masked_secret(submitted) else submitted
        setattr(row, field, encrypt_secret(secret))
    row.env_bootstrap_complete = True

    _notify_settings_changed(session)
    session.commit()
    session.refresh(row)
    return _masked_settings_response(row)
