"""Telegram subscriber/listener API routes."""

from backend_core import telegram_store
from backend_core.api_execution_budget import run_api_blocking
from backend_core.database import run_db, run_settings_db
from backend_core.error_handlers import handle_errors
from backend_core.telegram_schemas import (
    BotStatusResponse,
    ListenerCreate,
    ListenerResponse,
    SubscriberResponse,
)
from backend_core.validation import DataSourceId, parse_datasource_id
from modules.mcp.router import MCPRouter
from modules.telegram import store as telegram_runtime_store

router = MCPRouter(prefix='/telegram', tags=['telegram'])


def _bot_status() -> BotStatusResponse:
    subscribers = run_db(telegram_store.list_subscribers)
    active = sum(1 for subscriber in subscribers if subscriber.is_active)
    telegram_settings = run_settings_db(telegram_runtime_store.read_settings)
    return BotStatusResponse(
        running=telegram_settings.enabled,
        token_configured=bool(telegram_settings.token),
        subscriber_count=active,
    )


@router.get('/status', response_model=BotStatusResponse, mcp=True)
@handle_errors(operation='get bot status')
async def bot_status() -> BotStatusResponse:
    """Get Telegram bot status: whether the bot is running, token is configured, and active subscriber count."""
    return await run_api_blocking(_bot_status)


@router.get('/subscribers', response_model=list[SubscriberResponse], mcp=True)
@handle_errors(operation='list subscribers')
async def get_subscribers() -> list[SubscriberResponse]:
    """List all Telegram subscribers (chats that have interacted with the bot)."""
    subscribers = await run_api_blocking(run_db, telegram_store.list_subscribers)
    return [SubscriberResponse.model_validate(item) for item in subscribers]


@router.delete('/subscribers/{subscriber_id}', status_code=204, mcp=True)
@handle_errors(operation='delete subscriber')
async def delete_subscriber(subscriber_id: int) -> None:
    """Remove a Telegram subscriber by ID. Use GET /telegram/subscribers to find subscriber IDs."""
    await run_api_blocking(run_db, telegram_store.delete_subscriber, subscriber_id)


@router.get('/listeners', response_model=list[ListenerResponse], mcp=True)
@handle_errors(operation='list listeners')
async def get_listeners(
    subscriber_id: int | None = None,
    datasource_id: DataSourceId | None = None,
) -> list[ListenerResponse]:
    """List notification listeners. Filter by subscriber_id or datasource_id to narrow results.

    A listener links a Telegram subscriber to a datasource for build notifications.
    """
    listeners = await run_api_blocking(
        run_db,
        telegram_store.list_listeners,
        subscriber_id,
        parse_datasource_id(datasource_id) if datasource_id else None,
    )
    return [ListenerResponse.model_validate(item) for item in listeners]


@router.post('/listeners', response_model=ListenerResponse, mcp=True)
@handle_errors(operation='create listener')
async def create_listener(payload: ListenerCreate) -> ListenerResponse:
    """Create a notification listener linking a Telegram subscriber to a datasource.

    Requires subscriber_id (from GET /telegram/subscribers) and datasource_id
    (from GET /datasource). The subscriber will receive notifications when the datasource is built.
    """
    listener = telegram_store.ListenerCreate.model_validate(payload.model_dump())
    created = await run_api_blocking(run_db, telegram_store.add_listener, listener)
    return ListenerResponse.model_validate(created)


@router.delete('/listeners/{listener_id}', status_code=204, mcp=True)
@handle_errors(operation='delete listener')
async def delete_listener(listener_id: int) -> None:
    """Remove a notification listener by ID. Use GET /telegram/listeners to find listener IDs."""
    await run_api_blocking(run_db, telegram_store.remove_listener, listener_id)
