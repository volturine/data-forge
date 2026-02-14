import logging
from typing import Literal

import polars as pl
from pydantic import ConfigDict

from modules.compute.core.base import OperationHandler, OperationParams

logger = logging.getLogger(__name__)


class NotificationParams(OperationParams):
    model_config = ConfigDict(extra='forbid')

    method: Literal['email', 'telegram'] = 'email'
    recipient: str
    subject_template: str = 'Build Complete: {{analysis_name}}'
    body_template: str = 'Analysis: {{analysis_name}}\nStatus: {{status}}\nDuration: {{duration_ms}}ms\nRows: {{row_count}}'
    attach_result: bool = False
    attach_error: bool = True
    webhook_url: str | None = None
    timeout_seconds: int = 20
    retries: int = 0


class NotificationHandler(OperationHandler):
    """Notification is a leaf node.

    Validates config during pipeline build,
    actual sending is handled post-export by the service layer.
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
        NotificationParams.model_validate(params)
        return lf
