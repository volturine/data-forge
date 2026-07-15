import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlmodel import Session

from backend_core.persistence.telegram.models import TelegramListener, TelegramSubscriber
from backend_core.sqlmodel_typing import col, sa
from backend_core.telegram_schemas import (
    ListenerCreate,
    ListenerResponse,
    SubscriberResponse,
)

logger = logging.getLogger(__name__)


def list_subscribers(session: Session, bot_token: str | None = None) -> list[SubscriberResponse]:
    query = select(TelegramSubscriber)
    if bot_token:
        query = query.where(sa(TelegramSubscriber.bot_token == bot_token))
    rows = session.execute(query).scalars().all()
    return [SubscriberResponse.model_validate(s) for s in rows]


def get_subscriber_by_chat(session: Session, chat_id: str, bot_token: str) -> TelegramSubscriber | None:
    return (
        session.execute(
            select(TelegramSubscriber).where(sa(TelegramSubscriber.chat_id == chat_id)).where(sa(TelegramSubscriber.bot_token == bot_token)),
        )
        .scalars()
        .first()
    )


def add_subscriber(session: Session, chat_id: str, title: str, bot_token: str) -> SubscriberResponse:
    existing = get_subscriber_by_chat(session, chat_id, bot_token)
    if existing:
        existing.is_active = True
        existing.title = title
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return SubscriberResponse.model_validate(existing)
    sub = TelegramSubscriber(
        chat_id=chat_id,
        title=title,
        bot_token=bot_token,
        is_active=True,
        subscribed_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return SubscriberResponse.model_validate(sub)


def deactivate_subscriber(session: Session, subscriber_id: int) -> None:
    sub = session.get(TelegramSubscriber, subscriber_id)
    if not sub:
        return
    sub.is_active = False
    for listener in (
        session.execute(
            select(TelegramListener).where(sa(TelegramListener.subscriber_id == subscriber_id)),
        )
        .scalars()
        .all()
    ):
        session.delete(listener)
    session.add(sub)
    session.commit()


def delete_subscriber(session: Session, subscriber_id: int) -> None:
    listeners = (
        session.execute(
            select(TelegramListener).where(sa(TelegramListener.subscriber_id == subscriber_id)),
        )
        .scalars()
        .all()
    )
    for listener in listeners:
        session.delete(listener)
    sub = session.get(TelegramSubscriber, subscriber_id)
    if sub:
        session.delete(sub)
    session.commit()


def list_listeners(
    session: Session,
    subscriber_id: int | None = None,
    datasource_id: str | None = None,
) -> list[ListenerResponse]:
    query = select(TelegramListener)
    if subscriber_id is not None:
        query = query.where(sa(TelegramListener.subscriber_id == subscriber_id))
    if datasource_id:
        query = query.where(sa(TelegramListener.datasource_id == datasource_id))
    rows = session.execute(query).scalars().all()
    return [ListenerResponse.model_validate(row) for row in rows]


def add_listener(session: Session, data: ListenerCreate) -> ListenerResponse:
    existing = (
        session.execute(
            select(TelegramListener)
            .where(sa(TelegramListener.subscriber_id == data.subscriber_id))
            .where(sa(TelegramListener.datasource_id == data.datasource_id)),
        )
        .scalars()
        .first()
    )
    if existing:
        return ListenerResponse.model_validate(existing)
    listener = TelegramListener(subscriber_id=data.subscriber_id, datasource_id=data.datasource_id)
    session.add(listener)
    session.commit()
    session.refresh(listener)
    return ListenerResponse.model_validate(listener)


def remove_listener(session: Session, listener_id: int) -> None:
    listener = session.get(TelegramListener, listener_id)
    if not listener:
        return
    session.delete(listener)
    session.commit()


def auto_populate_listeners(session: Session, datasource_id: str) -> list[ListenerResponse]:
    subs = (
        session.execute(
            select(TelegramSubscriber).where(col(TelegramSubscriber.is_active).is_(True)),
        )
        .scalars()
        .all()
    )
    results: list[ListenerResponse] = []
    for sub in subs:
        data = ListenerCreate(subscriber_id=sub.id, datasource_id=datasource_id)
        results.append(add_listener(session, data))
    return results


def get_notification_chat_ids(session: Session, datasource_id: str) -> list[tuple[str, str]]:
    listeners = (
        session.execute(
            select(TelegramListener).where(sa(TelegramListener.datasource_id == datasource_id)),
        )
        .scalars()
        .all()
    )
    sub_ids = {listener.subscriber_id for listener in listeners}
    if not sub_ids:
        return []
    subs = (
        session.execute(
            select(TelegramSubscriber).where(col(TelegramSubscriber.id).in_(sub_ids)).where(col(TelegramSubscriber.is_active).is_(True)),
        )
        .scalars()
        .all()
    )
    return [(s.chat_id, s.bot_token) for s in subs]
