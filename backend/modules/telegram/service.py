import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlmodel import Session

from modules.telegram.models import TelegramListener, TelegramSubscriber
from modules.telegram.schemas import ListenerCreate, ListenerResponse, SubscriberResponse

logger = logging.getLogger(__name__)


def list_subscribers(session: Session, bot_token: str | None = None) -> list[SubscriberResponse]:
    query = select(TelegramSubscriber)
    if bot_token:
        query = query.where(TelegramSubscriber.bot_token == bot_token)  # type: ignore[arg-type]
    rows = session.execute(query).scalars().all()
    return [SubscriberResponse.model_validate(s) for s in rows]


def get_subscriber_by_chat(session: Session, chat_id: str, bot_token: str) -> TelegramSubscriber | None:
    return (
        session.execute(
            select(TelegramSubscriber)
            .where(TelegramSubscriber.chat_id == chat_id)  # type: ignore[arg-type]
            .where(TelegramSubscriber.bot_token == bot_token)  # type: ignore[arg-type]
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
    listeners = (
        session.execute(
            select(TelegramListener).where(TelegramListener.subscriber_id == subscriber_id)  # type: ignore[arg-type]
        )
        .scalars()
        .all()
    )
    for listener in listeners:
        session.delete(listener)
    session.add(sub)
    session.commit()


def delete_subscriber(session: Session, subscriber_id: int) -> None:
    # Delete listeners first
    listeners = (
        session.execute(
            select(TelegramListener).where(TelegramListener.subscriber_id == subscriber_id)  # type: ignore[arg-type]
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
        query = query.where(TelegramListener.subscriber_id == subscriber_id)  # type: ignore[arg-type]
    if datasource_id:
        query = query.where(TelegramListener.datasource_id == datasource_id)  # type: ignore[arg-type]
    rows = session.execute(query).scalars().all()
    return [ListenerResponse.model_validate(row) for row in rows]


def add_listener(session: Session, data: ListenerCreate) -> ListenerResponse:
    existing = (
        session.execute(
            select(TelegramListener)
            .where(TelegramListener.subscriber_id == data.subscriber_id)  # type: ignore[arg-type]
            .where(TelegramListener.datasource_id == data.datasource_id)  # type: ignore[arg-type]
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
            select(TelegramSubscriber).where(TelegramSubscriber.is_active == True)  # type: ignore[arg-type]  # noqa: E712
        )
        .scalars()
        .all()
    )
    results: list[ListenerResponse] = []
    for sub in subs:
        data = ListenerCreate(subscriber_id=sub.id, datasource_id=datasource_id)  # type: ignore[arg-type]
        results.append(add_listener(session, data))
    return results


def get_notification_chat_ids(session: Session, datasource_id: str) -> list[tuple[str, str]]:
    listeners = (
        session.execute(
            select(TelegramListener).where(TelegramListener.datasource_id == datasource_id)  # type: ignore[arg-type]
        )
        .scalars()
        .all()
    )
    sub_ids = {listener.subscriber_id for listener in listeners}
    if not sub_ids:
        return []
    subs = (
        session.execute(
            select(TelegramSubscriber)
            .where(TelegramSubscriber.id.in_(sub_ids))  # type: ignore[union-attr]
            .where(TelegramSubscriber.is_active == True)  # type: ignore[arg-type]  # noqa: E712
        )
        .scalars()
        .all()
    )
    return [(s.chat_id, s.bot_token) for s in subs]
