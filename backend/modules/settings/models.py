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

    # Telegram
    telegram_bot_token: str = Field(default='')
    telegram_bot_enabled: bool = Field(default=False)

    # OpenRouter
    openrouter_api_key: str = Field(default='')
    openrouter_default_model: str = Field(default='')

    # OpenAI-compatible
    openai_api_key: str = Field(default='')
    openai_endpoint_url: str = Field(default='https://api.openai.com')
    openai_default_model: str = Field(default='gpt-4o-mini')
    openai_organization_id: str = Field(default='')

    # Ollama
    ollama_endpoint_url: str = Field(default='http://localhost:11434')
    ollama_default_model: str = Field(default='llama3.2')

    # Hugging Face Inference API
    huggingface_api_token: str = Field(default='')
    huggingface_default_model: str = Field(default='google/flan-t5-base')
    env_bootstrap_complete: bool = Field(default=True)

    # Display
    public_idb_debug: bool = Field(default=False)
