import base64
from email.message import EmailMessage

from backend_core import http as http_client
from backend_core.settings_projection import get_resolved_smtp, get_resolved_telegram_settings, get_resolved_telegram_token
from backend_core.smtp import send_smtp_message

EMAIL_DELIVERY_KIND = 'email_delivery'
TELEGRAM_DELIVERY_KIND = 'telegram_delivery'
_TELEGRAM_BASE_URL = 'https://api.telegram.org'


def deliver(payload: dict[str, object], *, event_id: str) -> None:
    kind = payload.get('kind')
    if kind == EMAIL_DELIVERY_KIND:
        _deliver_email(payload, event_id=event_id)
        return
    if kind == TELEGRAM_DELIVERY_KIND:
        _deliver_telegram(payload)
        return
    raise ValueError(f'Unsupported notification delivery kind: {kind!r}')


def _attachments(payload: dict[str, object]) -> list[dict[str, str]]:
    raw = payload.get('attachments')
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and all(isinstance(item.get(key), str) for key in ('filename', 'content_base64', 'content_type'))]


def _required_text(payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f'Notification delivery requires {field}')
    return value


def _deliver_email(payload: dict[str, object], *, event_id: str) -> None:
    smtp = get_resolved_smtp()
    host = str(smtp.get('host', ''))
    port = int(str(smtp.get('port', 587)))
    user = str(smtp.get('user', ''))
    password = str(smtp.get('password', ''))
    if not host or not user:
        raise ValueError('SMTP is not configured')
    message = EmailMessage()
    message['From'] = user
    message['To'] = _required_text(payload, 'to')
    message['Subject'] = _required_text(payload, 'subject')
    message['Message-ID'] = f'<{event_id}@data-forge>'
    body = str(payload.get('body', ''))
    message.set_content(body)
    message.add_alternative(body, subtype='html')
    for attachment in _attachments(payload):
        maintype, separator, subtype = attachment['content_type'].partition('/')
        if not separator:
            maintype, subtype = 'text', 'plain'
        message.add_attachment(
            base64.b64decode(attachment['content_base64']),
            maintype=maintype,
            subtype=subtype,
            filename=attachment['filename'],
        )
    send_smtp_message(host, port, user, password, message)


def _deliver_telegram(payload: dict[str, object]) -> None:
    resolved = get_resolved_telegram_settings()
    if not resolved['enabled']:
        raise ValueError('Telegram is not enabled')
    payload_token = payload.get('bot_token')
    token = payload_token if isinstance(payload_token, str) and payload_token else str(resolved['token']) or get_resolved_telegram_token()
    if not token:
        raise ValueError('Telegram bot token is not configured')
    chat_id = _required_text(payload, 'chat_id')
    base = f'{_TELEGRAM_BASE_URL}/bot{token}'
    response = http_client.post(
        f'{base}/sendMessage',
        json={'chat_id': chat_id, 'text': _required_text(payload, 'message'), 'parse_mode': 'HTML'},
        timeout=20,
    )
    response.raise_for_status()
    for attachment in _attachments(payload):
        file_response = http_client.post(
            f'{base}/sendDocument',
            data={'chat_id': chat_id},
            files={'document': (attachment['filename'], base64.b64decode(attachment['content_base64']), attachment['content_type'])},
            timeout=30,
        )
        file_response.raise_for_status()
