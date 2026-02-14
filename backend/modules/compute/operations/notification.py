"""Notification handler — per-row UDF for sending notifications.

Takes column input(s) from the DataFrame, interpolates them into a message
template, sends the notification via email or Telegram, and writes the
delivery status into a result column.  This is a predefined UDF with
wiring to the notification service — users feed it column values and
a template, and get per-row send status back.
"""

import logging
import re
from typing import Literal

import httpx
import polars as pl
from pydantic import ConfigDict, model_validator

from modules.compute.core.base import OperationHandler, OperationParams
from modules.notification.service import notification_service

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r'\{\{(\w+)\}\}')


class NotificationParams(OperationParams):
    """Parameters for the per-row notification UDF.

    Supports multiple input columns via ``input_columns``.
    Message template uses ``{{column_name}}`` placeholders.
    """

    model_config = ConfigDict(extra='forbid')

    method: Literal['email', 'telegram'] = 'email'
    recipient: str = ''
    bot_token: str = ''
    input_columns: list[str] = []
    output_column: str = 'notification_status'
    message_template: str = '{{message}}'
    subject_template: str = 'Notification'
    batch_size: int = 10
    timeout_seconds: int = 20

    @model_validator(mode='after')
    def _validate(self) -> 'NotificationParams':
        if not self.recipient:
            raise ValueError('recipient is required')
        if not self.input_columns:
            raise ValueError('At least one input column is required (input_columns)')
        return self


def _build_message(template: str, row: dict[str, object]) -> str:
    """Replace ``{{col}}`` placeholders with row values."""

    def _replace(m: re.Match[str]) -> str:
        key = m.group(1)
        if key in row:
            return str(row[key])
        return m.group(0)

    return _PLACEHOLDER_RE.sub(_replace, template)


class NotificationHandler(OperationHandler):
    """Per-row notification UDF.

    Collects the DataFrame, iterates rows in batches, sends notifications
    using the configured method, and appends a status column with the
    result of each send (``sent`` or ``[error: ...]``).
    """

    @property
    def name(self) -> str:
        return 'notification'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = NotificationParams.model_validate(params)
        df = lf.collect()

        missing = [c for c in validated.input_columns if c not in df.columns]
        if missing:
            raise ValueError(f'Input column(s) not found: {", ".join(missing)}')

        row_count = df.height
        if row_count == 0:
            return df.with_columns(
                pl.Series(name=validated.output_column, values=[], dtype=pl.Utf8),
            ).lazy()

        rows = df.select(validated.input_columns).to_dicts()
        results: list[str] = []

        for offset in range(0, row_count, validated.batch_size):
            batch = rows[offset : offset + validated.batch_size]
            for row in batch:
                message = _build_message(validated.message_template, row)
                try:
                    if validated.method == 'email':
                        subject = _build_message(validated.subject_template, row)
                        notification_service.send_email(
                            to=validated.recipient,
                            subject=subject,
                            body=message,
                        )
                    elif validated.bot_token:
                        # Custom bot token — send directly via httpx
                        for cid in validated.recipient.split(','):
                            cid = cid.strip()
                            if not cid:
                                continue
                            httpx.post(
                                f'https://api.telegram.org/bot{validated.bot_token}/sendMessage',
                                json={'chat_id': cid, 'text': message, 'parse_mode': 'HTML'},
                                timeout=validated.timeout_seconds,
                            )
                    else:
                        # Global token — send via notification_service
                        for cid in validated.recipient.split(','):
                            cid = cid.strip()
                            if not cid:
                                continue
                            notification_service.send_telegram(
                                chat_id=cid,
                                message=message,
                            )
                    results.append('sent')
                except Exception as exc:
                    logger.warning('Notification failed at row %d: %s', offset, exc)
                    results.append(f'[error: {exc}]')

        if len(results) != row_count:
            raise ValueError(f'Notification output length mismatch: got {len(results)}, expected {row_count}')

        return df.with_columns(pl.Series(name=validated.output_column, values=results)).lazy()
