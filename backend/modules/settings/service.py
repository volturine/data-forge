import logging

from sqlmodel import Session, select

from core.exceptions import SettingsConfigurationError
from core.secrets import (
    decrypt_secret,
    encrypt_secret,
    is_masked_secret,
    mask_secret,
    should_migrate_secret,
)
from modules.settings.models import AppSettings
from modules.settings.schemas import SettingsResponse, SettingsUpdate

logger = logging.getLogger(__name__)


def _read_secret(row: AppSettings, field: str) -> str:
    stored = str(getattr(row, field, '') or '')
    if not stored:
        return ''
    value = decrypt_secret(stored)
    if should_migrate_secret(stored):
        setattr(row, field, encrypt_secret(value))
    return value


def _write_secret(row: AppSettings, field: str, value: str) -> None:
    setattr(row, field, encrypt_secret(value))


def _resolve_updated_secret(row: AppSettings, field: str, value: str | None) -> str:
    if value is None:
        return _read_secret(row, field)
    if is_masked_secret(value):
        return _read_secret(row, field)
    return value


def _masked_settings_response(row: AppSettings) -> SettingsResponse:
    smtp_password = _read_secret(row, 'smtp_password')
    telegram_bot_token = _read_secret(row, 'telegram_bot_token')
    openrouter_api_key = _read_secret(row, 'openrouter_api_key')
    return SettingsResponse(
        smtp_host=row.smtp_host,
        smtp_port=row.smtp_port,
        smtp_user=row.smtp_user,
        smtp_password=mask_secret(smtp_password),
        telegram_bot_token=mask_secret(telegram_bot_token),
        telegram_bot_enabled=row.telegram_bot_enabled,
        openrouter_api_key=mask_secret(openrouter_api_key),
        openrouter_default_model=row.openrouter_default_model,
        public_idb_debug=row.public_idb_debug,
    )


def seed_settings_from_env(session: Session) -> None:
    """Seed app_settings from ENV vars on first run.

    Bootstrap ENV-backed settings into the DB once for a new settings row.

    Existing rows are treated as user-owned state and are not re-seeded on
    restart, even when a saved value is empty, False, or a default like 587.
    """
    from core.config import settings as app_settings

    row = session.get(AppSettings, 1)
    if row and row.env_bootstrap_complete:
        return
    if not row:
        row = AppSettings(id=1, env_bootstrap_complete=False)
        session.add(row)

    changed = False

    if not row.smtp_host and app_settings.smtp_host:
        row.smtp_host = app_settings.smtp_host
        changed = True
    if row.smtp_port == 587 and app_settings.smtp_port != 587:
        row.smtp_port = app_settings.smtp_port
        changed = True
    if not row.smtp_user and app_settings.smtp_user:
        row.smtp_user = app_settings.smtp_user
        changed = True
    bootstrap_complete = True
    if not row.smtp_password and app_settings.smtp_password:
        try:
            _write_secret(row, 'smtp_password', app_settings.smtp_password)
            changed = True
        except SettingsConfigurationError:
            bootstrap_complete = False
            logger.warning('Skipping SMTP password bootstrap because SETTINGS_ENCRYPTION_KEY is not set')
    if not row.telegram_bot_token and app_settings.telegram_bot_token:
        try:
            _write_secret(row, 'telegram_bot_token', app_settings.telegram_bot_token)
            changed = True
        except SettingsConfigurationError:
            bootstrap_complete = False
            logger.warning('Skipping Telegram token bootstrap because SETTINGS_ENCRYPTION_KEY is not set')
    if not row.telegram_bot_enabled and app_settings.telegram_bot_enabled:
        row.telegram_bot_enabled = app_settings.telegram_bot_enabled
        changed = True
    if not row.openrouter_api_key and app_settings.openrouter_api_key:
        try:
            _write_secret(row, 'openrouter_api_key', app_settings.openrouter_api_key)
            changed = True
        except SettingsConfigurationError:
            bootstrap_complete = False
            logger.warning('Skipping OpenRouter key bootstrap because SETTINGS_ENCRYPTION_KEY is not set')
    if not row.openrouter_default_model and app_settings.openrouter_default_model:
        row.openrouter_default_model = app_settings.openrouter_default_model
        changed = True
    if row.env_bootstrap_complete != bootstrap_complete:
        row.env_bootstrap_complete = bootstrap_complete
        changed = True

    if changed:
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

    migrated = False
    for field in ('smtp_password', 'telegram_bot_token', 'openrouter_api_key'):
        stored = str(getattr(row, field, '') or '')
        if should_migrate_secret(stored):
            _read_secret(row, field)
            migrated = True
    if migrated:
        session.add(row)
        session.commit()
        session.refresh(row)

    return _masked_settings_response(row)


def update_settings(session: Session, data: SettingsUpdate) -> SettingsResponse:
    row = session.get(AppSettings, 1)
    if not row:
        row = AppSettings(id=1)
        session.add(row)

    if data.smtp_host is not None:
        row.smtp_host = data.smtp_host
    if data.smtp_port is not None:
        row.smtp_port = data.smtp_port
    if data.smtp_user is not None:
        row.smtp_user = data.smtp_user
    smtp_password = _resolve_updated_secret(row, 'smtp_password', data.smtp_password)
    telegram_bot_token = _resolve_updated_secret(row, 'telegram_bot_token', data.telegram_bot_token)
    openrouter_api_key = _resolve_updated_secret(row, 'openrouter_api_key', data.openrouter_api_key)
    _write_secret(row, 'smtp_password', smtp_password)
    _write_secret(row, 'telegram_bot_token', telegram_bot_token)
    _write_secret(row, 'openrouter_api_key', openrouter_api_key)
    if data.telegram_bot_enabled is not None:
        row.telegram_bot_enabled = data.telegram_bot_enabled
    if data.openrouter_default_model is not None:
        row.openrouter_default_model = data.openrouter_default_model
    row.env_bootstrap_complete = True
    if data.public_idb_debug is not None:
        row.public_idb_debug = data.public_idb_debug

    session.commit()
    session.refresh(row)
    return _masked_settings_response(row)


def get_resolved_smtp() -> dict[str, object]:
    from core.database import run_settings_db

    def _read(session: Session) -> dict[str, object]:
        row = session.exec(select(AppSettings).where(AppSettings.id == 1)).first()
        if row and row.smtp_host:
            return {
                'host': row.smtp_host,
                'port': row.smtp_port,
                'user': row.smtp_user,
                'password': _read_secret(row, 'smtp_password'),
            }
        return {
            'host': '',
            'port': 587,
            'user': '',
            'password': '',
        }

    return run_settings_db(_read)


def get_resolved_telegram_token() -> str:
    resolved = get_resolved_telegram_settings()
    return str(resolved['token'])


def get_resolved_telegram_settings() -> dict[str, object]:
    from core.database import run_settings_db

    def _read(session: Session) -> dict[str, object]:
        row = session.exec(select(AppSettings).where(AppSettings.id == 1)).first()
        if row:
            token = _read_secret(row, 'telegram_bot_token')
            enabled = bool(row.telegram_bot_enabled and token)
            return {'enabled': enabled, 'token': token}
        return {'enabled': False, 'token': ''}

    return run_settings_db(_read)


def get_resolved_openrouter_key() -> str:
    from core.database import run_settings_db

    def _read(session: Session) -> str:
        row = session.exec(select(AppSettings).where(AppSettings.id == 1)).first()
        if row:
            return _read_secret(row, 'openrouter_api_key')
        return ''

    return run_settings_db(_read)


def get_resolved_default_model() -> str:
    from core.database import run_settings_db

    def _read(session: Session) -> str:
        row = session.exec(select(AppSettings).where(AppSettings.id == 1)).first()
        if row:
            return row.openrouter_default_model
        return ''

    return run_settings_db(_read)
