"""Settings service — singleton row CRUD with env-var fallback."""

from sqlmodel import Session, select

from core.config import settings as env_settings
from modules.settings.models import AppSettings
from modules.settings.schemas import SettingsResponse, SettingsUpdate


def get_settings(session: Session) -> SettingsResponse:
    """Return the singleton settings row, creating it from env-var defaults if absent."""
    row = session.get(AppSettings, 1)
    if not row:
        row = AppSettings(
            id=1,
            smtp_host=env_settings.smtp_host,
            smtp_port=env_settings.smtp_port,
            smtp_user=env_settings.smtp_user,
            smtp_password=env_settings.smtp_password,
            telegram_bot_token=env_settings.telegram_bot_token,
            public_idb_debug=env_settings.public_idb_debug,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
    return SettingsResponse.model_validate(row)


def update_settings(session: Session, data: SettingsUpdate) -> SettingsResponse:
    """Upsert the singleton settings row."""
    row = session.get(AppSettings, 1)
    if not row:
        row = AppSettings(id=1)
        session.add(row)

    row.smtp_host = data.smtp_host
    row.smtp_port = data.smtp_port
    row.smtp_user = data.smtp_user
    row.smtp_password = data.smtp_password
    row.telegram_bot_token = data.telegram_bot_token
    row.telegram_bot_enabled = data.telegram_bot_enabled
    row.public_idb_debug = data.public_idb_debug

    session.commit()
    session.refresh(row)
    return SettingsResponse.model_validate(row)


def get_resolved_smtp() -> dict[str, object]:
    """Return the effective SMTP settings by reading from DB, falling back to env vars.

    Used by the notification service (runs in subprocesses, so opens its own session).
    """
    from core.database import run_db

    def _read(session: Session) -> dict[str, object]:
        row = session.exec(select(AppSettings).where(AppSettings.id == 1)).first()
        if row and row.smtp_host:
            return {
                'host': row.smtp_host,
                'port': row.smtp_port,
                'user': row.smtp_user,
                'password': row.smtp_password,
            }
        return {
            'host': env_settings.smtp_host,
            'port': env_settings.smtp_port,
            'user': env_settings.smtp_user,
            'password': env_settings.smtp_password,
        }

    return run_db(_read)


def get_resolved_telegram_token() -> str:
    """Return the effective Telegram bot token by reading from DB, falling back to env var."""
    from core.database import run_db

    def _read(session: Session) -> str:
        row = session.exec(select(AppSettings).where(AppSettings.id == 1)).first()
        if row and row.telegram_bot_token:
            return row.telegram_bot_token
        return env_settings.telegram_bot_token

    return run_db(_read)
