from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session

from backend_core.persistence.settings.models import AppSettings
from backend_core.secrets import decrypt_secret

DEFAULT_SMTP_PORT = 587
DEFAULT_OLLAMA_ENDPOINT_URL = 'http://localhost:11434'
DEFAULT_OLLAMA_MODEL = 'llama3.2'


@dataclass(frozen=True, slots=True)
class ResolvedSettingsSnapshot:
    exists: bool
    smtp_host: str = ''
    smtp_port: int = DEFAULT_SMTP_PORT
    smtp_user: str = ''
    smtp_password: str = ''
    telegram_bot_enabled: bool = False
    telegram_bot_token: str = ''
    openrouter_api_key: str = ''
    openrouter_default_model: str = ''
    ollama_endpoint_url: str = DEFAULT_OLLAMA_ENDPOINT_URL
    ollama_default_model: str = DEFAULT_OLLAMA_MODEL

    @classmethod
    def from_row(cls, row: AppSettings) -> ResolvedSettingsSnapshot:
        return cls(
            exists=True,
            smtp_host=row.smtp_host,
            smtp_port=row.smtp_port,
            smtp_user=row.smtp_user,
            smtp_password=_read_secret(row, 'smtp_password'),
            telegram_bot_enabled=row.telegram_bot_enabled,
            telegram_bot_token=_read_secret(row, 'telegram_bot_token'),
            openrouter_api_key=_read_secret(row, 'openrouter_api_key'),
            openrouter_default_model=row.openrouter_default_model,
            ollama_endpoint_url=row.ollama_endpoint_url or DEFAULT_OLLAMA_ENDPOINT_URL,
            ollama_default_model=row.ollama_default_model or DEFAULT_OLLAMA_MODEL,
        )

    def smtp_settings(self) -> dict[str, object]:
        if self.exists and self.smtp_host:
            return {
                'host': self.smtp_host,
                'port': self.smtp_port,
                'user': self.smtp_user,
                'password': self.smtp_password,
            }
        return {'host': '', 'port': DEFAULT_SMTP_PORT, 'user': '', 'password': ''}

    def telegram_settings(self) -> dict[str, object]:
        if not self.exists:
            return {'enabled': False, 'token': ''}
        enabled = bool(self.telegram_bot_enabled and self.telegram_bot_token)
        return {'enabled': enabled, 'token': self.telegram_bot_token}

    def openrouter_key(self) -> str:
        return self.openrouter_api_key if self.exists else ''

    def ollama_settings(self) -> dict[str, str]:
        return {'endpoint_url': self.ollama_endpoint_url, 'default_model': self.ollama_default_model}

    def default_model(self) -> str:
        return self.openrouter_default_model if self.exists else ''


def _read_secret(row: AppSettings, field: str) -> str:
    stored = str(getattr(row, field, '') or '')
    if not stored:
        return ''
    return decrypt_secret(stored)


def _load_resolved_snapshot(session: Session) -> ResolvedSettingsSnapshot:
    row = session.get(AppSettings, 1)
    if not row:
        return ResolvedSettingsSnapshot(exists=False)
    return ResolvedSettingsSnapshot.from_row(row)


def _get_resolved_snapshot() -> ResolvedSettingsSnapshot:
    from backend_core.database import run_settings_db

    # Read at each action boundary. A process-local snapshot can outlive a
    # settings update committed by another API child.
    return run_settings_db(_load_resolved_snapshot)


def get_resolved_smtp() -> dict[str, object]:
    return _get_resolved_snapshot().smtp_settings()


def get_resolved_telegram_token() -> str:
    resolved = get_resolved_telegram_settings()
    return str(resolved['token'])


def get_resolved_telegram_settings() -> dict[str, object]:
    return _get_resolved_snapshot().telegram_settings()


def get_resolved_openrouter_key() -> str:
    """Return the saved OpenRouter key, copying the deployment key in when it is empty.

    A key saved from the profile replaces that value and is what chat and Test
    read afterwards.
    """
    from backend_core.database import run_settings_db
    from backend_core.settings_store import ensure_openrouter_key_populated

    return run_settings_db(ensure_openrouter_key_populated)


def get_resolved_ollama_settings() -> dict[str, str]:
    return _get_resolved_snapshot().ollama_settings()


def get_resolved_default_model() -> str:
    return _get_resolved_snapshot().default_model()
