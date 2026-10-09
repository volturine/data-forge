from __future__ import annotations

import datetime as dt
from typing import Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend_core.domain.api_enums import ApiEnumValue, api_token
from dataforge_protocol import enums_pb2


class ComputeWorkerRunKind(ApiEnumValue):
    BUILD: ClassVar[Self]
    PREVIEW: ClassVar[Self]
    ROW_COUNT: ClassVar[Self]
    DOWNLOAD: ClassVar[Self]
    INGEST: ClassVar[Self]


ComputeWorkerRunKind.BUILD = ComputeWorkerRunKind(
    enums_pb2.COMPUTE_WORKER_RUN_KIND_BUILD, api_token('ComputeWorkerRunKind', enums_pb2.COMPUTE_WORKER_RUN_KIND_BUILD)
)
ComputeWorkerRunKind.PREVIEW = ComputeWorkerRunKind(
    enums_pb2.COMPUTE_WORKER_RUN_KIND_PREVIEW, api_token('ComputeWorkerRunKind', enums_pb2.COMPUTE_WORKER_RUN_KIND_PREVIEW)
)
ComputeWorkerRunKind.ROW_COUNT = ComputeWorkerRunKind(
    enums_pb2.COMPUTE_WORKER_RUN_KIND_ROW_COUNT, api_token('ComputeWorkerRunKind', enums_pb2.COMPUTE_WORKER_RUN_KIND_ROW_COUNT)
)
ComputeWorkerRunKind.DOWNLOAD = ComputeWorkerRunKind(
    enums_pb2.COMPUTE_WORKER_RUN_KIND_DOWNLOAD, api_token('ComputeWorkerRunKind', enums_pb2.COMPUTE_WORKER_RUN_KIND_DOWNLOAD)
)
ComputeWorkerRunKind.INGEST = ComputeWorkerRunKind(
    enums_pb2.COMPUTE_WORKER_RUN_KIND_INGEST, api_token('ComputeWorkerRunKind', enums_pb2.COMPUTE_WORKER_RUN_KIND_INGEST)
)


class ComputeWorkerRunStatus(ApiEnumValue):
    RUNNING: ClassVar[Self]
    SUCCESS: ClassVar[Self]
    FAILED: ClassVar[Self]
    CANCELLED: ClassVar[Self]

    @property
    def is_terminal(self) -> bool:
        return self in {ComputeWorkerRunStatus.SUCCESS, ComputeWorkerRunStatus.FAILED, ComputeWorkerRunStatus.CANCELLED}

    def blocks_transition_to(self, next_status: ComputeWorkerRunStatus) -> bool:
        return self.is_terminal and next_status != self


ComputeWorkerRunStatus.RUNNING = ComputeWorkerRunStatus(
    enums_pb2.COMPUTE_WORKER_RUN_STATUS_RUNNING, api_token('ComputeWorkerRunStatus', enums_pb2.COMPUTE_WORKER_RUN_STATUS_RUNNING)
)
ComputeWorkerRunStatus.SUCCESS = ComputeWorkerRunStatus(
    enums_pb2.COMPUTE_WORKER_RUN_STATUS_SUCCESS, api_token('ComputeWorkerRunStatus', enums_pb2.COMPUTE_WORKER_RUN_STATUS_SUCCESS)
)
ComputeWorkerRunStatus.FAILED = ComputeWorkerRunStatus(
    enums_pb2.COMPUTE_WORKER_RUN_STATUS_FAILED, api_token('ComputeWorkerRunStatus', enums_pb2.COMPUTE_WORKER_RUN_STATUS_FAILED)
)
ComputeWorkerRunStatus.CANCELLED = ComputeWorkerRunStatus(
    enums_pb2.COMPUTE_WORKER_RUN_STATUS_CANCELLED, api_token('ComputeWorkerRunStatus', enums_pb2.COMPUTE_WORKER_RUN_STATUS_CANCELLED)
)


class ComputeWorkerRunExecutionCategory(ApiEnumValue):
    READ: ClassVar[Self]
    STEP: ClassVar[Self]
    PLAN: ClassVar[Self]
    COMPUTE: ClassVar[Self]
    WRITE: ClassVar[Self]

    @property
    def is_query_plan(self) -> bool:
        return self == ComputeWorkerRunExecutionCategory.PLAN

    @property
    def default_step_type(self) -> str:
        match self:
            case ComputeWorkerRunExecutionCategory.READ | ComputeWorkerRunExecutionCategory.WRITE:
                return self.value
            case _:
                return 'unknown'


ComputeWorkerRunExecutionCategory.READ = ComputeWorkerRunExecutionCategory(
    enums_pb2.COMPUTE_WORKER_RUN_EXECUTION_CATEGORY_READ, api_token('ComputeWorkerRunExecutionCategory', enums_pb2.COMPUTE_WORKER_RUN_EXECUTION_CATEGORY_READ)
)
ComputeWorkerRunExecutionCategory.STEP = ComputeWorkerRunExecutionCategory(
    enums_pb2.COMPUTE_WORKER_RUN_EXECUTION_CATEGORY_STEP, api_token('ComputeWorkerRunExecutionCategory', enums_pb2.COMPUTE_WORKER_RUN_EXECUTION_CATEGORY_STEP)
)
ComputeWorkerRunExecutionCategory.PLAN = ComputeWorkerRunExecutionCategory(
    enums_pb2.COMPUTE_WORKER_RUN_EXECUTION_CATEGORY_PLAN, api_token('ComputeWorkerRunExecutionCategory', enums_pb2.COMPUTE_WORKER_RUN_EXECUTION_CATEGORY_PLAN)
)
ComputeWorkerRunExecutionCategory.COMPUTE = ComputeWorkerRunExecutionCategory(
    enums_pb2.COMPUTE_WORKER_RUN_EXECUTION_CATEGORY_COMPUTE,
    api_token('ComputeWorkerRunExecutionCategory', enums_pb2.COMPUTE_WORKER_RUN_EXECUTION_CATEGORY_COMPUTE),
)
ComputeWorkerRunExecutionCategory.WRITE = ComputeWorkerRunExecutionCategory(
    enums_pb2.COMPUTE_WORKER_RUN_EXECUTION_CATEGORY_WRITE, api_token('ComputeWorkerRunExecutionCategory', enums_pb2.COMPUTE_WORKER_RUN_EXECUTION_CATEGORY_WRITE)
)


class SchemaDiffStatus(ApiEnumValue):
    ADDED: ClassVar[Self]
    REMOVED: ClassVar[Self]
    TYPE_CHANGED: ClassVar[Self]


SchemaDiffStatus.ADDED = SchemaDiffStatus(enums_pb2.SCHEMA_DIFF_STATUS_ADDED, api_token('SchemaDiffStatus', enums_pb2.SCHEMA_DIFF_STATUS_ADDED))
SchemaDiffStatus.REMOVED = SchemaDiffStatus(enums_pb2.SCHEMA_DIFF_STATUS_REMOVED, api_token('SchemaDiffStatus', enums_pb2.SCHEMA_DIFF_STATUS_REMOVED))
SchemaDiffStatus.TYPE_CHANGED = SchemaDiffStatus(
    enums_pb2.SCHEMA_DIFF_STATUS_TYPE_CHANGED, api_token('SchemaDiffStatus', enums_pb2.SCHEMA_DIFF_STATUS_TYPE_CHANGED)
)


class ComputeWorkerRunResultSummary(BaseModel):
    model_config = ConfigDict(extra='allow')

    row_count: int | str | None = None
    schema_: dict[str, str] | None = Field(default_factory=dict, alias='schema')
    data: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None


class ComputeWorkerRunExecutionEntry(BaseModel):
    key: str
    label: str
    category: ComputeWorkerRunExecutionCategory
    order: int
    duration_ms: float | None = None
    share_pct: float | None = None
    optimized_plan: str | None = None
    unoptimized_plan: str | None = None
    metadata: dict[str, Any] | None = None


class ComputeWorkerRunBaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    namespace: str
    analysis_id: str | None = None
    datasource_id: str
    kind: ComputeWorkerRunKind
    status: ComputeWorkerRunStatus
    request_json: dict[str, Any]
    result_json: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: dt.datetime
    completed_at: dt.datetime | None = None
    duration_ms: int | None = None
    step_timings: dict[str, float] = Field(default_factory=dict)
    query_plan: str | None = None
    progress: float = 0.0
    current_step: str | None = None
    triggered_by: str | None = None
    execution_entries: list[ComputeWorkerRunExecutionEntry] = Field(default_factory=list)


class ComputeWorkerRunResponseSchema(ComputeWorkerRunBaseSchema):
    id: str
    applied: bool = True


class ColumnDiff(BaseModel):
    column: str
    status: SchemaDiffStatus
    type_a: str | None = None
    type_b: str | None = None


class TimingDiff(BaseModel):
    step: str
    ms_a: float | None = None
    ms_b: float | None = None
    delta_ms: float | None = None
    delta_pct: float | None = None


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: ComputeWorkerRunKind
    status: ComputeWorkerRunStatus
    created_at: dt.datetime
    duration_ms: int | None
    row_count: int | None = None
    schema_columns: int = 0
    triggered_by: str | None = None

    @model_validator(mode='before')
    @classmethod
    def extract_result_fields(cls, values: dict) -> dict:  # type: ignore[override]
        """Pull row_count and schema size from result_json if present."""
        if not isinstance(values, dict):
            return values
        rj = values.get('result_json') or {}
        if 'row_count' not in values or values.get('row_count') is None:
            rc = rj.get('row_count')
            if rc is not None:
                values['row_count'] = int(rc) if not isinstance(rc, int) else rc
        if values.get('schema_columns', 0) == 0:
            schema = rj.get('schema')
            if isinstance(schema, dict):
                values['schema_columns'] = len(schema)
        return values


class BuildComparisonResponse(BaseModel):
    run_a: RunSummary
    run_b: RunSummary
    row_count_a: int | None = None
    row_count_b: int | None = None
    row_count_delta: int | None = None
    schema_diff: list[ColumnDiff] = Field(default_factory=list)
    timing_diff: list[TimingDiff] = Field(default_factory=list)
    total_duration_delta_ms: int | None = None


class DurationStatsRun(BaseModel):
    id: str
    started_at: dt.datetime
    duration_ms: int | None
    status: str


class DurationTrend(BaseModel):
    """Half-window comparison of build length (older runs vs more recent runs).

    ``change_pct`` is signed on duration: positive means duration is increasing,
    negative means duration is decreasing.
    """

    direction: str = 'insufficient_data'
    change_pct: float | None = None
    older_avg_ms: float | None = None
    recent_avg_ms: float | None = None
    older_count: int = 0
    recent_count: int = 0
    sample_size: int = 0
    threshold_pct: float = 10.0
    summary: str = 'Not enough builds to judge a trend yet.'


class DurationStatsResponse(BaseModel):
    runs: list[DurationStatsRun] = Field(default_factory=list)
    avg_duration_ms: float | None = None
    p50_duration_ms: float | None = None
    p95_duration_ms: float | None = None
    trend: DurationTrend = Field(default_factory=DurationTrend)
