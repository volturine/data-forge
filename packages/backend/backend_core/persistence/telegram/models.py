"""Telegram subscriber and listener persistence models."""

import datetime as dt

from sqlalchemy import JSON, BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlmodel import Field, SQLModel


class TelegramSubscriber(SQLModel, table=True):  # type: ignore[call-arg]
    """A Telegram chat that subscribed via /subscribe command."""

    __tablename__ = 'telegram_subscribers'  # type: ignore[assignment]

    id: int | None = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    chat_id: str = Field(sa_column=Column(String, nullable=False))
    title: str = Field(default='', sa_column=Column(String, nullable=False, server_default=''))
    bot_token: str = Field(sa_column=Column(String, nullable=False))
    is_active: bool = Field(default=True)
    subscribed_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class TelegramListener(SQLModel, table=True):  # type: ignore[call-arg]
    """Maps a subscriber to a datasource they want build notifications for."""

    __tablename__ = 'telegram_listeners'  # type: ignore[assignment]

    id: int | None = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    subscriber_id: int = Field(sa_column=Column(Integer, ForeignKey('telegram_subscribers.id', ondelete='CASCADE'), nullable=False))
    datasource_id: str = Field(sa_column=Column(String, nullable=False))


class TelegramPollOffset(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'telegram_poll_offsets'
    __table_args__ = (CheckConstraint('next_update_id >= 0', name='ck_telegram_poll_offset_nonnegative'),)

    token_sha256: str = Field(sa_column=Column(String(64), primary_key=True))
    next_update_id: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default='0'))
    chats_json: list[dict[str, str]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False, server_default='[]'))
    coordinator_generation: int = Field(sa_column=Column(BigInteger, nullable=False))
    updated_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class TelegramDetectionRequest(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'telegram_detection_requests'
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'running', 'completed', 'failed', 'timed_out')", name='ck_telegram_detection_status'),
        Index('ix_telegram_detection_requests_recovery', 'status', 'deadline_at', 'created_at'),
    )

    id: str = Field(sa_column=Column(String(64), primary_key=True))
    token_encrypted: str = Field(repr=False, sa_column=Column(Text, nullable=False))
    token_sha256: str = Field(sa_column=Column(String(64), nullable=False))
    request_user_id: str = Field(sa_column=Column(String(64), nullable=False))
    namespace: str = Field(sa_column=Column(String(128), nullable=False))
    status: str = Field(default='pending', sa_column=Column(String(16), nullable=False, server_default='pending'))
    result_json: dict[str, object] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    owner_generation: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default='0'))
    deadline_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    created_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
