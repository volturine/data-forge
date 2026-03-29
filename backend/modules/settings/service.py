import logging
import os

from sqlmodel import Session, select

from modules.settings.models import AppSettings
from modules.settings.schemas import SettingsResponse, SettingsUpdate

logger = logging.getLogger(__name__)
_ENCRYPTED_PREFIX = 'enc:'


def _ensure_encryption_key() -> str:
    key = os.getenv('SETTINGS_ENCRYPTION_KEY')
    if not key:
        raise ValueError('SETTINGS_ENCRYPTION_KEY must be set to encrypt SMTP passwords')
    return key


def _xor_bytes(payload: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[idx % len(key)] for idx, b in enumerate(payload))


def _encrypt_password(password: str) -> str:
    if not password:
        return ''
    key = _ensure_encryption_key().encode('utf-8')
    raw = password.encode('utf-8')
    encrypted = _xor_bytes(raw, key)
    return f'{_ENCRYPTED_PREFIX}{encrypted.hex()}'


def _decrypt_password(value: str) -> str:
    if not value:
        return ''
    if not value.startswith(_ENCRYPTED_PREFIX):
        raise ValueError('Stored SMTP password must use encrypted storage')
    key = _ensure_encryption_key().encode('utf-8')
    encrypted = bytes.fromhex(value.removeprefix(_ENCRYPTED_PREFIX))
    raw = _xor_bytes(encrypted, key)
    return raw.decode('utf-8')


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
            row.smtp_password = _encrypt_password(app_settings.smtp_password)
            changed = True
        except ValueError:
            bootstrap_complete = False
            logger.warning('Skipping SMTP password bootstrap because SETTINGS_ENCRYPTION_KEY is not set')
    if not row.telegram_bot_token and app_settings.telegram_bot_token:
        row.telegram_bot_token = app_settings.telegram_bot_token
        changed = True
    if not row.telegram_bot_enabled and app_settings.telegram_bot_enabled:
        row.telegram_bot_enabled = app_settings.telegram_bot_enabled
        changed = True
    if not row.openrouter_api_key and app_settings.openrouter_api_key:
        row.openrouter_api_key = app_settings.openrouter_api_key
        changed = True
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

    return SettingsResponse(
        smtp_host=row.smtp_host,
        smtp_port=row.smtp_port,
        smtp_user=row.smtp_user,
        smtp_password=_decrypt_password(row.smtp_password),
        telegram_bot_token=row.telegram_bot_token,
        telegram_bot_enabled=row.telegram_bot_enabled,
        openrouter_api_key=row.openrouter_api_key,
        openrouter_default_model=row.openrouter_default_model,
        public_idb_debug=row.public_idb_debug,
    )


def update_settings(session: Session, data: SettingsUpdate) -> SettingsResponse:
    row = session.get(AppSettings, 1)
    if not row:
        row = AppSettings(id=1)
        session.add(row)

    row.smtp_host = data.smtp_host
    row.smtp_port = data.smtp_port
    row.smtp_user = data.smtp_user
    row.smtp_password = _encrypt_password(data.smtp_password)
    row.telegram_bot_token = data.telegram_bot_token
    row.telegram_bot_enabled = data.telegram_bot_enabled
    row.openrouter_api_key = data.openrouter_api_key
    row.openrouter_default_model = data.openrouter_default_model
    row.env_bootstrap_complete = True
    row.public_idb_debug = data.public_idb_debug

    session.commit()
    session.refresh(row)
    return SettingsResponse(
        smtp_host=row.smtp_host,
        smtp_port=row.smtp_port,
        smtp_user=row.smtp_user,
        smtp_password=data.smtp_password,
        telegram_bot_token=row.telegram_bot_token,
        telegram_bot_enabled=row.telegram_bot_enabled,
        openrouter_api_key=row.openrouter_api_key,
        openrouter_default_model=row.openrouter_default_model,
        public_idb_debug=row.public_idb_debug,
    )


def get_resolved_smtp() -> dict[str, object]:
    from core.database import run_settings_db

    def _read(session: Session) -> dict[str, object]:
        row = session.exec(select(AppSettings).where(AppSettings.id == 1)).first()
        if row and row.smtp_host:
            return {
                'host': row.smtp_host,
                'port': row.smtp_port,
                'user': row.smtp_user,
                'password': _decrypt_password(row.smtp_password),
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
            token = row.telegram_bot_token
            enabled = bool(row.telegram_bot_enabled and token)
            return {'enabled': enabled, 'token': token}
        return {'enabled': False, 'token': ''}

    return run_settings_db(_read)


def get_resolved_openrouter_key() -> str:
    from core.database import run_settings_db

    def _read(session: Session) -> str:
        row = session.exec(select(AppSettings).where(AppSettings.id == 1)).first()
        if row:
            return row.openrouter_api_key
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
