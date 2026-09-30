"""Settings API routes — GET/PUT settings, test SMTP/Telegram."""

import asyncio
import threading
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from email.message import EmailMessage
from functools import partial

import httpx
from fastapi import Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session

from backend_core import settings_store
from backend_core.database import get_settings_db_async, run_settings_db
from backend_core.error_handlers import handle_errors
from backend_core.secrets import MASKED_SECRET
from backend_core.settings_schemas import (
    DetectCustomBotRequest,
    DetectTelegramResponse,
    SettingsResponse,
    SettingsUpdate,
    SettingsUpdate as CoreSettingsUpdate,
    TestResult,
    TestSmtpRequest,
    TestTelegramRequest,
)
from backend_core.smtp import send_smtp_message
from modules.auth.dependencies import get_current_user
from modules.auth.models import User
from modules.mcp.router import MCPRouter
from modules.telegram import store as telegram_runtime_store
from modules.telegram.runtime import (
    TelegramDetectionFailed,
    TelegramDetectionTimedOut,
    request_chat_detection,
)

router = MCPRouter(prefix='/settings', tags=['settings'])
_SMTP_TEST_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='smtp-test')
_SMTP_TEST_CAPACITY = threading.BoundedSemaphore(1)
_SMTP_TEST_DEADLINE = 12.0
_TELEGRAM_TEST_TIMEOUT = httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=3.0)


def _redact_token(value: str, token: str) -> str:
    return value.replace(token, MASKED_SECRET) if token else value


def _finish_smtp_test(future: Future[None]) -> None:
    """Observe late worker errors and release capacity only after the worker settles."""
    try:
        future.exception()
    except CancelledError:
        pass
    finally:
        _SMTP_TEST_CAPACITY.release()


def _consume_smtp_test_result(future: asyncio.Future[None]) -> None:
    """Retrieve a worker error even when its HTTP request has already ended."""
    if not future.cancelled():
        future.exception()


@router.get('', response_model=SettingsResponse, mcp=True)
@handle_errors(operation='get settings')
def read_settings(
    session: Session = Depends(get_settings_db_async),
    user: User = Depends(get_current_user),
) -> SettingsResponse:
    """Get application settings including SMTP config, Telegram token, OpenRouter API key, and feature flags."""
    return SettingsResponse.model_validate(settings_store.get_settings(session))


@router.put('', response_model=SettingsResponse, mcp=True)
@handle_errors(operation='update settings')
def write_settings(
    data: SettingsUpdate,
    session: Session = Depends(get_settings_db_async),
    user: User = Depends(get_current_user),
) -> SettingsResponse:
    """Update application settings. Only provided fields are changed; omitted fields keep current values."""
    result = settings_store.update_settings(
        session,
        CoreSettingsUpdate.model_validate(data.model_dump(exclude_unset=True)),
    )
    typed_result = SettingsResponse.model_validate(result)

    return typed_result


@router.post('/test-smtp', response_model=TestResult, mcp=True)
@handle_errors(operation='test smtp')
async def test_smtp(body: TestSmtpRequest, user: User = Depends(get_current_user)) -> TestResult:
    """Send a test email via SMTP to verify email notification settings. Requires 'to' address in body."""
    smtp = await run_in_threadpool(settings_store.get_resolved_smtp)
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

    if not _SMTP_TEST_CAPACITY.acquire(blocking=False):
        raise HTTPException(status_code=429, detail='SMTP testing is busy; try again shortly')
    try:
        future = _SMTP_TEST_EXECUTOR.submit(
            partial(send_smtp_message, host, port, smtp_user, password, msg, timeout=10),
        )
    except BaseException:
        _SMTP_TEST_CAPACITY.release()
        raise

    future.add_done_callback(_finish_smtp_test)
    async_future = asyncio.wrap_future(future)
    async_future.add_done_callback(_consume_smtp_test_result)
    try:
        completed, _pending = await asyncio.wait({async_future}, timeout=_SMTP_TEST_DEADLINE)
        if completed:
            async_future.result()
            return TestResult(success=True, message=f'Test email sent to {body.to}')
    except asyncio.CancelledError:
        future.cancel()
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_redact_token(str(exc), password)) from exc

    if future.cancel():
        detail = 'SMTP test deadline expired before sending; the email was not sent'
    else:
        detail = 'SMTP test deadline expired while sending; the SMTP provider may have accepted the email'
    raise HTTPException(status_code=504, detail=detail)


@router.post('/test-telegram', response_model=TestResult, mcp=True)
@handle_errors(operation='test telegram')
async def test_telegram(body: TestTelegramRequest, user: User = Depends(get_current_user)) -> TestResult:
    """Send a test message to a Telegram chat to verify bot settings. Requires chat_id in body."""
    resolved = await run_in_threadpool(run_settings_db, telegram_runtime_store.read_settings)
    token = resolved.token
    if not resolved.enabled:
        return TestResult(success=False, message='Telegram bot token not configured')

    try:
        async with asyncio.timeout(12.0), httpx.AsyncClient(timeout=_TELEGRAM_TEST_TIMEOUT) as client:
            resp = await client.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={
                    'chat_id': body.chat_id,
                    'text': 'Test notification from your application.',
                },
            )
        if resp.status_code == 200:
            return TestResult(success=True, message=f'Test message sent to chat {body.chat_id}')
        data = resp.json()
        desc = data.get('description', resp.text)
        return TestResult(success=False, message=_redact_token(f'Telegram API error: {desc}', token))
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail='Telegram test deadline expired') from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_redact_token(str(exc), token)) from exc


@router.post('/detect-telegram-chat', response_model=DetectTelegramResponse, mcp=True)
@handle_errors(operation='detect telegram chat')
async def detect_telegram_chat(
    user: User = Depends(get_current_user),
) -> DetectTelegramResponse:
    """Detect Telegram chats that have messaged the configured bot.

    Send a message to your bot first, then call this to discover the chat_id.
    Returns a list of detected chats with their IDs and titles.
    """
    resolved = await run_in_threadpool(run_settings_db, telegram_runtime_store.read_settings)
    if not resolved.enabled:
        return DetectTelegramResponse(success=False, message='Telegram bot token not configured')
    try:
        result = await request_chat_detection(token=resolved.token, request_user_id=user.id, namespace=_request_namespace())
        return DetectTelegramResponse.model_validate(result)
    except telegram_runtime_store.DetectionQueueFull as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except TelegramDetectionTimedOut as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except TelegramDetectionFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post('/detect-chat-custom', response_model=DetectTelegramResponse, mcp=True)
@handle_errors(operation='detect custom telegram chat')
async def detect_custom_bot_chat(
    body: DetectCustomBotRequest,
    user: User = Depends(get_current_user),
) -> DetectTelegramResponse:
    """Detect chats for a custom Telegram bot token (not the one saved in settings).

    Use this to test a new bot token before saving it. Requires bot_token in body.
    """
    if not body.bot_token:
        return DetectTelegramResponse(success=False, message='Bot token is required')
    try:
        result = await request_chat_detection(
            token=body.bot_token,
            request_user_id=user.id,
            namespace=_request_namespace(),
        )
        return DetectTelegramResponse.model_validate(result)
    except telegram_runtime_store.DetectionQueueFull as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except TelegramDetectionTimedOut as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except TelegramDetectionFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _request_namespace() -> str:
    from backend_core.namespace import get_namespace

    return get_namespace()
