"""Settings API routes — GET/PUT settings, test SMTP/Telegram."""

import smtplib
from email.message import EmailMessage

import httpx
from fastapi import APIRouter, Depends
from sqlmodel import Session

from core.database import get_db
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
    get_resolved_telegram_token,
    get_settings,
    update_settings,
)

router = APIRouter(prefix='/settings', tags=['settings'])


@router.get('', response_model=SettingsResponse)
def read_settings(session: Session = Depends(get_db)) -> SettingsResponse:
    """Return the current runtime settings."""
    return get_settings(session)


@router.put('', response_model=SettingsResponse)
def write_settings(data: SettingsUpdate, session: Session = Depends(get_db)) -> SettingsResponse:
    """Update runtime settings and restart Telegram bot if token/enabled changed."""
    from modules.telegram.bot import telegram_bot

    result = update_settings(session, data)

    # Start, restart, or stop the Telegram bot based on enabled flag + token
    if data.telegram_bot_enabled and data.telegram_bot_token:
        telegram_bot.start(data.telegram_bot_token)
    elif telegram_bot.running:
        telegram_bot.stop()

    return result


@router.post('/test-smtp', response_model=TestResult)
def test_smtp(body: TestSmtpRequest) -> TestResult:
    """Send a test email using current SMTP settings."""
    smtp = get_resolved_smtp()
    host = str(smtp.get('host', ''))
    port = int(str(smtp.get('port', 587)))
    user = str(smtp.get('user', ''))
    password = str(smtp.get('password', ''))

    if not host or not user:
        return TestResult(success=False, message='SMTP not configured — set host and user first')

    msg = EmailMessage()
    msg['From'] = user
    msg['To'] = body.to
    msg['Subject'] = 'Test notification'
    msg.set_content('This is a test email from your application.')

    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls()
            if password:
                server.login(user, password)
            server.send_message(msg)
        return TestResult(success=True, message=f'Test email sent to {body.to}')
    except Exception as exc:
        return TestResult(success=False, message=str(exc))


@router.post('/test-telegram', response_model=TestResult)
def test_telegram(body: TestTelegramRequest) -> TestResult:
    """Send a test Telegram message using current settings."""
    token = get_resolved_telegram_token()
    if not token:
        return TestResult(success=False, message='Telegram bot token not configured')

    try:
        resp = httpx.post(
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
        return TestResult(success=False, message=str(exc))


@router.post('/detect-telegram-chat', response_model=DetectTelegramResponse)
def detect_telegram_chat() -> DetectTelegramResponse:
    """Call Telegram getUpdates to detect chat IDs from recent messages."""
    from modules.telegram.bot import telegram_bot

    token = get_resolved_telegram_token()
    if not token:
        return DetectTelegramResponse(success=False, message='Telegram bot token not configured')

    was_running = telegram_bot.running
    if was_running:
        telegram_bot.pause()
    try:
        offset = telegram_bot.get_offset(token)
        resp = telegram_bot.get_updates(token, params={'limit': 10, 'timeout': 0, 'offset': offset}, timeout=10)
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
        return DetectTelegramResponse(success=False, message=str(exc))
    finally:
        if was_running:
            telegram_bot.resume()


@router.post('/detect-chat-custom', response_model=DetectTelegramResponse)
def detect_custom_bot_chat(body: DetectCustomBotRequest) -> DetectTelegramResponse:
    """Detect chat_id from a custom bot token (for notification node config)."""
    from modules.telegram.bot import telegram_bot

    if not body.bot_token:
        return DetectTelegramResponse(success=False, message='Bot token is required')

    was_running = telegram_bot.running and telegram_bot.token == body.bot_token
    if was_running:
        telegram_bot.pause()
    try:
        offset = telegram_bot.get_offset(body.bot_token)
        resp = telegram_bot.get_updates(
            body.bot_token,
            params={'limit': 10, 'timeout': 0, 'offset': offset},
            timeout=10,
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
        return DetectTelegramResponse(success=False, message=str(exc))
    finally:
        if was_running:
            telegram_bot.resume()
