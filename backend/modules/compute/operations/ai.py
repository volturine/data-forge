import logging
from typing import Literal

import polars as pl
from pydantic import ConfigDict, field_validator

from modules.ai.service import AIError, get_ai_client, parse_request_options
from modules.compute.core.base import OperationHandler, OperationParams

logger = logging.getLogger(__name__)


class AIParams(OperationParams):
    model_config = ConfigDict(extra='forbid')

    provider: Literal['ollama', 'openai'] = 'ollama'
    model: str = 'llama2'
    input_column: str
    output_column: str
    prompt_template: str = 'Classify this text: {{text}}'
    batch_size: int = 10
    endpoint_url: str | None = None
    api_key: str | None = None
    request_options: dict | None = None

    @field_validator('request_options', mode='before')
    @classmethod
    def _parse_options(cls, v: str | dict | None) -> dict | None:
        return parse_request_options(v)


class AIHandler(OperationHandler):
    @property
    def name(self) -> str:
        return 'ai'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = AIParams.model_validate(params)
        if validated.batch_size < 1:
            raise ValueError('batch_size must be at least 1')
        df = lf.collect()
        if validated.input_column not in df.columns:
            raise ValueError(f'Input column not found: {validated.input_column}')

        texts = df[validated.input_column].to_list()
        if not texts:
            return df.with_columns(pl.Series(name=validated.output_column, values=[], dtype=pl.Utf8)).lazy()

        client = get_ai_client(
            validated.provider,
            endpoint_url=validated.endpoint_url,
            api_key=validated.api_key,
        )
        results: list[str] = []
        total = len(texts)
        for offset in range(0, total, validated.batch_size):
            batch = texts[offset : offset + validated.batch_size]
            prompts = [validated.prompt_template.replace('{{text}}', str(text)) for text in batch]
            try:
                outputs = client.generate_batch(
                    prompts,
                    model=validated.model,
                    options=validated.request_options,
                )
                results.extend(outputs)
            except AIError as exc:
                logger.error('AI batch failed at row %d-%d: %s', offset, offset + len(batch), exc)
                results.extend([f'[error: {exc}]'] * len(batch))
            except Exception as exc:
                logger.error('Unexpected AI error at row %d-%d: %s', offset, offset + len(batch), exc)
                results.extend([f'[error: {exc}]'] * len(batch))

        if len(results) != total:
            raise ValueError(f'AI output length mismatch: got {len(results)}, expected {total}')
        return df.with_columns(pl.Series(name=validated.output_column, values=results)).lazy()
