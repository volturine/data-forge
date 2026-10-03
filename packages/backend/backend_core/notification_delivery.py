import base64
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage

from backend_core import http as http_client
from backend_core.settings_projection import get_resolved_smtp, get_resolved_telegram_settings, get_resolved_telegram_token
from backend_core.smtp import send_smtp_message

EMAIL_DELIVERY_KIND = 'email_delivery'
TELEGRAM_DELIVERY_KIND = 'telegram_delivery'
EXTERNAL_DELIVERY_KINDS = frozenset({EMAIL_DELIVERY_KIND, TELEGRAM_DELIVERY_KIND})
_TELEGRAM_BASE_URL = 'https://api.telegram.org'
_REDACTED = '[REDACTED]'


@dataclass(frozen=True, slots=True)
class DeliveryProgress:
    completed_parts: frozenset[str] = frozenset()
    record_completed_part: Callable[[str], bool] | None = None


def redact_secrets_in_text(message: str, *secrets: str) -> str:
    for secret in secrets:
        if secret:
            message = message.replace(secret, _REDACTED)
    return message


def deliver(payload: dict[str, object], *, event_id: str, progress: DeliveryProgress | None = None) -> None:
    kind = payload.get('kind')
    if kind == EMAIL_DELIVERY_KIND:
        _deliver_email(payload, event_id=event_id)
        return
    if kind == TELEGRAM_DELIVERY_KIND:
        _deliver_telegram(payload, progress or DeliveryProgress())
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


def _deliver_telegram(payload: dict[str, object], progress: DeliveryProgress) -> None:
    resolved = get_resolved_telegram_settings()
    if not resolved['enabled']:
        raise ValueError('Telegram is not enabled')
    payload_token = payload.get('bot_token')
    token = payload_token if isinstance(payload_token, str) and payload_token else str(resolved['token']) or get_resolved_telegram_token()
    if not token:
        raise ValueError('Telegram bot token is not configured')
    chat_id = _required_text(payload, 'chat_id')
    base = f'{_TELEGRAM_BASE_URL}/bot{token}'
    try:
        if 'message' not in progress.completed_parts:
            _telegram_post(
                f'{base}/sendMessage',
                token,
                json={'chat_id': chat_id, 'text': _required_text(payload, 'message'), 'parse_mode': 'HTML'},
                timeout=20,
            )
            _record_completed_part(progress, 'message')
        for index, attachment in enumerate(_attachments(payload)):
            part_key = f'attachment:{index}'
            if part_key in progress.completed_parts:
                continue
            _telegram_post(
                f'{base}/sendDocument',
                token,
                data={'chat_id': chat_id},
                files={'document': (attachment['filename'], base64.b64decode(attachment['content_base64']), attachment['content_type'])},
                timeout=30,
            )
            _record_completed_part(progress, part_key)
    except Exception as exc:
        raise RuntimeError(f'Telegram delivery failed: {redact_secrets_in_text(str(exc), token)}') from exc


def _record_completed_part(progress: DeliveryProgress, part_key: str) -> None:
    if progress.record_completed_part is not None and not progress.record_completed_part(part_key):
        raise RuntimeError('Telegram delivery claim expired before progress could be recorded')


def _telegram_post(url: str, token: str, **kwargs: object) -> None:
    response = http_client.post(url, **kwargs)
    response.raise_for_status()
