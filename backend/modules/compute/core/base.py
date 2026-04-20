from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

import polars as pl
from pydantic import BaseModel, ConfigDict


class OperationParams(BaseModel):
    model_config = ConfigDict(extra='forbid')


class OperationHandler(Protocol):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict[str, object],
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Engine command types — sent from main process to compute subprocess
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShutdownCommand:
    type: Literal['shutdown'] = 'shutdown'


@dataclass(frozen=True, slots=True)
class PreviewCommand:
    job_id: str
    datasource_config: dict[str, Any]
    steps: list[dict[str, Any]]
    row_limit: int = 1000
    offset: int = 0
    additional_datasources: dict[str, dict[str, Any]] = field(default_factory=dict)
    type: Literal['preview'] = 'preview'


@dataclass(frozen=True, slots=True)
class ExportCommand:
    job_id: str
    datasource_config: dict[str, Any]
    steps: list[dict[str, Any]]
    output_path: str
    export_format: str = 'csv'
    additional_datasources: dict[str, dict[str, Any]] = field(default_factory=dict)
    type: Literal['export'] = 'export'


@dataclass(frozen=True, slots=True)
class SchemaCommand:
    job_id: str
    datasource_config: dict[str, Any]
    steps: list[dict[str, Any]]
    additional_datasources: dict[str, dict[str, Any]] = field(default_factory=dict)
    type: Literal['schema'] = 'schema'


@dataclass(frozen=True, slots=True)
class RowCountCommand:
    job_id: str
    datasource_config: dict[str, Any]
    steps: list[dict[str, Any]]
    additional_datasources: dict[str, dict[str, Any]] = field(default_factory=dict)
    type: Literal['row_count'] = 'row_count'


EngineCommand = ShutdownCommand | PreviewCommand | ExportCommand | SchemaCommand | RowCountCommand


# ---------------------------------------------------------------------------
# Engine result — sent from compute subprocess back to main process
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EngineResult:
    job_id: str | None
    data: dict[str, Any] | None
    error: str | None
    error_kind: str | None = None
    error_details: dict[str, Any] | None = None
    step_timings: dict[str, float] = field(default_factory=dict)
    query_plan: str | None = None
    read_duration_ms: float | None = None
    write_duration_ms: float | None = None
    collect_duration_ms: float | None = None


@dataclass(slots=True)
class EngineProgressEvent:
    job_id: str
    event: dict[str, Any]


# ---------------------------------------------------------------------------
# Engine status — returned by manager
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EngineStatusInfo:
    analysis_id: str
    status: str
    process_id: int | None
    last_activity: str | None
    current_job_id: str | None
    resource_config: dict[str, Any] | None
    effective_resources: dict[str, Any] | None
    defaults: dict[str, Any]


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ComputeEngine(Protocol):
    """Protocol defining the interface any compute engine must satisfy."""

    analysis_id: str
    resource_config: dict[str, Any]
    effective_resources: dict[str, Any]
    current_job_id: str | None

    @property
    def process_id(self) -> int | None:
        raise NotImplementedError

    def start(self) -> None:
        raise NotImplementedError

    def is_process_alive(self) -> bool:
        raise NotImplementedError

    def check_health(self) -> bool:
        raise NotImplementedError

    def preview(
        self,
        datasource_config: dict[str, Any],
        steps: list[dict[str, Any]],
        row_limit: int = 1000,
        offset: int = 0,
        additional_datasources: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        raise NotImplementedError

    def export(
        self,
        datasource_config: dict[str, Any],
        steps: list[dict[str, Any]],
        output_path: str,
        export_format: str = 'csv',
        additional_datasources: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        raise NotImplementedError

    def get_schema(
        self,
        datasource_config: dict[str, Any],
        steps: list[dict[str, Any]],
        additional_datasources: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        raise NotImplementedError

    def get_row_count(
        self,
        datasource_config: dict[str, Any],
        steps: list[dict[str, Any]],
        additional_datasources: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        raise NotImplementedError

    def get_result(self, timeout: float = 1.0, job_id: str | None = None) -> EngineResult | None:
        raise NotImplementedError

    def get_progress_event(self, timeout: float = 1.0, job_id: str | None = None) -> EngineProgressEvent | None:
        raise NotImplementedError

    def shutdown(self) -> None:
        raise NotImplementedError
