"""Configuration and utility endpoints."""

import uuid

from fastapi import Depends, Query
from pydantic import BaseModel
from sqlmodel import Session

from core.config import settings
from core.database import get_settings_db
from core.error_handlers import handle_errors
from modules.mcp.router import MCPRouter
from modules.settings.service import get_settings

router = MCPRouter(prefix='/config', tags=['config'])


class FrontendConfig(BaseModel):
    """Configuration values exposed to frontend."""

    engine_pooling_interval: int  # milliseconds
    engine_idle_timeout: int  # seconds
    job_timeout: int  # seconds
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
def get_config(session: Session = Depends(get_settings_db)) -> FrontendConfig:
    """Get application configuration: timeouts, logging settings, feature flags, and default namespace."""
    db_settings = get_settings(session)
    return FrontendConfig(
        engine_pooling_interval=settings.engine_pooling_interval * 1000,  # Convert to ms
        engine_idle_timeout=settings.engine_idle_timeout,
        job_timeout=settings.job_timeout,
        timezone=settings.timezone,
        normalize_tz=settings.normalize_tz,
        log_client_batch_size=settings.log_client_batch_size,
        log_client_flush_interval_ms=settings.log_client_flush_interval_ms,
        log_client_dedupe_window_ms=settings.log_client_dedupe_window_ms,
        log_client_flush_cooldown_ms=settings.log_client_flush_cooldown_ms,
        log_queue_max_size=settings.log_queue_max_size,
        public_idb_debug=db_settings.public_idb_debug,
        auth_required=settings.auth_required,
        smtp_enabled=bool(db_settings.smtp_host and db_settings.smtp_user),
        telegram_enabled=bool(db_settings.telegram_bot_enabled and db_settings.telegram_bot_token),
        default_namespace=settings.default_namespace,
    )
