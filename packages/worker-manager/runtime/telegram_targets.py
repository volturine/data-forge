from __future__ import annotations

from contracts.telegram_models import TelegramListener, TelegramSubscriber
from sqlalchemy import select
from sqlmodel import Session


def list_active_subscriber_targets(session: Session) -> list[tuple[str, str]]:
    rows = (
        session.execute(
            select(TelegramSubscriber).where(TelegramSubscriber.is_active == True)  # type: ignore[arg-type]  # noqa: E712
        )
        .scalars()
        .all()
    )
    return [(row.chat_id, row.bot_token) for row in rows if row.bot_token]


def get_notification_chat_targets(session: Session, datasource_id: str) -> list[tuple[str, str]]:
    listeners = (
        session.execute(
            select(TelegramListener).where(TelegramListener.datasource_id == datasource_id),  # type: ignore[arg-type]
        )
        .scalars()
        .all()
    )
    subscriber_ids = {listener.subscriber_id for listener in listeners}
    if not subscriber_ids:
        return []
    rows = (
        session.execute(
            select(TelegramSubscriber)
            .where(TelegramSubscriber.id.in_(subscriber_ids))  # type: ignore[union-attr]
            .where(TelegramSubscriber.is_active == True),  # type: ignore[arg-type]  # noqa: E712
        )
        .scalars()
        .all()
    )
    return [(row.chat_id, row.bot_token) for row in rows if row.bot_token]
