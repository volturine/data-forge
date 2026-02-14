"""Telegram subscriber/listener API routes."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from core.database import get_db
from modules.telegram import service
from modules.telegram.bot import telegram_bot
from modules.telegram.schemas import (
    BotStatusResponse,
    ListenerCreate,
    ListenerResponse,
    SubscriberResponse,
)

router = APIRouter(prefix='/telegram', tags=['telegram'])


@router.get('/status', response_model=BotStatusResponse)
def bot_status(session: Session = Depends(get_db)) -> BotStatusResponse:
    subs = service.list_subscribers(session)
    active = sum(1 for s in subs if s.is_active)
    return BotStatusResponse(
        running=telegram_bot.running,
        token_configured=bool(telegram_bot.token),
        subscriber_count=active,
    )


@router.get('/subscribers', response_model=list[SubscriberResponse])
def get_subscribers(session: Session = Depends(get_db)) -> list[SubscriberResponse]:
    return service.list_subscribers(session)


@router.delete('/subscribers/{subscriber_id}')
def delete_subscriber(subscriber_id: int, session: Session = Depends(get_db)) -> dict[str, str]:
    service.delete_subscriber(session, subscriber_id)
    return {'message': 'Subscriber deleted'}


@router.get('/listeners', response_model=list[ListenerResponse])
def get_listeners(
    subscriber_id: int | None = None,
    datasource_id: str | None = None,
    session: Session = Depends(get_db),
) -> list[ListenerResponse]:
    return service.list_listeners(session, subscriber_id, datasource_id)


@router.post('/listeners', response_model=ListenerResponse)
def create_listener(payload: ListenerCreate, session: Session = Depends(get_db)) -> ListenerResponse:
    return service.add_listener(session, payload)


@router.delete('/listeners/{listener_id}')
def delete_listener(listener_id: int, session: Session = Depends(get_db)) -> dict[str, str]:
    service.remove_listener(session, listener_id)
    return {'message': 'Listener deleted'}
