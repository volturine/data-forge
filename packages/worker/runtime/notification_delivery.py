from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

import pyarrow as pa  # type: ignore[import-untyped]

from runtime.worker_runtime_client import WorkerRuntimeClient, client_from_env
from runtime.namespace import get_namespace

STAGED_NOTIFICATION_PREFIX = "__dataforge_notification_"


def staged_column_name(step_id: str) -> str:
    return f"{STAGED_NOTIFICATION_PREFIX}{step_id.replace('-', '_')}"


def encode_staged_deliveries(deliveries: list[dict[str, object]]) -> str:
    return json.dumps(deliveries, separators=(",", ":"), sort_keys=True)


def extract_staged_deliveries(table: pa.Table) -> tuple[pa.Table, list[dict[str, object]]]:
    staged_columns = [name for name in table.column_names if name.startswith(STAGED_NOTIFICATION_PREFIX)]
    if not staged_columns:
        return table, []
    deliveries: list[dict[str, object]] = []
    for column_name in staged_columns:
        for raw in table[column_name].to_pylist():
            if raw is None:
                continue
            parsed = json.loads(str(raw))
            if not isinstance(parsed, list):
                raise ValueError(f"Staged notification column {column_name} must contain JSON arrays")
            for delivery in parsed:
                if not isinstance(delivery, dict):
                    raise ValueError(f"Staged notification column {column_name} contains an invalid delivery")
                deliveries.append({str(key): value for key, value in delivery.items()})
    return table.drop(staged_columns), deliveries


def strip_staged_preview(data: Mapping[str, object]) -> dict[str, Any]:
    result = dict(data)
    raw_schema = result.get("schema")
    if isinstance(raw_schema, Mapping):
        result["schema"] = {str(key): value for key, value in raw_schema.items() if not str(key).startswith(STAGED_NOTIFICATION_PREFIX)}
    raw_rows = result.get("data")
    if isinstance(raw_rows, list):
        result["data"] = [
            {str(key): value for key, value in row.items() if not str(key).startswith(STAGED_NOTIFICATION_PREFIX)}
            for row in raw_rows
            if isinstance(row, Mapping)
        ]
    return result


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
    def __init__(self, client: WorkerRuntimeClient | None = None) -> None:
        self._client = client

    def _api_client(self) -> WorkerRuntimeClient:
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
            namespace=get_namespace(),
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
            namespace=get_namespace(),
            chat_id=chat_id,
            message=message,
            bot_token=bot_token,
            attachments=[attachment.__dict__ for attachment in attachments or []],
        )
