from pathlib import Path

from pydantic import Field, field_validator
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
        env_file_encoding='utf-8',
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
    compute_timeout: int = Field(default=300, alias='COMPUTE_TIMEOUT')

    # Job cleanup TTL in seconds (default 1 hour)
    job_ttl: int = Field(default=3600, alias='JOB_TTL')

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins from comma-separated string."""
        return [origin.strip() for origin in self.cors_origins.split(',') if origin.strip()]

    @field_validator('upload_dir', 'results_dir', 'exports_dir', mode='before')
    @classmethod
    def _ensure_dirs(cls, value: Path) -> Path:
        return _resolve_dir(value)


settings = Settings()
