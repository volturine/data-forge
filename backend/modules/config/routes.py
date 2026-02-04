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


@router.get('', response_model=FrontendConfig)
def get_config():
    """Get configuration values for frontend."""
    return FrontendConfig(
        engine_pooling_interval=settings.engine_pooling_interval * 1000,  # Convert to ms
        engine_idle_timeout=settings.engine_idle_timeout,
        job_timeout=settings.job_timeout,
        timezone=settings.timezone,
        normalize_tz=settings.normalize_tz,
    )
