"""View passthrough operation."""

from runtime.domain.compute.base import OperationParams


class ViewParams(OperationParams):
    row_limit: int | None = None
    cache_enabled: bool = True
