import polars as pl
from pydantic import Field, model_validator

from operations.enums import NotificationMethod, RecipientSource
from operations.template_placeholders import render_template_placeholders
from runtime.domain.compute.base import OperationParams
from runtime.notification_delivery import encode_staged_deliveries, staged_column_name


class NotificationParams(OperationParams):
    method: NotificationMethod = NotificationMethod.EMAIL
    # Stored for the editor's recipient mode; the editor keeps `recipient` and
    # `recipient_column` mutually exclusive, so the rows below already follow it.
    recipient_source: RecipientSource = RecipientSource.MANUAL
    recipient: str = ""
    subscriber_ids: list[str] = Field(default_factory=list)
    bot_token: str = ""
    recipient_column: str = ""
    input_columns: list[str] = Field(default_factory=list)
    output_column: str = "notification_status"
    message_template: str = "{{message}}"
    subject_template: str = "Notification"
    # Accepted from the protocol; rows are delivered in one pass, so the size itself has no effect.
    batch_size: int = Field(default=10, ge=1)

    @model_validator(mode="after")
    def _validate(self) -> NotificationParams:
        if not self.recipient and not self.subscriber_ids and not self.recipient_column:
            raise ValueError("recipient is required")
        if not self.input_columns:
            raise ValueError("At least one input column is required (input_columns)")
        return self


def notification(
    lf: pl.LazyFrame,
    params: NotificationParams,
    *,
    step_id: str,
    **_,
) -> pl.LazyFrame:
    """Per-row notification UDF.

    Collects the DataFrame, iterates rows, sends notifications
    using the configured method, and appends a status column with the
    staged delivery command (``staged`` or ``[error: ...]``). The commands are
    removed from the exported dataset and committed to the durable outbox with
    the output datasource publication.
    """
    schema = lf.collect_schema()

    required_columns = list(params.input_columns)
    if params.recipient_column:
        required_columns.append(params.recipient_column)
    missing = [c for c in required_columns if c not in schema]
    if missing:
        raise ValueError(f"Input column(s) not found: {', '.join(missing)}")

    select_cols = list(dict.fromkeys(required_columns))
    output_schema = dict(schema)
    output_schema[params.output_column] = pl.Utf8()
    command_column = staged_column_name(step_id)
    output_schema[command_column] = pl.Utf8()

    def parse_recipients(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value).split(",") if item.strip()]

    def apply_batch(df: pl.DataFrame) -> pl.DataFrame:
        if df.is_empty():
            return df.with_columns(
                pl.Series(name=params.output_column, values=[], dtype=pl.Utf8),
                pl.Series(name=command_column, values=[], dtype=pl.Utf8),
            )

        rows = df.select(select_cols).to_dicts()
        results: list[str] = []
        staged: list[str] = []

        for row in rows:
            message = render_template_placeholders(params.message_template, row)
            recipient_value = row.get(params.recipient_column) if params.recipient_column else None
            recipients = parse_recipients(recipient_value) or parse_recipients(params.recipient)
            if not recipients:
                results.append("[error: recipient is required]")
                staged.append(encode_staged_deliveries([]))
                continue
            try:
                commands: list[dict[str, object]]
                if params.method == NotificationMethod.EMAIL:
                    subject = render_template_placeholders(params.subject_template, row)
                    commands = [
                        {
                            "method": "email",
                            "recipient": ",".join(recipients),
                            "subject": subject,
                            "body": message,
                        }
                    ]
                else:
                    commands = [
                        {
                            "method": "telegram",
                            "recipient": recipient,
                            "message": message,
                            **({"bot_token": params.bot_token} if params.bot_token else {}),
                        }
                        for recipient in recipients
                    ]
                encoded = encode_staged_deliveries(commands)
                results.append("staged")
                staged.append(encoded)
            except Exception as exc:
                results.append(f"[error: {exc}]")
                staged.append(encode_staged_deliveries([]))

        return df.with_columns(
            pl.Series(name=params.output_column, values=results, dtype=pl.Utf8),
            pl.Series(name=command_column, values=staged, dtype=pl.Utf8),
        )

    return lf.map_batches(
        apply_batch,
        schema=output_schema,
        predicate_pushdown=False,
        projection_pushdown=False,
        slice_pushdown=False,
        validate_output_schema=True,
        streamable=False,
    )
