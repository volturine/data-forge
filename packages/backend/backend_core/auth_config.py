from __future__ import annotations

import os

from core.config import Settings as SharedSettings
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import DotEnvSettingsSource

_PLACEHOLDER_ENCRYPTION_KEYS = {"your-encryption-key-here"}
_PLACEHOLDER_PASSWORDS = {
    "changeme123",
    "changeme123!",
    "replaceme123",
    "replace-with-strong-password",
}


def _get_env_file() -> str | None:
    if "ENV_FILE" in os.environ:
        env_val = os.environ.get("ENV_FILE", "")
        if env_val:
            return env_val
        return None
    return ".env"


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, env_file_encoding="utf8", extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        env_file = _get_env_file()
        if env_file is None:
            return (init_settings, env_settings, file_secret_settings)
        return (
            init_settings,
            env_settings,
            DotEnvSettingsSource(settings_cls, env_file=env_file, env_file_encoding="utf8"),
            file_secret_settings,
        )

    auth_required: bool = Field(default=False, alias="AUTH_REQUIRED")
    verify_email_address: bool = Field(default=True, alias="VERIFY_EMAIL_ADDRESS")
    default_user_email: str = Field(default="default@example.com", alias="DEFAULT_USER_EMAIL")
    default_user_password: str = Field(default="ChangeMe123", alias="DEFAULT_USER_PASSWORD")
    default_user_name: str = Field(default="Default User", alias="DEFAULT_USER_NAME")
    google_client_id: str = Field(default="", alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(default="", alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(
        default="http://localhost:8000/api/v1/auth/google/callback",
        alias="GOOGLE_REDIRECT_URI",
    )
    github_client_id: str = Field(default="", alias="GITHUB_CLIENT_ID")
    github_client_secret: str = Field(default="", alias="GITHUB_CLIENT_SECRET")
    github_redirect_uri: str = Field(
        default="http://localhost:8000/api/v1/auth/github/callback",
        alias="GITHUB_REDIRECT_URI",
    )
    auth_frontend_url: str = Field(default="http://localhost:5173", alias="AUTH_FRONTEND_URL")
    session_max_age_days: int = Field(default=30, alias="SESSION_MAX_AGE_DAYS")

    @field_validator("default_user_password")
    @classmethod
    def _validate_default_user_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("DEFAULT_USER_PASSWORD must be at least 8 characters long")
        if not any(c.isupper() for c in value):
            raise ValueError("DEFAULT_USER_PASSWORD must contain at least one uppercase letter")
        if not any(c.islower() for c in value):
            raise ValueError("DEFAULT_USER_PASSWORD must contain at least one lowercase letter")
        if not any(c.isdigit() for c in value):
            raise ValueError("DEFAULT_USER_PASSWORD must contain at least one digit")
        return value

    @model_validator(mode="after")
    def _validate_security_requirements(self) -> AuthSettings:
        shared_runtime = SharedSettings()
        encryption_key = shared_runtime.settings_encryption_key.strip()
        prod_mode_enabled = shared_runtime.prod_mode_enabled
        if self.auth_required and prod_mode_enabled and (not encryption_key or encryption_key in _PLACEHOLDER_ENCRYPTION_KEYS):
            raise ValueError("SETTINGS_ENCRYPTION_KEY must be set to a non-placeholder value when AUTH_REQUIRED=true in production")
        if self.auth_required and (not encryption_key or encryption_key in _PLACEHOLDER_ENCRYPTION_KEYS):
            import warnings

            warnings.warn(
                "SETTINGS_ENCRYPTION_KEY is empty while AUTH_REQUIRED=True. "
                "Stored secrets (SMTP passwords, API keys) will not be encrypted. "
                "Set a strong SETTINGS_ENCRYPTION_KEY to protect persisted secrets.",
                stacklevel=2,
            )
        if self.auth_required and prod_mode_enabled and self.default_user_password.strip().lower() in _PLACEHOLDER_PASSWORDS:
            raise ValueError("DEFAULT_USER_PASSWORD must be changed from the production placeholder value")
        return self


settings = AuthSettings()


def reload_settings() -> AuthSettings:
    global settings  # noqa: PLW0603
    settings = AuthSettings()
    return settings
