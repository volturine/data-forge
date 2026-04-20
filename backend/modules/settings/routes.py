"""Settings API routes — GET/PUT settings, test SMTP/Telegram."""

import logging
from email.message import EmailMessage

from fastapi import Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session

from core import http as http_client
from core.database import get_settings_db
from core.error_handlers import handle_errors
from core.smtp import send_smtp_message
from modules.auth.dependencies import get_current_user
from modules.auth.models import User
from modules.config.routes import invalidate_config_cache
from modules.mcp.router import MCPRouter
from modules.settings.schemas import (
    DetectCustomBotRequest,
    DetectTelegramResponse,
    SettingsResponse,
    SettingsUpdate,
    TelegramChat,
    TestResult,
    TestSmtpRequest,
    TestTelegramRequest,
)
from modules.settings.service import (
    get_resolved_smtp,
    get_resolved_telegram_settings,
    get_settings,
    update_settings,
)

logger = logging.getLogger(__name__)

router = MCPRouter(prefix='/settings', tags=['settings'])


def _apply_telegram_bot_runtime(enabled: bool, token: str, telegram_bot) -> None:  # type: ignore[no-untyped-def]
    if enabled and token:
        telegram_bot.start(token)
        return
    if telegram_bot.running:
        telegram_bot.stop()


@router.get('', response_model=SettingsResponse, mcp=True)
@handle_errors(operation='get settings')
def read_settings(
    session: Session = Depends(get_settings_db),
    user: User = Depends(get_current_user),
) -> SettingsResponse:
    """Get application settings including SMTP config, Telegram token, OpenRouter API key, and feature flags."""
    return get_settings(session)


@router.put('', response_model=SettingsResponse, mcp=True)
@handle_errors(operation='update settings')
def write_settings(
    data: SettingsUpdate,
    session: Session = Depends(get_settings_db),
    user: User = Depends(get_current_user),
) -> SettingsResponse:
    """Update application settings. Only provided fields are changed; omitted fields keep current values."""
    from modules.telegram.bot import telegram_bot

    result = update_settings(session, data)
    invalidate_config_cache()

    token = get_resolved_telegram_settings().get('token', '')

    try:
        _apply_telegram_bot_runtime(result.telegram_bot_enabled, str(token), telegram_bot)
    except Exception as exc:
        logger.error('Failed to apply Telegram bot runtime after settings save', exc_info=True)
        raise HTTPException(status_code=502, detail=f'Telegram bot runtime update failed: {exc}') from exc

    return result


@router.post('/test-smtp', response_model=TestResult, mcp=True)
@handle_errors(operation='test smtp')
async def test_smtp(body: TestSmtpRequest, user: User = Depends(get_current_user)) -> TestResult:
    """Send a test email via SMTP to verify email notification settings. Requires 'to' address in body."""
    smtp = get_resolved_smtp()
    host = str(smtp.get('host', ''))
    port = int(str(smtp.get('port', 587)))
    smtp_user = str(smtp.get('user', ''))
    password = str(smtp.get('password', ''))

    if not host or not smtp_user:
        return TestResult(success=False, message='SMTP not configured — set host and user first')

    msg = EmailMessage()
    msg['From'] = smtp_user
    msg['To'] = body.to
    msg['Subject'] = 'Test notification'
    msg.set_content('This is a test email from your application.')

    try:
        await run_in_threadpool(send_smtp_message, host, port, smtp_user, password, msg)
        return TestResult(success=True, message=f'Test email sent to {body.to}')
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post('/test-telegram', response_model=TestResult, mcp=True)
@handle_errors(operation='test telegram')
async def test_telegram(body: TestTelegramRequest, user: User = Depends(get_current_user)) -> TestResult:
    """Send a test message to a Telegram chat to verify bot settings. Requires chat_id in body."""
    resolved = get_resolved_telegram_settings()
    token = str(resolved.get('token', ''))
    if not resolved.get('enabled'):
        return TestResult(success=False, message='Telegram bot token not configured')

    try:
        resp = await run_in_threadpool(
            http_client.post,
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={
                'chat_id': body.chat_id,
                'text': 'Test notification from your application.',
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return TestResult(success=True, message=f'Test message sent to chat {body.chat_id}')
        data = resp.json()
        desc = data.get('description', resp.text)
        return TestResult(success=False, message=f'Telegram API error: {desc}')
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post('/detect-telegram-chat', response_model=DetectTelegramResponse, mcp=True)
@handle_errors(operation='detect telegram chat')
async def detect_telegram_chat(user: User = Depends(get_current_user)) -> DetectTelegramResponse:
    """Detect Telegram chats that have messaged the configured bot.

    Send a message to your bot first, then call this to discover the chat_id.
    Returns a list of detected chats with their IDs and titles.
    """
    from modules.telegram.bot import telegram_bot

    resolved = get_resolved_telegram_settings()
    token = str(resolved.get('token', ''))
    if not resolved.get('enabled'):
        return DetectTelegramResponse(success=False, message='Telegram bot token not configured')

    was_running = telegram_bot.running
    if was_running:
        await run_in_threadpool(telegram_bot.pause)
    try:
        offset = telegram_bot.get_offset(token)
        resp = await run_in_threadpool(
            telegram_bot.get_updates,
            token,
            {'limit': 10, 'timeout': 0, 'offset': offset},
            10,
        )
        if resp.status_code != 200:
            return DetectTelegramResponse(success=False, message=f'Telegram API error: {resp.text}')

        data = resp.json()
        updates: list[dict[str, object]] = data.get('result', [])
        seen: dict[str, str] = {}

        for update in updates:
            chat: dict[str, object] | None = None
            if 'message' in update:
                msg = update['message']
                if isinstance(msg, dict):
                    chat = msg.get('chat')  # type: ignore[assignment]
            elif 'channel_post' in update:
                post = update['channel_post']
                if isinstance(post, dict):
                    chat = post.get('chat')  # type: ignore[assignment]
            if not chat:
                continue
            cid = str(chat['id'])
            if cid not in seen:
                title = str(chat.get('first_name') or chat.get('title') or chat.get('username') or cid)
                seen[cid] = title

        chats = [TelegramChat(chat_id=cid, title=title) for cid, title in seen.items()]
        return DetectTelegramResponse(success=True, message=f'Found {len(chats)} chat(s)', chats=chats)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        if was_running:
            await run_in_threadpool(telegram_bot.resume)


@router.post('/detect-chat-custom', response_model=DetectTelegramResponse, mcp=True)
@handle_errors(operation='detect custom telegram chat')
async def detect_custom_bot_chat(
    body: DetectCustomBotRequest,
    user: User = Depends(get_current_user),
) -> DetectTelegramResponse:
    """Detect chats for a custom Telegram bot token (not the one saved in settings).

    Use this to test a new bot token before saving it. Requires bot_token in body.
    """
    from modules.telegram.bot import telegram_bot

    if not body.bot_token:
        return DetectTelegramResponse(success=False, message='Bot token is required')

    was_running = telegram_bot.running and telegram_bot.token == body.bot_token
    if was_running:
        await run_in_threadpool(telegram_bot.pause)
    try:
        offset = telegram_bot.get_offset(body.bot_token)
        resp = await run_in_threadpool(
            telegram_bot.get_updates,
            body.bot_token,
            {'limit': 10, 'timeout': 0, 'offset': offset},
            10,
        )
        if resp.status_code != 200:
            return DetectTelegramResponse(success=False, message=f'Telegram API error: {resp.text}')

        data = resp.json()
        updates: list[dict[str, object]] = data.get('result', [])
        seen: dict[str, str] = {}

        for update in updates:
            chat: dict[str, object] | None = None
            if 'message' in update:
                msg = update['message']
                if isinstance(msg, dict):
                    chat = msg.get('chat')  # type: ignore[assignment]
            elif 'channel_post' in update:
                post = update['channel_post']
                if isinstance(post, dict):
                    chat = post.get('chat')  # type: ignore[assignment]
            if not chat:
                continue
            cid = str(chat['id'])
            if cid not in seen:
                title = str(chat.get('first_name') or chat.get('title') or chat.get('username') or cid)
                seen[cid] = title

        chats = [TelegramChat(chat_id=cid, title=title) for cid, title in seen.items()]
        return DetectTelegramResponse(success=True, message=f'Found {len(chats)} chat(s)', chats=chats)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        if was_running:
            await run_in_threadpool(telegram_bot.resume)
