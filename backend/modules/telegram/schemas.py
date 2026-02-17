"""Telegram schemas."""

import datetime as dt

from pydantic import BaseModel, ConfigDict


class SubscriberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chat_id: str
    title: str
    bot_token: str
    is_active: bool
    subscribed_at: dt.datetime


class ListenerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subscriber_id: int
    datasource_id: str


class ListenerCreate(BaseModel):
    subscriber_id: int
    datasource_id: str


class BotStatusResponse(BaseModel):
    running: bool
    token_configured: bool
    subscriber_count: int
