import os

from sqlmodel import Session, select

from modules.settings.models import AppSettings
from modules.settings.schemas import SettingsResponse, SettingsUpdate


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
    return encrypted.hex()


def _decrypt_password(value: str) -> str:
    if not value:
        return ''
    key = _ensure_encryption_key().encode('utf-8')
    encrypted = bytes.fromhex(value)
    raw = _xor_bytes(encrypted, key)
    return raw.decode('utf-8')


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

    smtp_password = ''
    if row.smtp_password_encrypted:
        smtp_password = _decrypt_password(row.smtp_password_encrypted)
    elif row.smtp_password:
        smtp_password = row.smtp_password

    return SettingsResponse(
        smtp_host=row.smtp_host,
        smtp_port=row.smtp_port,
        smtp_user=row.smtp_user,
        smtp_password=smtp_password,
        telegram_bot_token=row.telegram_bot_token,
        telegram_bot_enabled=row.telegram_bot_enabled,
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
    row.smtp_password_encrypted = _encrypt_password(data.smtp_password)
    row.smtp_password = ''
    row.telegram_bot_token = data.telegram_bot_token
    row.telegram_bot_enabled = data.telegram_bot_enabled
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
        public_idb_debug=row.public_idb_debug,
    )


def get_resolved_smtp() -> dict[str, object]:
    from core.database import run_db

    def _read(session: Session) -> dict[str, object]:
        row = session.exec(select(AppSettings).where(AppSettings.id == 1)).first()
        if row and row.smtp_host:
            password = ''
            if row.smtp_password_encrypted:
                password = _decrypt_password(row.smtp_password_encrypted)
            elif row.smtp_password:
                password = row.smtp_password
            return {
                'host': row.smtp_host,
                'port': row.smtp_port,
                'user': row.smtp_user,
                'password': password,
            }
        return {
            'host': '',
            'port': 587,
            'user': '',
            'password': '',
        }

    return run_db(_read)


def get_resolved_telegram_token() -> str:
    resolved = get_resolved_telegram_settings()
    return str(resolved['token'])


def get_resolved_telegram_settings() -> dict[str, object]:
    from core.database import run_db

    def _read(session: Session) -> dict[str, object]:
        row = session.exec(select(AppSettings).where(AppSettings.id == 1)).first()
        if row:
            token = row.telegram_bot_token
            enabled = bool(row.telegram_bot_enabled and token)
            return {'enabled': enabled, 'token': token}
        return {'enabled': False, 'token': ''}

    return run_db(_read)
