"""AI handler — UDF wrapper for LLM chat APIs.

Takes column input(s) from the DataFrame, interpolates them into a prompt
template, calls the configured LLM endpoint, and writes the response into
a result column.  This is NOT a general-purpose AI assistant — it is a
predefined UDF with wiring to LLM request endpoints.
"""

import logging
import re
import time
from enum import StrEnum

import polars as pl
from pydantic import ConfigDict, Field, field_validator, model_validator

from modules.ai.service import AIError, get_ai_client, parse_request_options
from modules.compute.core.base import OperationHandler, OperationParams

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r'\{\{(\w+)\}\}')


class AIProvider(StrEnum):
    OLLAMA = 'ollama'
    OPENAI = 'openai'
    OPENROUTER = 'openrouter'
    HUGGINGFACE = 'huggingface'


class AIParams(OperationParams):
    """Parameters for the AI UDF handler.

    Supports multiple input columns via ``input_columns``.  The legacy
    ``input_column`` (singular) field is accepted for backward compatibility
    and automatically promoted into the list.
    """

    model_config = ConfigDict(extra='forbid')

    provider: AIProvider = AIProvider.OLLAMA
    model: str = 'llama2'
    input_columns: list[str] = Field(default_factory=list)
    input_column: str | None = None  # legacy — promoted into input_columns
    output_column: str = 'ai_result'
    error_column: str = 'ai_error'
    prompt_template: str = 'Classify this text: {{text}}'
    batch_size: int = 10
    max_retries: int = 3
    rate_limit_rpm: int | None = None
    endpoint_url: str | None = None
    api_key: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    request_options: dict[str, object] | None = None

    @field_validator('request_options', mode='before')
    @classmethod
    def _parse_options(cls, v: str | dict[str, object] | None) -> dict[str, object] | None:
        return parse_request_options(v)

    @model_validator(mode='after')
    def _promote_legacy_input(self) -> 'AIParams':
        """Merge legacy ``input_column`` into ``input_columns``."""
        if self.input_column and self.input_column not in self.input_columns:
            self.input_columns = [self.input_column, *self.input_columns]
        # Clear legacy field so it's not serialized twice
        self.input_column = None
        if not self.input_columns:
            raise ValueError('At least one input column is required (input_columns)')
        return self


def _build_prompt(template: str, row: dict[str, object]) -> str:
    """Replace ``{{col}}`` placeholders with row values.

    Falls back to ``{{text}}`` → first column value for single-column prompts.
    """

    def _replace(m: re.Match[str]) -> str:
        key = m.group(1)
        if key in row:
            return str(row[key])
        return m.group(0)  # leave unknown placeholders untouched

    return _PLACEHOLDER_RE.sub(_replace, template)


class AIHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = AIParams.model_validate(params)
        if validated.batch_size < 1:
            raise ValueError('batch_size must be at least 1')
        if validated.max_retries < 0:
            raise ValueError('max_retries must be non-negative')
        if validated.rate_limit_rpm is not None and validated.rate_limit_rpm <= 0:
            raise ValueError('rate_limit_rpm must be positive when provided')
        schema = lf.collect_schema()

        # Validate all input columns exist
        missing = [c for c in validated.input_columns if c not in schema]
        if missing:
            raise ValueError(f'Input column(s) not found: {", ".join(missing)}')

        select_cols = list(validated.input_columns)
        uses_text = '{{text}}' in validated.prompt_template
        single_col = len(select_cols) == 1

        output_schema = dict(schema)
        output_schema[validated.output_column] = pl.Utf8()
        output_schema[validated.error_column] = pl.Utf8()

        def apply_batch(df: pl.DataFrame) -> pl.DataFrame:
            if df.is_empty():
                return df.with_columns(
                    pl.Series(name=validated.output_column, values=[], dtype=pl.Utf8),
                    pl.Series(name=validated.error_column, values=[], dtype=pl.Utf8),
                )

            rows = df.select(select_cols).to_dicts()
            row_count = len(rows)

            client = get_ai_client(
                validated.provider,
                endpoint_url=validated.endpoint_url,
                api_key=validated.api_key,
            )
            results: list[str] = []
            errors: list[str] = []
            last_call_ts = 0.0
            min_interval_sec = 0.0
            if validated.rate_limit_rpm:
                min_interval_sec = 60.0 / float(validated.rate_limit_rpm)

            request_options = dict(validated.request_options or {})
            request_options.setdefault('temperature', validated.temperature)
            if validated.max_tokens is not None:
                request_options.setdefault('max_tokens', validated.max_tokens)

            for offset in range(0, row_count, validated.batch_size):
                batch_rows = rows[offset : offset + validated.batch_size]
                prompts: list[str] = []
                for row in batch_rows:
                    if uses_text and single_col:
                        row['text'] = row[select_cols[0]]
                    prompts.append(_build_prompt(validated.prompt_template, row))
                success = False
                for attempt in range(validated.max_retries + 1):
                    try:
                        if min_interval_sec > 0:
                            elapsed = time.monotonic() - last_call_ts
                            if elapsed < min_interval_sec:
                                time.sleep(min_interval_sec - elapsed)
                        outputs = client.generate_batch(
                            prompts,
                            model=validated.model,
                            options=request_options,
                        )
                        last_call_ts = time.monotonic()
                        if len(outputs) != len(batch_rows):
                            raise AIError(f'AI output length mismatch for batch: got {len(outputs)}, expected {len(batch_rows)}')
                        results.extend(outputs)
                        errors.extend([''] * len(batch_rows))
                        success = True
                        break
                    except Exception as exc:
                        is_final_attempt = attempt >= validated.max_retries
                        if is_final_attempt:
                            logger.error(
                                'AI batch failed at row %d-%d after %d attempt(s): %s',
                                offset,
                                offset + len(batch_rows),
                                attempt + 1,
                                exc,
                            )
                            detail = str(exc) or exc.__class__.__name__
                            marker = f'[error: {detail}]'
                            results.extend([marker] * len(batch_rows))
                            errors.extend([detail] * len(batch_rows))
                            break
                        backoff_sec = min(2**attempt, 30)
                        logger.warning(
                            'AI batch retry %d/%d at row %d-%d: %s',
                            attempt + 1,
                            validated.max_retries,
                            offset,
                            offset + len(batch_rows),
                            exc,
                        )
                        time.sleep(backoff_sec)
                if not success and len(errors) < len(results):
                    errors.extend(['Unknown AI batch failure'] * (len(results) - len(errors)))

            if len(results) != row_count:
                raise ValueError(f'AI output length mismatch: got {len(results)}, expected {row_count}')
            if len(errors) != row_count:
                raise ValueError(f'AI error length mismatch: got {len(errors)}, expected {row_count}')

            return df.with_columns(
                pl.Series(name=validated.output_column, values=results, dtype=pl.Utf8),
                pl.Series(name=validated.error_column, values=errors, dtype=pl.Utf8),
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
