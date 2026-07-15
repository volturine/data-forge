from __future__ import annotations

import datetime as dt
from typing import Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend_core.domain.api_enums import ApiEnumValue, api_token
from dataforge_protocol import enums_pb2


class EngineRunKind(ApiEnumValue):
    BUILD: ClassVar[Self]
    PREVIEW: ClassVar[Self]
    ROW_COUNT: ClassVar[Self]
    DOWNLOAD: ClassVar[Self]
    INGEST: ClassVar[Self]


EngineRunKind.BUILD = EngineRunKind(enums_pb2.ENGINE_RUN_KIND_BUILD, api_token('EngineRunKind', enums_pb2.ENGINE_RUN_KIND_BUILD))
EngineRunKind.PREVIEW = EngineRunKind(enums_pb2.ENGINE_RUN_KIND_PREVIEW, api_token('EngineRunKind', enums_pb2.ENGINE_RUN_KIND_PREVIEW))
EngineRunKind.ROW_COUNT = EngineRunKind(enums_pb2.ENGINE_RUN_KIND_ROW_COUNT, api_token('EngineRunKind', enums_pb2.ENGINE_RUN_KIND_ROW_COUNT))
EngineRunKind.DOWNLOAD = EngineRunKind(enums_pb2.ENGINE_RUN_KIND_DOWNLOAD, api_token('EngineRunKind', enums_pb2.ENGINE_RUN_KIND_DOWNLOAD))
EngineRunKind.INGEST = EngineRunKind(enums_pb2.ENGINE_RUN_KIND_INGEST, api_token('EngineRunKind', enums_pb2.ENGINE_RUN_KIND_INGEST))


class EngineRunStatus(ApiEnumValue):
    RUNNING: ClassVar[Self]
    SUCCESS: ClassVar[Self]
    FAILED: ClassVar[Self]
    CANCELLED: ClassVar[Self]

    @property
    def is_terminal(self) -> bool:
        return self in {EngineRunStatus.SUCCESS, EngineRunStatus.FAILED, EngineRunStatus.CANCELLED}

    def blocks_transition_to(self, next_status: EngineRunStatus) -> bool:
        return self.is_terminal and next_status != self


EngineRunStatus.RUNNING = EngineRunStatus(enums_pb2.ENGINE_RUN_STATUS_RUNNING, api_token('EngineRunStatus', enums_pb2.ENGINE_RUN_STATUS_RUNNING))
EngineRunStatus.SUCCESS = EngineRunStatus(enums_pb2.ENGINE_RUN_STATUS_SUCCESS, api_token('EngineRunStatus', enums_pb2.ENGINE_RUN_STATUS_SUCCESS))
EngineRunStatus.FAILED = EngineRunStatus(enums_pb2.ENGINE_RUN_STATUS_FAILED, api_token('EngineRunStatus', enums_pb2.ENGINE_RUN_STATUS_FAILED))
EngineRunStatus.CANCELLED = EngineRunStatus(enums_pb2.ENGINE_RUN_STATUS_CANCELLED, api_token('EngineRunStatus', enums_pb2.ENGINE_RUN_STATUS_CANCELLED))


class EngineRunExecutionCategory(ApiEnumValue):
    READ: ClassVar[Self]
    STEP: ClassVar[Self]
    PLAN: ClassVar[Self]
    COMPUTE: ClassVar[Self]
    WRITE: ClassVar[Self]

    @property
    def is_query_plan(self) -> bool:
        return self == EngineRunExecutionCategory.PLAN

    @property
    def default_step_type(self) -> str:
        match self:
            case EngineRunExecutionCategory.READ | EngineRunExecutionCategory.WRITE:
                return self.value
            case _:
                return 'unknown'


EngineRunExecutionCategory.READ = EngineRunExecutionCategory(
    enums_pb2.ENGINE_RUN_EXECUTION_CATEGORY_READ, api_token('EngineRunExecutionCategory', enums_pb2.ENGINE_RUN_EXECUTION_CATEGORY_READ)
)
EngineRunExecutionCategory.STEP = EngineRunExecutionCategory(
    enums_pb2.ENGINE_RUN_EXECUTION_CATEGORY_STEP, api_token('EngineRunExecutionCategory', enums_pb2.ENGINE_RUN_EXECUTION_CATEGORY_STEP)
)
EngineRunExecutionCategory.PLAN = EngineRunExecutionCategory(
    enums_pb2.ENGINE_RUN_EXECUTION_CATEGORY_PLAN, api_token('EngineRunExecutionCategory', enums_pb2.ENGINE_RUN_EXECUTION_CATEGORY_PLAN)
)
EngineRunExecutionCategory.COMPUTE = EngineRunExecutionCategory(
    enums_pb2.ENGINE_RUN_EXECUTION_CATEGORY_COMPUTE, api_token('EngineRunExecutionCategory', enums_pb2.ENGINE_RUN_EXECUTION_CATEGORY_COMPUTE)
)
EngineRunExecutionCategory.WRITE = EngineRunExecutionCategory(
    enums_pb2.ENGINE_RUN_EXECUTION_CATEGORY_WRITE, api_token('EngineRunExecutionCategory', enums_pb2.ENGINE_RUN_EXECUTION_CATEGORY_WRITE)
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


class EngineRunResultSummary(BaseModel):
    model_config = ConfigDict(extra='allow')

    row_count: int | str | None = None
    schema_: dict[str, str] | None = Field(default_factory=dict, alias='schema')
    data: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None


class EngineRunExecutionEntry(BaseModel):
    key: str
    label: str
    category: EngineRunExecutionCategory
    order: int
    duration_ms: float | None = None
    share_pct: float | None = None
    optimized_plan: str | None = None
    unoptimized_plan: str | None = None
    metadata: dict[str, Any] | None = None


class EngineRunBaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    namespace: str
    analysis_id: str | None = None
    datasource_id: str
    kind: EngineRunKind
    status: EngineRunStatus
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
    execution_entries: list[EngineRunExecutionEntry] = Field(default_factory=list)


class EngineRunResponseSchema(EngineRunBaseSchema):
    id: str


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
    kind: EngineRunKind
    status: EngineRunStatus
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
