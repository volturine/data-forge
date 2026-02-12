"""Configuration endpoints for frontend."""

from fastapi import APIRouter
from pydantic import BaseModel

from core.config import settings

router = APIRouter(prefix='/config', tags=['config'])


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


@router.get('', response_model=FrontendConfig)
def get_config():
    """Get configuration values for frontend."""
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
        public_idb_debug=settings.public_idb_debug,
    )
