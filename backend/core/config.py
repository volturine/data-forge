import os
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Root data directory (relative to project root, not backend/)
DATA_DIR = Path(__file__).parent.parent.parent / 'data'


def _resolve_dir(value: Path | str) -> Path:
    """Ensure a directory path exists and return it."""
    path_value = Path(value)
    path_value.mkdir(parents=True, exist_ok=True)
    return path_value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf8',
        extra='ignore',
    )

    app_name: str = 'Polars-FastAPI-Svelte Analysis Platform'
    app_version: str = '1.0.0'

    # Debug mode - enables SQL echo, verbose logging
    debug: bool = False

    # CORS origins - comma-separated list of allowed origins
    cors_origins: str = (
        'http://localhost:3000,http://127.0.0.1:3000,http://0.0.0.0:3000,http://192.168.1.140:3000,http://100.68.183.19:3000'
    )

    database_url: str = 'sqlite+aiosqlite:///./database/app.db'

    # All data directories under root data/ folder
    upload_dir: Path = Field(default=DATA_DIR / 'uploads', alias='UPLOAD_DIR')
    results_dir: Path = Field(default=DATA_DIR / 'results', alias='RESULTS_DIR')
    exports_dir: Path = Field(default=DATA_DIR / 'exports', alias='EXPORTS_DIR')

    max_upload_size: int = Field(default=10 * 1024 * 1024 * 1024, alias='MAX_UPLOAD_SIZE')

    # Engine idle timeout in seconds (default 5 minutes)
    # Engines will be terminated after this duration of inactivity (reset on save)
    engine_idle_timeout: int = Field(default=300, alias='ENGINE_IDLE_TIMEOUT')

    # Engine pooling interval in seconds (default 5 seconds)
    # How often to check engine states and cleanup idle engines
    engine_pooling_interval: int = Field(default=5, alias='ENGINE_POOLING_INTERVAL')

    # Job execution timeout in seconds (default 5 minutes)
    # Jobs that exceed this duration will be terminated
    job_timeout: int = Field(default=300, alias='JOB_TIMEOUT')

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

    # Maximum connections per worker
    worker_connections: int = Field(default=1000, alias='WORKER_CONNECTIONS')

    # Logging level (debug, info, warning, error)
    log_level: str = Field(default='info', alias='LOG_LEVEL')

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins from comma-separated string."""
        return [origin.strip() for origin in self.cors_origins.split(',') if origin.strip()]

    @field_validator('upload_dir', 'results_dir', 'exports_dir', mode='before')
    @classmethod
    def _ensure_dirs(cls, value: Path) -> Path:
        return _resolve_dir(value)

    @field_validator('engine_idle_timeout', 'job_timeout', 'engine_pooling_interval')
    @classmethod
    def _validate_positive_timeout(cls, value: int, info) -> int:
        """Ensure timeout values are positive."""
        if value <= 0:
            raise ValueError(f'{info.field_name} must be positive, got {value}')
        return value

    @field_validator('max_upload_size')
    @classmethod
    def _validate_upload_size(cls, value: int) -> int:
        """Ensure upload size is reasonable."""
        if value < 1024:  # At least 1KB
            raise ValueError(f'max_upload_size must be at least 1024 bytes, got {value}')
        return value

    @field_validator('polars_max_threads', 'polars_max_memory_mb', 'polars_streaming_chunk_size')
    @classmethod
    def _validate_non_negative(cls, value: int, info) -> int:
        """Ensure Polars resource values are non-negative."""
        if value < 0:
            raise ValueError(f'{info.field_name} must be non-negative (0 = unlimited/auto), got {value}')
        return value

    @field_validator('max_concurrent_engines')
    @classmethod
    def _validate_max_engines(cls, value: int) -> int:
        """Ensure max concurrent engines is reasonable."""
        if value < 1:
            raise ValueError(f'max_concurrent_engines must be at least 1, got {value}')
        if value > 100:
            raise ValueError(f'max_concurrent_engines must be at most 100, got {value}')
        return value

    @field_validator('workers')
    @classmethod
    def _validate_workers(cls, value: int) -> int:
        """Ensure workers count is valid."""
        if value < 0:
            raise ValueError(f'workers must be non-negative (0 = auto), got {value}')
        if value > 32:
            raise ValueError(f'workers must be at most 32, got {value}')
        return value

    @field_validator('log_level')
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        """Ensure log level is valid."""
        valid_levels = ['debug', 'info', 'warning', 'error', 'critical']
        if value.lower() not in valid_levels:
            raise ValueError(f'log_level must be one of {valid_levels}, got {value}')
        return value.lower()

    @model_validator(mode='after')
    def _validate_directories_writable(self):
        """Ensure all directories are writable."""
        for dir_name in ['upload_dir', 'results_dir', 'exports_dir']:
            dir_path = getattr(self, dir_name)
            if not os.access(dir_path, os.W_OK):
                raise ValueError(f'{dir_name} is not writable: {dir_path}')
        return self


settings = Settings()
