import logging

from contracts.settings_models import AppSettings
from core.exceptions import SettingsConfigurationError
from core.secrets import decrypt_secret, encrypt_secret, is_masked_secret, mask_secret
from core.settings_projection import (
    get_resolved_default_model as get_resolved_default_model,
)
from core.settings_projection import (
    get_resolved_huggingface_settings as get_resolved_huggingface_settings,
)
from core.settings_projection import (
    get_resolved_ollama_settings as get_resolved_ollama_settings,
)
from core.settings_projection import (
    get_resolved_openai_settings as get_resolved_openai_settings,
)
from core.settings_projection import (
    get_resolved_openrouter_key as get_resolved_openrouter_key,
)
from core.settings_projection import (
    get_resolved_smtp as get_resolved_smtp,
)
from core.settings_projection import (
    get_resolved_telegram_settings as get_resolved_telegram_settings,
)
from core.settings_projection import (
    get_resolved_telegram_token as get_resolved_telegram_token,
)
from core.settings_projection import (
    invalidate_resolved_settings_cache,
)
from sqlmodel import Session

from backend_core.settings_schemas import SettingsResponse, SettingsUpdate

logger = logging.getLogger(__name__)


def _warn_bootstrap_secret_missing(name: str) -> None:
    logging.warning("Skipping %s bootstrap because SETTINGS_ENCRYPTION_KEY is not set", name)


def _read_secret(row: AppSettings, field: str) -> str:
    stored = str(getattr(row, field, "") or "")
    if not stored:
        return ""
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
    smtp_password = _read_secret(row, "smtp_password")
    telegram_bot_token = _read_secret(row, "telegram_bot_token")
    openrouter_api_key = _read_secret(row, "openrouter_api_key")
    openai_api_key = _read_secret(row, "openai_api_key")
    huggingface_api_token = _read_secret(row, "huggingface_api_token")
    return SettingsResponse(
        smtp_host=row.smtp_host,
        smtp_port=row.smtp_port,
        smtp_user=row.smtp_user,
        smtp_password=mask_secret(smtp_password),
        telegram_bot_token=mask_secret(telegram_bot_token),
        telegram_bot_enabled=row.telegram_bot_enabled,
        openrouter_api_key=mask_secret(openrouter_api_key),
        openrouter_default_model=row.openrouter_default_model,
        openai_api_key=mask_secret(openai_api_key),
        openai_endpoint_url=row.openai_endpoint_url,
        openai_default_model=row.openai_default_model,
        openai_organization_id=row.openai_organization_id,
        ollama_endpoint_url=row.ollama_endpoint_url,
        ollama_default_model=row.ollama_default_model,
        huggingface_api_token=mask_secret(huggingface_api_token),
        huggingface_default_model=row.huggingface_default_model,
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
            _write_secret(row, "smtp_password", app_settings.smtp_password)
            changed = True
        except SettingsConfigurationError:
            bootstrap_complete = False
            _warn_bootstrap_secret_missing("SMTP password")
    if not row.telegram_bot_token and app_settings.telegram_bot_token:
        try:
            _write_secret(row, "telegram_bot_token", app_settings.telegram_bot_token)
            changed = True
        except SettingsConfigurationError:
            bootstrap_complete = False
            _warn_bootstrap_secret_missing("Telegram token")
    if not row.telegram_bot_enabled and app_settings.telegram_bot_enabled:
        row.telegram_bot_enabled = app_settings.telegram_bot_enabled
        changed = True
    if not row.openrouter_api_key and app_settings.openrouter_api_key:
        try:
            _write_secret(row, "openrouter_api_key", app_settings.openrouter_api_key)
            changed = True
        except SettingsConfigurationError:
            bootstrap_complete = False
            _warn_bootstrap_secret_missing("OpenRouter key")
    if not row.openrouter_default_model and app_settings.openrouter_default_model:
        row.openrouter_default_model = app_settings.openrouter_default_model
        changed = True
    if not row.openai_api_key and app_settings.openai_api_key:
        try:
            _write_secret(row, "openai_api_key", app_settings.openai_api_key)
            changed = True
        except SettingsConfigurationError:
            bootstrap_complete = False
            _warn_bootstrap_secret_missing("OpenAI key")
    if not row.openai_endpoint_url and app_settings.openai_base_url:
        row.openai_endpoint_url = app_settings.openai_base_url
        changed = True
    if not row.openai_default_model and app_settings.openai_default_model:
        row.openai_default_model = app_settings.openai_default_model
        changed = True
    if not row.openai_organization_id and app_settings.openai_organization_id:
        row.openai_organization_id = app_settings.openai_organization_id
        changed = True
    if not row.ollama_endpoint_url and app_settings.ollama_base_url:
        row.ollama_endpoint_url = app_settings.ollama_base_url
        changed = True
    if not row.ollama_default_model and app_settings.ollama_default_model:
        row.ollama_default_model = app_settings.ollama_default_model
        changed = True
    if not row.huggingface_api_token and app_settings.huggingface_api_token:
        try:
            _write_secret(row, "huggingface_api_token", app_settings.huggingface_api_token)
            changed = True
        except SettingsConfigurationError:
            bootstrap_complete = False
            _warn_bootstrap_secret_missing("Hugging Face token")
    if not row.huggingface_default_model and app_settings.huggingface_default_model:
        row.huggingface_default_model = app_settings.huggingface_default_model
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

    if data.smtp_host is not None:
        row.smtp_host = data.smtp_host
    if data.smtp_port is not None:
        row.smtp_port = data.smtp_port
    if data.smtp_user is not None:
        row.smtp_user = data.smtp_user
    smtp_password = _resolve_updated_secret(row, "smtp_password", data.smtp_password)
    telegram_bot_token = _resolve_updated_secret(row, "telegram_bot_token", data.telegram_bot_token)
    openrouter_api_key = _resolve_updated_secret(row, "openrouter_api_key", data.openrouter_api_key)
    openai_api_key = _resolve_updated_secret(row, "openai_api_key", data.openai_api_key)
    huggingface_api_token = _resolve_updated_secret(row, "huggingface_api_token", data.huggingface_api_token)
    _write_secret(row, "smtp_password", smtp_password)
    _write_secret(row, "telegram_bot_token", telegram_bot_token)
    _write_secret(row, "openrouter_api_key", openrouter_api_key)
    _write_secret(row, "openai_api_key", openai_api_key)
    _write_secret(row, "huggingface_api_token", huggingface_api_token)
    if data.telegram_bot_enabled is not None:
        row.telegram_bot_enabled = data.telegram_bot_enabled
    if data.openrouter_default_model is not None:
        row.openrouter_default_model = data.openrouter_default_model
    if data.openai_endpoint_url is not None:
        row.openai_endpoint_url = data.openai_endpoint_url
    if data.openai_default_model is not None:
        row.openai_default_model = data.openai_default_model
    if data.openai_organization_id is not None:
        row.openai_organization_id = data.openai_organization_id
    if data.ollama_endpoint_url is not None:
        row.ollama_endpoint_url = data.ollama_endpoint_url
    if data.ollama_default_model is not None:
        row.ollama_default_model = data.ollama_default_model
    if data.huggingface_default_model is not None:
        row.huggingface_default_model = data.huggingface_default_model
    row.env_bootstrap_complete = True
    if data.public_idb_debug is not None:
        row.public_idb_debug = data.public_idb_debug

    session.commit()
    session.refresh(row)
    invalidate_resolved_settings_cache()
    return _masked_settings_response(row)
