"""Configuration and utility endpoints."""

from __future__ import annotations

import uuid

from fastapi import Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from backend_core.auth_config import settings as auth_settings
from backend_core.config import settings
from backend_core.error_handlers import handle_errors
from backend_core.settings_schemas import SettingsResponse
from backend_core.settings_store import get_settings
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix='/config', tags=['config'])


class FrontendConfig(BaseModel):
    """Configuration values exposed to frontend."""

    timezone: str
    normalize_tz: bool
    log_client_batch_size: int
    log_client_flush_interval_ms: int
    log_client_dedupe_window_ms: int
    log_client_flush_cooldown_ms: int
    log_queue_max_size: int
    public_idb_debug: bool
    smtp_enabled: bool
    telegram_enabled: bool
    default_namespace: str
    auth_required: bool
    verify_email_address: bool


class UuidResponse(BaseModel):
    """One or more generated UUID v4 values."""

    uuids: list[str]


@router.get('/uuid', response_model=UuidResponse, mcp=True)
@handle_errors(operation='generate UUID')
def generate_uuid(count: int = Query(default=1, ge=1, le=20)) -> UuidResponse:
    """Generate UUID v4 values for use in analysis creation (output.result_id) or any UUID field.

    Pass count=N to generate multiple UUIDs in one call (max 20).
    """
    return UuidResponse(uuids=[str(uuid.uuid4()) for _ in range(count)])


@router.get('', response_model=FrontendConfig, mcp=True)
@handle_errors(operation='get config')
async def get_config() -> FrontendConfig:
    """Get application configuration: runtime settings, logging settings, feature flags, and default namespace."""
    from backend_core.database import run_settings_db

    db_settings = await run_in_threadpool(run_settings_db, get_settings)
    return _build_frontend_config(db_settings)


def _build_frontend_config(db_settings: SettingsResponse) -> FrontendConfig:
    """Build the frontend configuration from current runtime and persisted settings."""
    return FrontendConfig(
        timezone=settings.timezone,
        normalize_tz=settings.normalize_tz,
        log_client_batch_size=settings.log_client_batch_size,
        log_client_flush_interval_ms=settings.log_client_flush_interval_ms,
        log_client_dedupe_window_ms=settings.log_client_dedupe_window_ms,
        log_client_flush_cooldown_ms=settings.log_client_flush_cooldown_ms,
        log_queue_max_size=settings.log_queue_max_size,
        public_idb_debug=db_settings.public_idb_debug,
        auth_required=auth_settings.auth_required,
        smtp_enabled=bool(db_settings.smtp_host and db_settings.smtp_user),
        telegram_enabled=bool(db_settings.telegram_bot_enabled and db_settings.telegram_bot_token),
        default_namespace=settings.default_namespace,
        verify_email_address=auth_settings.verify_email_address,
    )
