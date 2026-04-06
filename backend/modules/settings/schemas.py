"""Settings schemas — Pydantic in, Pydantic out."""

from pydantic import BaseModel, ConfigDict


class SettingsResponse(BaseModel):
    """Settings returned to the frontend."""

    model_config = ConfigDict(from_attributes=True)

    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    telegram_bot_token: str
    telegram_bot_enabled: bool
    openrouter_api_key: str
    openrouter_default_model: str
    openai_api_key: str
    openai_endpoint_url: str
    openai_default_model: str
    openai_organization_id: str
    ollama_endpoint_url: str
    ollama_default_model: str
    huggingface_api_token: str
    huggingface_default_model: str
    public_idb_debug: bool


class SettingsUpdate(BaseModel):
    """Settings update payload from the frontend."""

    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None
    telegram_bot_token: str | None = None
    telegram_bot_enabled: bool | None = None
    openrouter_api_key: str | None = None
    openrouter_default_model: str | None = None
    openai_api_key: str | None = None
    openai_endpoint_url: str | None = None
    openai_default_model: str | None = None
    openai_organization_id: str | None = None
    ollama_endpoint_url: str | None = None
    ollama_default_model: str | None = None
    huggingface_api_token: str | None = None
    huggingface_default_model: str | None = None
    public_idb_debug: bool | None = None


class TestSmtpRequest(BaseModel):
    """Request to send a test email."""

    to: str


class TestTelegramRequest(BaseModel):
    """Request to send a test Telegram message."""

    chat_id: str


class TestResult(BaseModel):
    """Result of a test notification."""

    success: bool
    message: str


class TelegramChat(BaseModel):
    """A detected Telegram chat from getUpdates."""

    model_config = ConfigDict(from_attributes=True)

    chat_id: str
    title: str


class DetectTelegramResponse(BaseModel):
    """Response from the detect-telegram-chat endpoint."""

    model_config = ConfigDict(from_attributes=True)

    success: bool
    message: str
    chats: list[TelegramChat] = []


class DetectCustomBotRequest(BaseModel):
    """Request to detect chat_id from a custom bot token."""

    bot_token: str
