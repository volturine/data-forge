from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'Polars-FastAPI-Svelte Analysis Platform'
    app_version: str = '1.0.0'

    # Debug mode - enables SQL echo, verbose logging
    debug: bool = False

    # CORS origins - comma-separated list of allowed origins
    cors_origins: str = (
        'http://localhost:3000,http://127.0.0.1:3000,http://0.0.0.0:3000,http://192.168.1.140:3000,http://100.68.183.19:3000'
    )

    database_url: str = 'sqlite+aiosqlite:///./database/app.db'

    upload_dir: Path = Path('./data/uploads')
    results_dir: Path = Path('./data/results')

    max_upload_size: int = 10 * 1024 * 1024 * 1024
    compute_timeout: int = 300

    # Job cleanup TTL in seconds (default 1 hour)
    job_ttl: int = 3600

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins from comma-separated string."""
        return [origin.strip() for origin in self.cors_origins.split(',') if origin.strip()]


settings = Settings()

settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.results_dir.mkdir(parents=True, exist_ok=True)
