"""Telegram subscriber/listener API routes."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from core.database import get_db
from core.validation import DataSourceId, parse_datasource_id
from modules.telegram import service
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
    from modules.settings.service import get_settings

    settings = get_settings(session)
    token_configured = bool(settings.telegram_bot_token)
    return BotStatusResponse(
        running=token_configured,
        token_configured=token_configured,
        subscriber_count=active,
    )


@router.get('/subscribers', response_model=list[SubscriberResponse])
def get_subscribers(session: Session = Depends(get_db)) -> list[SubscriberResponse]:
    return service.list_subscribers(session)


@router.delete('/subscribers/{subscriber_id}', status_code=204)
def delete_subscriber(subscriber_id: int, session: Session = Depends(get_db)) -> None:
    service.delete_subscriber(session, subscriber_id)
    return None


@router.get('/listeners', response_model=list[ListenerResponse])
def get_listeners(
    subscriber_id: int | None = None,
    datasource_id: DataSourceId | None = None,
    session: Session = Depends(get_db),
) -> list[ListenerResponse]:
    return service.list_listeners(session, subscriber_id, parse_datasource_id(datasource_id) if datasource_id else None)


@router.post('/listeners', response_model=ListenerResponse)
def create_listener(payload: ListenerCreate, session: Session = Depends(get_db)) -> ListenerResponse:
    return service.add_listener(session, payload)


@router.delete('/listeners/{listener_id}', status_code=204)
def delete_listener(listener_id: int, session: Session = Depends(get_db)) -> None:
    service.remove_listener(session, listener_id)
    return None
