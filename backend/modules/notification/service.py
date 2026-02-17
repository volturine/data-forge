from dataclasses import dataclass
from email.message import EmailMessage
from typing import Final

import httpx

from modules.settings.service import (
    get_resolved_smtp,
    get_resolved_telegram_settings,
    get_resolved_telegram_token,
)


@dataclass(frozen=True)
class NotificationAttachment:
    filename: str
    content: bytes
    content_type: str = 'text/plain'


_TELEGRAM_BASE_URL: Final[str] = 'https://api.telegram.org'


def render_template(template: str, context: dict[str, object]) -> str:
    output = template
    for key, value in context.items():
        output = output.replace(f'{{{{{key}}}}}', str(value))
    return output


class NotificationService:
    def send_email(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        attachments: list[NotificationAttachment] | None = None,
    ) -> None:
        if not to:
            return
        smtp = get_resolved_smtp()
        host = str(smtp.get('host', ''))
        port = int(str(smtp.get('port', 587)))
        user = str(smtp.get('user', ''))
        password = str(smtp.get('password', ''))

        if not host:
            raise ValueError('SMTP not configured (host missing)')
        if not user:
            raise ValueError('SMTP not configured (user missing)')

        msg = EmailMessage()
        msg['From'] = user
        msg['To'] = to
        msg['Subject'] = subject
        msg.set_content(body)
        msg.add_alternative(body, subtype='html')

        for attachment in attachments or []:
            maintype, _, subtype = attachment.content_type.partition('/')
            if not maintype or not subtype:
                maintype = 'text'
                subtype = 'plain'
            msg.add_attachment(
                attachment.content,
                maintype=maintype,
                subtype=subtype,
                filename=attachment.filename,
            )

        import smtplib

        with smtplib.SMTP(host, port) as server:
            server.starttls()
            if password:
                server.login(user, password)
            server.send_message(msg)

    def send_telegram(
        self,
        *,
        chat_id: str,
        message: str,
        bot_token: str | None = None,
        attachments: list[NotificationAttachment] | None = None,
    ) -> None:
        resolved = get_resolved_telegram_settings()
        if not resolved['enabled']:
            return
        token = bot_token or str(resolved['token']) or get_resolved_telegram_token()
        if not token:
            raise ValueError('Telegram bot token not configured')
        base = f'{_TELEGRAM_BASE_URL}/bot{token}'
        response = httpx.post(
            f'{base}/sendMessage',
            json={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'},
            timeout=20,
        )
        response.raise_for_status()

        for attachment in attachments or []:
            file_response = httpx.post(
                f'{base}/sendDocument',
                data={'chat_id': chat_id},
                files={'document': (attachment.filename, attachment.content, attachment.content_type)},
                timeout=30,
            )
            file_response.raise_for_status()


notification_service = NotificationService()
