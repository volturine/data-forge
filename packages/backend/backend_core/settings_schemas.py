"""Backend-owned settings API schemas."""

from pydantic import BaseModel, ConfigDict


class SettingsResponse(BaseModel):
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
    to: str


class TestTelegramRequest(BaseModel):
    chat_id: str


class TestResult(BaseModel):
    success: bool
    message: str


class TelegramChat(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chat_id: str
    title: str


class DetectTelegramResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    success: bool
    message: str
    chats: list[TelegramChat] = []


class DetectCustomBotRequest(BaseModel):
    bot_token: str
