"""Telegram subscriber/listener API routes."""

from core.database import get_db
from fastapi import Depends
from sqlmodel import Session

from backend_core import telegram_store
from backend_core.error_handlers import handle_errors
from backend_core.settings_store import get_resolved_telegram_settings
from backend_core.telegram_schemas import (
    BotStatusResponse,
    ListenerCreate,
    ListenerResponse,
    SubscriberResponse,
)
from backend_core.validation import DataSourceId, parse_datasource_id
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix="/telegram", tags=["telegram"])


@router.get("/status", response_model=BotStatusResponse, mcp=True)
@handle_errors(operation="get bot status")
def bot_status(session: Session = Depends(get_db)) -> BotStatusResponse:
    """Get Telegram bot status: whether the bot is running, token is configured, and active subscriber count."""
    subs = telegram_store.list_subscribers(session)
    active = sum(1 for s in subs if s.is_active)
    telegram_settings = get_resolved_telegram_settings()
    token_configured = bool(telegram_settings["token"])
    running = bool(telegram_settings["enabled"])
    return BotStatusResponse(
        running=running,
        token_configured=token_configured,
        subscriber_count=active,
    )


@router.get("/subscribers", response_model=list[SubscriberResponse], mcp=True)
@handle_errors(operation="list subscribers")
def get_subscribers(session: Session = Depends(get_db)) -> list[SubscriberResponse]:
    """List all Telegram subscribers (chats that have interacted with the bot)."""
    return [SubscriberResponse.model_validate(item) for item in telegram_store.list_subscribers(session)]


@router.delete("/subscribers/{subscriber_id}", status_code=204, mcp=True)
@handle_errors(operation="delete subscriber")
def delete_subscriber(subscriber_id: int, session: Session = Depends(get_db)) -> None:
    """Remove a Telegram subscriber by ID. Use GET /telegram/subscribers to find subscriber IDs."""
    telegram_store.delete_subscriber(session, subscriber_id)


@router.get("/listeners", response_model=list[ListenerResponse], mcp=True)
@handle_errors(operation="list listeners")
def get_listeners(
    subscriber_id: int | None = None,
    datasource_id: DataSourceId | None = None,
    session: Session = Depends(get_db),
) -> list[ListenerResponse]:
    """List notification listeners. Filter by subscriber_id or datasource_id to narrow results.

    A listener links a Telegram subscriber to a datasource for build notifications.
    """
    return [
        ListenerResponse.model_validate(item)
        for item in telegram_store.list_listeners(
            session,
            subscriber_id,
            parse_datasource_id(datasource_id) if datasource_id else None,
        )
    ]


@router.post("/listeners", response_model=ListenerResponse, mcp=True)
@handle_errors(operation="create listener")
def create_listener(payload: ListenerCreate, session: Session = Depends(get_db)) -> ListenerResponse:
    """Create a notification listener linking a Telegram subscriber to a datasource.

    Requires subscriber_id (from GET /telegram/subscribers) and datasource_id
    (from GET /datasource). The subscriber will receive notifications when the datasource is built.
    """
    created = telegram_store.add_listener(session, telegram_store.ListenerCreate.model_validate(payload.model_dump()))
    return ListenerResponse.model_validate(created)


@router.delete("/listeners/{listener_id}", status_code=204, mcp=True)
@handle_errors(operation="delete listener")
def delete_listener(listener_id: int, session: Session = Depends(get_db)) -> None:
    """Remove a notification listener by ID. Use GET /telegram/listeners to find listener IDs."""
    telegram_store.remove_listener(session, listener_id)
