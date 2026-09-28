"""Configuration and utility endpoints."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from threading import Lock

from fastapi import Query
from pydantic import BaseModel

from backend_core.auth_config import settings as auth_settings
from backend_core.config import settings
from backend_core.error_handlers import handle_errors
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


_CONFIG_CACHE_TTL: float = 10.0


class FrontendConfigCache:
    def __init__(self, ttl: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl
        self._clock = clock
        self._config: FrontendConfig | None = None
        self._expires_at = 0.0
        self._state_lock = Lock()
        self._generation = 0
        self._refresh_task: asyncio.Task[FrontendConfig] | None = None

    async def get_or_create(self, create: Callable[[], FrontendConfig]) -> FrontendConfig:
        with self._state_lock:
            if self._config is not None and self._clock() < self._expires_at:
                return self._config

            task = self._refresh_task
            if task is None:
                task = asyncio.create_task(self._refresh(create))
                task.add_done_callback(self._consume_refresh_exception)
                self._refresh_task = task

        # A cancelled request must not cancel a config refresh shared by other
        # browser tabs. Followers await the same task without occupying threads.
        return await asyncio.shield(task)

    async def _refresh(self, create: Callable[[], FrontendConfig]) -> FrontendConfig:
        task = asyncio.current_task()
        try:
            while True:
                with self._state_lock:
                    generation = self._generation

                config = await asyncio.to_thread(create)

                with self._state_lock:
                    if generation != self._generation:
                        continue
                    self._config = config
                    self._expires_at = self._clock() + self._ttl
                    if self._refresh_task is task:
                        self._refresh_task = None
                    return config
        except BaseException:
            with self._state_lock:
                if self._refresh_task is task:
                    self._refresh_task = None
            raise

    @staticmethod
    def _consume_refresh_exception(task: asyncio.Task[FrontendConfig]) -> None:
        if not task.cancelled():
            task.exception()

    def invalidate(self) -> None:
        with self._state_lock:
            self._generation += 1
            self._config = None
            self._expires_at = 0.0


_frontend_config_cache = FrontendConfigCache(_CONFIG_CACHE_TTL)


def invalidate_config_cache() -> None:
    """Clear cached config so the next request rebuilds it."""
    _frontend_config_cache.invalidate()


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
    return await _frontend_config_cache.get_or_create(_build_frontend_config)


def _build_frontend_config() -> FrontendConfig:
    """Build the frontend configuration from current runtime and persisted settings."""
    from backend_core.database import run_settings_db

    db_settings = run_settings_db(get_settings)
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
