from __future__ import annotations

from dataclasses import dataclass

from runtime.internal_api import WorkerInternalApiClient, client_from_env


@dataclass(frozen=True)
class NotificationAttachment:
    filename: str
    content: bytes
    content_type: str = "text/plain"


def render_template(template: str, context: dict[str, object]) -> str:
    for key, value in context.items():
        template = template.replace(f"{{{{{key}}}}}", str(value))
    return template


class NotificationDelivery:
    def __init__(self, client: WorkerInternalApiClient | None = None) -> None:
        self._client = client

    def _api_client(self) -> WorkerInternalApiClient:
        if self._client is not None:
            return self._client
        return client_from_env()

    def telegram_enabled(self) -> bool:
        return self._api_client().telegram_enabled()

    def send_email(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        attachments: list[NotificationAttachment] | None = None,
    ) -> None:
        self._api_client().send_email(
            to=to,
            subject=subject,
            body=body,
            attachments=[attachment.__dict__ for attachment in attachments or []],
        )

    def send_telegram(
        self,
        *,
        chat_id: str,
        message: str,
        bot_token: str | None = None,
        attachments: list[NotificationAttachment] | None = None,
    ) -> None:
        self._api_client().send_telegram(
            chat_id=chat_id,
            message=message,
            bot_token=bot_token,
            attachments=[attachment.__dict__ for attachment in attachments or []],
        )


NotificationService = NotificationDelivery
notification_service = NotificationDelivery()
