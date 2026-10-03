from __future__ import annotations

import asyncio

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from backend_core.api_execution_budget import run_api_blocking
from backend_core.database import run_db
from backend_core.telegram_store import add_subscriber, get_subscriber_by_chat
from modules.telegram.store import require_generation

_TELEGRAM_BASE_URL = 'https://api.telegram.org'


async def handle_update(client: httpx.AsyncClient, *, token: str, update: dict[str, object], generation: int) -> None:
    message = update.get('message')
    if not isinstance(message, dict):
        return
    text = message.get('text')
    chat = message.get('chat')
    if not isinstance(text, str) or not isinstance(chat, dict) or chat.get('id') is None:
        return
    chat_id = str(chat['id'])
    title = str(chat.get('first_name') or chat.get('title') or chat.get('username') or chat_id)
    command = text.strip().lower()
    if command == '/subscribe':
        await _subscribe(client, token=token, chat_id=chat_id, title=title, generation=generation)
        return
    if command == '/unsubscribe':
        await _unsubscribe(client, token=token, chat_id=chat_id, generation=generation)
        return
    if command == '/start':
        await _send_message(client, token=token, chat_id=chat_id, text='Welcome! Use /subscribe to receive build notifications.')


async def _subscribe(client: httpx.AsyncClient, *, token: str, chat_id: str, title: str, generation: int) -> None:
    try:
        await run_api_blocking(run_db, _add_subscriber, chat_id, title, token, generation)
    except SQLAlchemyError:
        await _send_message(client, token=token, chat_id=chat_id, text='Failed to subscribe. Please try again.')
        raise
    await _send_message(client, token=token, chat_id=chat_id, text='Subscribed! You will receive build notifications.')


async def _unsubscribe(client: httpx.AsyncClient, *, token: str, chat_id: str, generation: int) -> None:
    await run_api_blocking(run_db, _deactivate_subscriber, chat_id, token, generation)
    await _send_message(client, token=token, chat_id=chat_id, text='Unsubscribed. You will no longer receive notifications.')


def _add_subscriber(session: Session, chat_id: str, title: str, token: str, generation: int) -> None:
    require_generation(session, generation)
    add_subscriber(session, chat_id, title, token)


def _deactivate_subscriber(session: Session, chat_id: str, token: str, generation: int) -> None:
    require_generation(session, generation)
    subscriber = get_subscriber_by_chat(session, chat_id, token)
    if subscriber is None:
        return
    subscriber.is_active = False
    session.add(subscriber)
    session.commit()


async def _send_message(client: httpx.AsyncClient, *, token: str, chat_id: str, text: str) -> None:
    async with asyncio.timeout(10.0):
        response = await client.post(
            f'{_TELEGRAM_BASE_URL}/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': text},
        )
    response.raise_for_status()
