"""Telegram subscriber and listener models."""

import datetime as dt

from sqlalchemy import Column, DateTime, Integer, String
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
    subscriber_id: int = Field(sa_column=Column(Integer, nullable=False))
    datasource_id: str = Field(sa_column=Column(String, nullable=False))
