import logging
import re
from enum import StrEnum

import polars as pl
from pydantic import ConfigDict, Field, model_validator

from core import http as http_client
from modules.compute.core.base import OperationHandler, OperationParams
from modules.notification.service import notification_service
from modules.settings.service import get_resolved_telegram_settings

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r'\{\{(\w+)\}\}')


class NotificationMethod(StrEnum):
    EMAIL = 'email'
    TELEGRAM = 'telegram'


class NotificationParams(OperationParams):
    model_config = ConfigDict(extra='forbid')

    method: NotificationMethod = NotificationMethod.EMAIL
    recipient: str = ''
    subscriber_ids: list[str] = Field(default_factory=list)
    bot_token: str = ''
    recipient_column: str = ''
    input_columns: list[str] = Field(default_factory=list)
    output_column: str = 'notification_status'
    message_template: str = '{{message}}'
    subject_template: str = 'Notification'
    batch_size: int = 10
    timeout_seconds: int = 20

    @model_validator(mode='after')
    def _validate(self) -> 'NotificationParams':
        if not self.recipient and not self.subscriber_ids and not self.recipient_column:
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

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = NotificationParams.model_validate(params)
        telegram_enabled = True
        if validated.method == NotificationMethod.TELEGRAM:
            resolved = get_resolved_telegram_settings()
            telegram_enabled = bool(resolved.get('enabled'))
        schema = lf.collect_schema()

        required_columns = list(validated.input_columns)
        if validated.recipient_column:
            required_columns.append(validated.recipient_column)
        missing = [c for c in required_columns if c not in schema]
        if missing:
            raise ValueError(f'Input column(s) not found: {", ".join(missing)}')

        select_cols = list(dict.fromkeys(required_columns))
        output_schema = dict(schema)
        output_schema[validated.output_column] = pl.Utf8()

        def parse_recipients(value: object) -> list[str]:
            if value is None:
                return []
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
            return [item.strip() for item in str(value).split(',') if item.strip()]

        def apply_batch(df: pl.DataFrame) -> pl.DataFrame:
            if df.is_empty():
                return df.with_columns(
                    pl.Series(name=validated.output_column, values=[], dtype=pl.Utf8),
                )
            if validated.method == NotificationMethod.TELEGRAM and not telegram_enabled:
                return df.with_columns(
                    pl.Series(
                        name=validated.output_column,
                        values=['[error: telegram disabled]' for _ in range(df.height)],
                        dtype=pl.Utf8,
                    ),
                )

            rows = df.select(select_cols).to_dicts()
            row_count = len(rows)
            results: list[str] = []

            for offset in range(0, row_count, validated.batch_size):
                batch = rows[offset : offset + validated.batch_size]
                for row in batch:
                    message = _build_message(validated.message_template, row)
                    recipient_value = row.get(validated.recipient_column) if validated.recipient_column else None
                    try:
                        recipients = parse_recipients(recipient_value)
                        if not recipients:
                            recipients = parse_recipients(validated.recipient)
                        if not recipients:
                            raise ValueError('recipient is required')
                        if validated.method == NotificationMethod.EMAIL:
                            subject = _build_message(validated.subject_template, row)
                            notification_service.send_email(
                                to=','.join(recipients),
                                subject=subject,
                                body=message,
                            )
                        elif validated.bot_token:
                            for cid in recipients:
                                http_client.post(
                                    f'https://api.telegram.org/bot{validated.bot_token}/sendMessage',
                                    json={'chat_id': cid, 'text': message, 'parse_mode': 'HTML'},
                                    timeout=validated.timeout_seconds,
                                )
                        else:
                            for cid in recipients:
                                notification_service.send_telegram(
                                    chat_id=cid,
                                    message=message,
                                )
                        results.append('sent')
                    except Exception as exc:
                        logger.warning('Notification failed at row %d: %s', offset, exc, exc_info=True)
                        results.append(f'[error: {exc}]')

            if len(results) != row_count:
                raise ValueError(f'Notification output length mismatch: got {len(results)}, expected {row_count}')

            return df.with_columns(
                pl.Series(name=validated.output_column, values=results, dtype=pl.Utf8),
            )

        return lf.map_batches(
            apply_batch,
            schema=output_schema,
            predicate_pushdown=False,
            projection_pushdown=False,
            slice_pushdown=False,
            no_optimizations=True,
            validate_output_schema=True,
            streamable=False,
        )
