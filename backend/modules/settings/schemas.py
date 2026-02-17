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
    public_idb_debug: bool


class SettingsUpdate(BaseModel):
    """Settings update payload from the frontend."""

    smtp_host: str = ''
    smtp_port: int = 587
    smtp_user: str = ''
    smtp_password: str = ''
    telegram_bot_token: str = ''
    telegram_bot_enabled: bool = False
    public_idb_debug: bool = False


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
