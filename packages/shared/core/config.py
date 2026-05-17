import os
import tempfile
from pathlib import Path
from zoneinfo import available_timezones

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import DotEnvSettingsSource

# (field_name, min_inclusive, max_inclusive) — None means no bound
_NUMERIC_CONSTRAINTS: list[tuple[str, int | None, int | None]] = [
    ('port', 1, 65535),
    ('scheduler_check_interval', 1, None),
    ('lock_ttl_seconds', 1, None),
    ('lock_heartbeat_interval_seconds', 1, None),
    ('polars_max_threads', 0, None),
    ('polars_max_memory_mb', 0, None),
    ('polars_streaming_chunk_size', 0, None),
    ('max_concurrent_engines', 1, 100),
    ('workers', 0, 32),
    ('compute_request_concurrency', 1, 100),
    ('build_worker_min_processes', 0, 100),
    ('build_worker_max_processes', 0, 100),
    ('build_worker_idle_exit_seconds', 1, None),
    ('log_queue_max_size', 1, None),
    ('log_max_body_size', 0, None),
    ('log_client_batch_size', 1, None),
    ('log_client_flush_interval_ms', 1, None),
    ('log_client_dedupe_window_ms', 1, None),
    ('log_client_flush_cooldown_ms', 1, None),
    ('upload_max_file_size_bytes', 0, None),
]
_PLACEHOLDER_ENCRYPTION_KEYS = {'your-encryption-key-here'}
_PLACEHOLDER_PASSWORDS = {'changeme123', 'changeme123!', 'replaceme123', 'replace-with-strong-password'}


def _default_data_dir() -> Path:
    """Return a stable writable default data directory when DATA_DIR is unset."""
    return Path(tempfile.gettempdir()) / 'data-forge'


def _get_env_file() -> str | None:
    if 'ENV_FILE' in os.environ:
        env_val = os.environ.get('ENV_FILE', '')
        if env_val:
            return env_val
        return None
    return '.env'


def _resolve_dir(value: Path | str) -> Path:
    """Ensure a directory path exists and return it."""
    path_value = Path(value)
    path_value.mkdir(parents=True, exist_ok=True)
    return path_value


def _resolve_file_parent(value: Path | str) -> Path:
    """Ensure the parent directory for a file path exists and return it."""
    path_value = Path(value)
    path_value.parent.mkdir(parents=True, exist_ok=True)
    return path_value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, env_file_encoding='utf8', extra='ignore')

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        env_file = _get_env_file()
        if env_file is None:
            return (init_settings, env_settings, file_secret_settings)
        return (init_settings, env_settings, DotEnvSettingsSource(settings_cls, env_file=env_file, env_file_encoding='utf8'), file_secret_settings)

    app_name: str = 'Data-Forge Analysis Platform'
    app_version: str = '1.0.0'

    # Debug mode - enables SQL echo, verbose logging
    debug: bool = False
    prod_mode_enabled: bool = Field(default=False, alias='PROD_MODE_ENABLED')
    port: int = Field(default=8000, alias='PORT')

    # CORS origins - comma-separated list of allowed origins
    cors_origins: str = 'http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173'

    data_dir: Path = Field(default_factory=_default_data_dir, alias='DATA_DIR')
    database_url: str = ''
    distributed_runtime_enabled: bool = Field(default=False, alias='DISTRIBUTED_RUNTIME_ENABLED')
    database_pool_size: int = Field(default=10, alias='DATABASE_POOL_SIZE')
    database_max_overflow: int = Field(default=20, alias='DATABASE_MAX_OVERFLOW')
    database_pool_timeout: int = Field(default=30, alias='DATABASE_POOL_TIMEOUT')
    default_namespace: str = Field(default='default', alias='DEFAULT_NAMESPACE')

    upload_chunk_size: int = Field(default=5 * 1024 * 1024, alias='UPLOAD_CHUNK_SIZE')
    upload_max_file_size_bytes: int = Field(default=2 * 1024 * 1024 * 1024, alias='UPLOAD_MAX_FILE_SIZE_BYTES')

    # Scheduler check interval in seconds (default 60 seconds)
    # How often to check for schedules that need to run
    scheduler_check_interval: int = Field(default=60, alias='SCHEDULER_CHECK_INTERVAL')

    # Resource lock defaults
    lock_ttl_seconds: int = Field(default=30, alias='LOCK_TTL_SECONDS')
    lock_heartbeat_interval_seconds: int = Field(default=10, alias='LOCK_HEARTBEAT_INTERVAL_SECONDS')

    # Polars Engine Resource Configuration
    # Maximum threads per engine (0 = auto-detect, uses all available cores)
    polars_max_threads: int = Field(default=0, alias='POLARS_MAX_THREADS')

    # Memory limit per engine in MB (0 = unlimited)
    polars_max_memory_mb: int = Field(default=0, alias='POLARS_MAX_MEMORY_MB')

    # Streaming chunk size for large datasets (0 = auto)
    polars_streaming_chunk_size: int = Field(default=0, alias='POLARS_STREAMING_CHUNK_SIZE')

    # Maximum number of concurrent engines allowed
    max_concurrent_engines: int = Field(default=10, alias='MAX_CONCURRENT_ENGINES')

    # Worker Configuration
    # Number of Gunicorn/Uvicorn workers (0 = auto: 2 * cores + 1)
    workers: int = Field(default=1, alias='WORKERS')
    compute_request_concurrency: int = Field(default=4, alias='COMPUTE_REQUEST_CONCURRENCY')
    embedded_build_worker_enabled: bool = Field(default=False, alias='EMBEDDED_BUILD_WORKER_ENABLED')

    # Maximum connections per worker
    worker_connections: int = Field(default=1000, alias='WORKER_CONNECTIONS')

    # Dynamic build worker pool
    build_worker_min_processes: int = Field(default=0, alias='BUILD_WORKER_MIN_PROCESSES')
    build_worker_max_processes: int = Field(default=10, alias='BUILD_WORKER_MAX_PROCESSES')
    build_worker_idle_exit_seconds: int = Field(default=30, alias='BUILD_WORKER_IDLE_EXIT_SECONDS')

    # Logging level (debug, info, warning, error)
    log_level: str = Field(default='info', alias='LOG_LEVEL')
    sql_echo: bool = Field(default=False, alias='SQL_ECHO')
    uvicorn_access_log: bool = Field(default=True, alias='UVICORN_ACCESS_LOG')

    # Timezone handling
    timezone: str = Field(default='UTC', alias='TIMEZONE')

    # Normalize datetime values to TIMEZONE
    normalize_tz: bool = Field(default=False, alias='NORMALIZE_TZ')

    # Client audit log configuration (frontend)
    # Batch size per flush request
    log_client_batch_size: int = Field(default=20, alias='LOG_CLIENT_BATCH_SIZE')

    # Flush interval in milliseconds
    log_client_flush_interval_ms: int = Field(default=5000, alias='LOG_CLIENT_FLUSH_INTERVAL_MS')

    # Dedupe window in milliseconds for repeated events
    log_client_dedupe_window_ms: int = Field(default=500, alias='LOG_CLIENT_DEDUPE_WINDOW_MS')

    # Cooldown in milliseconds before logging repeated flush failures
    log_client_flush_cooldown_ms: int = Field(default=3000, alias='LOG_CLIENT_FLUSH_COOLDOWN_MS')

    # Server-side log flush interval in seconds
    log_flush_interval_seconds: int = Field(default=5, alias='LOG_FLUSH_INTERVAL_SECONDS')

    # Max queued log batches before dropping
    log_queue_max_size: int = Field(default=2000, alias='LOG_QUEUE_MAX_SIZE')

    # Queue overflow behavior: 'block' or 'drop' (default)
    log_queue_overflow: str = Field(default='drop', alias='LOG_QUEUE_OVERFLOW')

    # Max body size to log in bytes (default 64KB, 0 = unlimited)
    log_max_body_size: int = Field(default=64 * 1024, alias='LOG_MAX_BODY_SIZE')

    # Frontend debug panels
    public_idb_debug: bool = Field(default=False, alias='PUBLIC_IDB_DEBUG')

    settings_encryption_key: str = Field(default='', alias='SETTINGS_ENCRYPTION_KEY')

    # AI configuration
    ollama_base_url: str = Field(default='http://localhost:11434', alias='OLLAMA_BASE_URL')
    ollama_default_model: str = Field(default='llama3.2', alias='OLLAMA_DEFAULT_MODEL')
    openai_api_key: str = Field(default='', alias='OPENAI_API_KEY')
    openai_base_url: str = Field(default='https://api.openai.com', alias='OPENAI_BASE_URL')
    openai_default_model: str = Field(default='gpt-4o-mini', alias='OPENAI_DEFAULT_MODEL')
    openai_organization_id: str = Field(default='', alias='OPENAI_ORGANIZATION_ID')
    huggingface_api_token: str = Field(default='', alias='HUGGINGFACE_API_TOKEN')
    huggingface_default_model: str = Field(default='google/flan-t5-base', alias='HUGGINGFACE_DEFAULT_MODEL')
    huggingface_api_base_url: str = Field(default='https://api-inference.huggingface.co', alias='HUGGINGFACE_API_BASE_URL')

    # DB-persisted settings — seeded into app_settings on first run if the DB field is empty.
    # Users may later override these via the UI; ENV values are never re-applied after that.
    smtp_host: str = Field(default='', alias='SMTP_HOST')
    smtp_port: int = Field(default=587, alias='SMTP_PORT')
    smtp_user: str = Field(default='', alias='SMTP_USER')
    smtp_password: str = Field(default='', alias='SMTP_PASSWORD')
    telegram_bot_token: str = Field(default='', alias='TELEGRAM_BOT_TOKEN')
    telegram_bot_enabled: bool = Field(default=False, alias='TELEGRAM_BOT_ENABLED')
    openrouter_api_key: str = Field(default='', alias='OPENROUTER_API_KEY')
    openrouter_default_model: str = Field(default='', alias='OPENROUTER_DEFAULT_MODEL')
    openai_default_model_db: str = Field(default='', alias='OPENAI_DEFAULT_MODEL_DB')
    openai_endpoint_url_db: str = Field(default='', alias='OPENAI_ENDPOINT_URL_DB')
    openai_organization_id_db: str = Field(default='', alias='OPENAI_ORGANIZATION_ID_DB')
    ollama_endpoint_url_db: str = Field(default='', alias='OLLAMA_ENDPOINT_URL_DB')
    ollama_default_model_db: str = Field(default='', alias='OLLAMA_DEFAULT_MODEL_DB')
    huggingface_default_model_db: str = Field(default='', alias='HUGGINGFACE_DEFAULT_MODEL_DB')

    trusted_proxy_hops: int = Field(default=0, alias='TRUSTED_PROXY_HOPS')

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins from comma-separated string."""
        return [origin.strip() for origin in self.cors_origins.split(',') if origin.strip()]

    @field_validator('data_dir', mode='before')
    @classmethod
    def _ensure_dirs(cls, value: Path) -> Path:
        return _resolve_dir(value)

    @field_validator('upload_chunk_size')
    @classmethod
    def _validate_upload_chunk_size(cls, value: int) -> int:
        if value < 1024:
            raise ValueError(f'upload_chunk_size must be at least 1024 bytes, got {value}')
        if value > 100 * 1024 * 1024:
            raise ValueError(f'upload_chunk_size must be at most 100MB, got {value}')
        return value

    @field_validator('log_level')
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        valid_levels = ['debug', 'info', 'warning', 'error', 'critical']
        if value.lower() not in valid_levels:
            raise ValueError(f'log_level must be one of {valid_levels}, got {value}')
        return value.lower()

    @field_validator('database_url')
    @classmethod
    def _validate_database_url(cls, value: str, _info) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError('DATABASE_URL must be set to a PostgreSQL connection string')
        lower = normalized.lower()
        if not (lower.startswith('postgresql://') or lower.startswith('postgresql+')):
            raise ValueError('DATABASE_URL must be a PostgreSQL connection string')
        return normalized

    @field_validator('timezone')
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        zones = available_timezones()
        if value not in zones:
            raise ValueError(f'timezone must be a valid IANA timezone, got {value}')
        return value

    @field_validator('log_queue_overflow')
    @classmethod
    def _validate_log_queue_overflow(cls, value: str) -> str:
        valid = ['block', 'drop']
        if value.lower() not in valid:
            raise ValueError(f'log_queue_overflow must be one of {valid}, got {value}')
        return value.lower()

    @field_validator('trusted_proxy_hops')
    @classmethod
    def _validate_trusted_proxy_hops(cls, value: int) -> int:
        if value < 0:
            raise ValueError('TRUSTED_PROXY_HOPS must be >= 0')
        return value

    @model_validator(mode='after')
    def _validate_numeric_constraints(self) -> 'Settings':
        for field_name, min_val, max_val in _NUMERIC_CONSTRAINTS:
            value = getattr(self, field_name)
            if min_val is not None and value < min_val:
                raise ValueError(f'{field_name} must be >= {min_val}, got {value}')
            if max_val is not None and value > max_val:
                raise ValueError(f'{field_name} must be <= {max_val}, got {value}')
        return self

    @model_validator(mode='after')
    def _validate_directories_writable(self) -> 'Settings':
        """Ensure all directories are writable."""
        for dir_name in ['data_dir']:
            dir_path = getattr(self, dir_name)
            if not os.access(dir_path, os.W_OK):
                raise ValueError(f'{dir_name} is not writable: {dir_path}')
        return self

    @model_validator(mode='after')
    def _validate_lock_intervals(self) -> 'Settings':
        if self.lock_heartbeat_interval_seconds >= self.lock_ttl_seconds:
            raise ValueError('lock_heartbeat_interval_seconds must be < lock_ttl_seconds')
        return self

    @model_validator(mode='after')
    def _validate_runtime_mode(self) -> 'Settings':
        if self.distributed_runtime_enabled and self.embedded_build_worker_enabled:
            raise ValueError('EMBEDDED_BUILD_WORKER_ENABLED cannot be enabled with DISTRIBUTED_RUNTIME_ENABLED')
        if self.build_worker_min_processes > self.build_worker_max_processes:
            raise ValueError('BUILD_WORKER_MIN_PROCESSES must be <= BUILD_WORKER_MAX_PROCESSES')
        if self.build_worker_max_processes > self.max_concurrent_engines:
            raise ValueError('BUILD_WORKER_MAX_PROCESSES must be <= MAX_CONCURRENT_ENGINES')
        return self


settings = Settings()
