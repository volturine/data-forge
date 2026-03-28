from typing import Protocol, runtime_checkable

import polars as pl
from pydantic import BaseModel, ConfigDict


class OperationParams(BaseModel):
    model_config = ConfigDict(extra='forbid')


class OperationHandler(Protocol):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame: ...


@runtime_checkable
class ComputeEngine(Protocol):
    """Protocol defining the interface any compute engine must satisfy.

    This enables future engine swapping (e.g. Polars ↔ PySpark) by decoupling
    the manager/service layers from a specific engine implementation.
    """

    analysis_id: str
    resource_config: dict
    effective_resources: dict
    current_job_id: str | None

    @property
    def process_id(self) -> int | None: ...

    def start(self) -> None: ...

    def is_process_alive(self) -> bool: ...

    def check_health(self) -> bool: ...

    def preview(
        self,
        datasource_config: dict,
        steps: list[dict],
        row_limit: int = 1000,
        offset: int = 0,
        additional_datasources: dict[str, dict] | None = None,
    ) -> str: ...

    def export(
        self,
        datasource_config: dict,
        steps: list[dict],
        output_path: str,
        export_format: str = 'csv',
        additional_datasources: dict[str, dict] | None = None,
    ) -> str: ...

    def get_schema(
        self,
        datasource_config: dict,
        steps: list[dict],
        additional_datasources: dict[str, dict] | None = None,
    ) -> str: ...

    def get_row_count(
        self,
        datasource_config: dict,
        steps: list[dict],
        additional_datasources: dict[str, dict] | None = None,
    ) -> str: ...

    def get_result(self, timeout: float = 1.0, job_id: str | None = None) -> dict | None: ...

    def shutdown(self) -> None: ...
