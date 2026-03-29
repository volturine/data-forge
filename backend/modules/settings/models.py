"""Settings model for runtime-editable configuration."""

from sqlmodel import Field, SQLModel


class AppSettings(SQLModel, table=True):
    """Singleton row storing runtime-editable notification and display settings."""

    __tablename__ = 'app_settings'  # type: ignore[assignment]

    id: int = Field(default=1, primary_key=True)

    # SMTP
    smtp_host: str = Field(default='')
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default='')
    smtp_password: str = Field(default='')
    smtp_password_encrypted: str = Field(default='')

    # Telegram
    telegram_bot_token: str = Field(default='')
    telegram_bot_enabled: bool = Field(default=False)

    # OpenRouter
    openrouter_api_key: str = Field(default='')
    openrouter_default_model: str = Field(default='')
    env_bootstrap_complete: bool = Field(default=True)

    # Display
    public_idb_debug: bool = Field(default=False)
