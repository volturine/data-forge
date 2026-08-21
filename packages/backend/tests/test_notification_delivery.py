from email.message import EmailMessage
from types import SimpleNamespace

import httpx
import pytest

from backend_core import notification_delivery


def test_email_delivery_uses_stable_message_id(monkeypatch) -> None:
    sent: list[EmailMessage] = []
    monkeypatch.setattr(
        notification_delivery,
        'get_resolved_smtp',
        lambda: {'host': 'smtp.example.com', 'port': 587, 'user': 'sender@example.com', 'password': 'secret'},
    )
    monkeypatch.setattr(notification_delivery, 'send_smtp_message', lambda _host, _port, _user, _password, message: sent.append(message))

    notification_delivery.deliver(
        {
            'kind': notification_delivery.EMAIL_DELIVERY_KIND,
            'to': 'owner@example.com',
            'subject': 'Ready',
            'body': 'Output published',
            'attachments': [],
        },
        event_id='delivery-1',
    )

    assert len(sent) == 1
    assert sent[0]['Message-ID'] == '<delivery-1@data-forge>'


def test_telegram_delivery_uses_persisted_target(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, str]]] = []
    monkeypatch.setattr(notification_delivery, 'get_resolved_telegram_settings', lambda: {'enabled': True, 'token': 'default-token'})

    def post(url: str, *, json: dict[str, str], timeout: int) -> SimpleNamespace:
        assert timeout == 20
        calls.append((url, json))
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(notification_delivery.http_client, 'post', post)

    notification_delivery.deliver(
        {
            'kind': notification_delivery.TELEGRAM_DELIVERY_KIND,
            'chat_id': '123',
            'message': 'Ready',
            'bot_token': 'subscriber-token',
            'attachments': [],
        },
        event_id='delivery-2',
    )

    assert calls == [('https://api.telegram.org/botsubscriber-token/sendMessage', {'chat_id': '123', 'text': 'Ready', 'parse_mode': 'HTML'})]


def test_telegram_failure_redacts_bot_token_from_error(monkeypatch) -> None:
    monkeypatch.setattr(notification_delivery, 'get_resolved_telegram_settings', lambda: {'enabled': True, 'token': 'default-token'})

    def post(url: str, **kwargs: object) -> SimpleNamespace:
        raise ConnectionError(f'Failed to reach {url}: connection refused')

    monkeypatch.setattr(notification_delivery.http_client, 'post', post)

    try:
        notification_delivery.deliver(
            {
                'kind': notification_delivery.TELEGRAM_DELIVERY_KIND,
                'chat_id': '123',
                'message': 'Ready',
                'bot_token': '12345:SECRET-TOKEN',
            },
            event_id='delivery-3',
        )
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError('deliver should raise on transport failure')

    assert '12345:SECRET-TOKEN' not in message
    assert '[REDACTED]' in message
    assert 'connection refused' in message


def test_telegram_status_error_redacts_bot_token_from_url(monkeypatch) -> None:
    monkeypatch.setattr(notification_delivery, 'get_resolved_telegram_settings', lambda: {'enabled': True, 'token': 'default-token'})

    def post(url: str, **kwargs: object) -> httpx.Response:
        request = httpx.Request('POST', url)
        response = httpx.Response(401, request=request)
        response.raise_for_status()
        return response

    monkeypatch.setattr(notification_delivery.http_client, 'post', post)

    with pytest.raises(RuntimeError) as exc_info:
        notification_delivery.deliver(
            {
                'kind': notification_delivery.TELEGRAM_DELIVERY_KIND,
                'chat_id': '123',
                'message': 'Ready',
                'bot_token': '12345:SECRET-TOKEN',
            },
            event_id='delivery-4',
        )

    message = str(exc_info.value)
    assert '12345:SECRET-TOKEN' not in message
    assert '[REDACTED]' in message
