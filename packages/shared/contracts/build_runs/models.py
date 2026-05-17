import datetime as dt
from typing import Any

from sqlalchemy import JSON, Column, DateTime, Enum as SAEnum, Float, Integer, String, UniqueConstraint
from sqlmodel import Field, SQLModel

from contracts.compute import schemas as compute_schemas
from contracts.enums import DataForgeStrEnum


class BuildRunStatus(DataForgeStrEnum):
    QUEUED = 'queued'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'
    ORPHANED = 'orphaned'

    @property
    def is_terminal(self) -> bool:
        return self in {BuildRunStatus.COMPLETED, BuildRunStatus.FAILED, BuildRunStatus.CANCELLED, BuildRunStatus.ORPHANED}

    def to_active_build_status(self) -> tuple[compute_schemas.ActiveBuildStatus, str | None]:
        if self == BuildRunStatus.QUEUED:
            return compute_schemas.ActiveBuildStatus.QUEUED, None
        if self == BuildRunStatus.RUNNING:
            return compute_schemas.ActiveBuildStatus.RUNNING, None
        if self == BuildRunStatus.COMPLETED:
            return compute_schemas.ActiveBuildStatus.COMPLETED, None
        if self == BuildRunStatus.CANCELLED:
            return compute_schemas.ActiveBuildStatus.CANCELLED, None
        if self == BuildRunStatus.FAILED:
            return compute_schemas.ActiveBuildStatus.FAILED, None
        return compute_schemas.ActiveBuildStatus.FAILED, 'Build orphaned during startup recovery'


class BuildRun(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    __tablename__ = 'build_runs'  # type: ignore[assignment]

    def apply_event_context(self, event: compute_schemas.BuildEvent) -> None:
        if event.current_datasource_id is not None:
            self.current_datasource_id = event.current_datasource_id
        if event.tab_id is not None:
            self.current_tab_id = event.tab_id
        if event.tab_name is not None:
            self.current_tab_name = event.tab_name
        if event.current_output_id is not None:
            self.current_output_id = event.current_output_id
        if event.current_output_name is not None:
            self.current_output_name = event.current_output_name
        if event.engine_run_id is not None:
            self.current_engine_run_id = event.engine_run_id

    def apply_runtime_event(self, event: compute_schemas.BuildEvent) -> None:
        if isinstance(event, compute_schemas.BuildProgressEvent):
            self.progress = event.progress
            self.elapsed_ms = event.elapsed_ms
            self.estimated_remaining_ms = event.estimated_remaining_ms
            self.current_step = event.current_step
            self.current_step_index = event.current_step_index
            self.total_steps = event.total_steps
        elif isinstance(event, compute_schemas.BuildStepStartEvent | compute_schemas.BuildStepCompleteEvent | compute_schemas.BuildStepFailedEvent):
            self.current_step = event.step_name
            self.current_step_index = event.build_step_index
            self.total_steps = event.total_steps

    def apply_terminal_event(self, event: compute_schemas.BuildEvent) -> bool:
        if self.status.is_terminal:
            return False
        if isinstance(event, compute_schemas.BuildCompleteEvent):
            self.status = BuildRunStatus.COMPLETED
            self.progress = event.progress
            self.elapsed_ms = event.elapsed_ms
            self.total_steps = event.total_steps
            self.duration_ms = event.duration_ms
            self.error_message = None
            self.completed_at = event.emitted_at
            return True
        if isinstance(event, compute_schemas.BuildFailedEvent):
            self.status = BuildRunStatus.FAILED
            self.progress = event.progress
            self.elapsed_ms = event.elapsed_ms
            self.total_steps = event.total_steps
            self.duration_ms = event.duration_ms
            self.error_message = event.error
            self.completed_at = event.emitted_at
            return True
        if isinstance(event, compute_schemas.BuildCancelledEvent):
            self.status = BuildRunStatus.CANCELLED
            self.progress = event.progress
            self.elapsed_ms = event.elapsed_ms
            self.total_steps = event.total_steps
            self.duration_ms = event.duration_ms
            self.error_message = 'Build cancelled'
            self.cancelled_at = event.cancelled_at
            self.cancelled_by = event.cancelled_by
            self.completed_at = event.emitted_at
            return True
        return True

    @staticmethod
    def terminal_status_for_event(event: compute_schemas.BuildEvent) -> BuildRunStatus | None:
        if isinstance(event, compute_schemas.BuildCompleteEvent):
            return BuildRunStatus.COMPLETED
        if isinstance(event, compute_schemas.BuildFailedEvent):
            return BuildRunStatus.FAILED
        if isinstance(event, compute_schemas.BuildCancelledEvent):
            return BuildRunStatus.CANCELLED
        return None

    @staticmethod
    def terminal_update_values(event: compute_schemas.BuildEvent) -> dict[str, Any] | None:
        if isinstance(event, compute_schemas.BuildCompleteEvent):
            return {
                'status': BuildRunStatus.COMPLETED,
                'progress': event.progress,
                'elapsed_ms': event.elapsed_ms,
                'total_steps': event.total_steps,
                'duration_ms': event.duration_ms,
                'error_message': None,
                'cancelled_at': None,
                'cancelled_by': None,
                'completed_at': event.emitted_at,
                'updated_at': event.emitted_at,
            }
        if isinstance(event, compute_schemas.BuildFailedEvent):
            return {
                'status': BuildRunStatus.FAILED,
                'progress': event.progress,
                'elapsed_ms': event.elapsed_ms,
                'total_steps': event.total_steps,
                'duration_ms': event.duration_ms,
                'error_message': event.error,
                'cancelled_at': None,
                'cancelled_by': None,
                'completed_at': event.emitted_at,
                'updated_at': event.emitted_at,
            }
        if isinstance(event, compute_schemas.BuildCancelledEvent):
            return {
                'status': BuildRunStatus.CANCELLED,
                'progress': event.progress,
                'elapsed_ms': event.elapsed_ms,
                'total_steps': event.total_steps,
                'duration_ms': event.duration_ms,
                'error_message': 'Build cancelled',
                'cancelled_at': event.cancelled_at,
                'cancelled_by': event.cancelled_by,
                'completed_at': event.emitted_at,
                'updated_at': event.emitted_at,
            }
        return None

    id: str = Field(sa_column=Column(String, primary_key=True))
    namespace: str = Field(sa_column=Column(String, nullable=False, index=True))
    schedule_id: str | None = Field(default=None, sa_column=Column(String, nullable=True, index=True))
    analysis_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    analysis_name: str = Field(sa_column=Column(String, nullable=False))
    status: BuildRunStatus = Field(
        sa_column=Column(SAEnum(BuildRunStatus, native_enum=False, values_callable=lambda enum_cls: enum_cls.values()), nullable=False, index=True)
    )
    request_json: dict[str, object] = Field(sa_column=Column(JSON, nullable=False))
    starter_json: dict[str, object] = Field(sa_column=Column(JSON, nullable=False))
    resource_config_json: dict[str, object] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    result_json: dict[str, object] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    current_engine_run_id: str | None = Field(default=None, sa_column=Column(String, nullable=True, index=True))
    current_kind: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    current_datasource_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    current_tab_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    current_tab_name: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    current_output_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    current_output_name: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    progress: float = Field(default=0.0, sa_column=Column(Float, nullable=False))
    elapsed_ms: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    estimated_remaining_ms: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    current_step: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    current_step_index: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    total_steps: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    total_tabs: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    duration_ms: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    error_message: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    cancelled_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    cancelled_by: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    created_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    started_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    completed_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    updated_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    version: int = Field(default=1, sa_column=Column(Integer, nullable=False))


class BuildEvent(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    __tablename__ = 'build_events'  # type: ignore[assignment]
    __table_args__ = (UniqueConstraint('build_id', 'sequence', name='uq_build_events_build_sequence'),)

    id: str = Field(sa_column=Column(String, primary_key=True))
    build_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    namespace: str = Field(sa_column=Column(String, nullable=False, index=True))
    sequence: int = Field(sa_column=Column(Integer, nullable=False))
    type: compute_schemas.BuildEventType = Field(
        sa_column=Column(SAEnum(compute_schemas.BuildEventType, native_enum=False, values_callable=lambda enum_cls: enum_cls.values()), nullable=False)
    )
    payload_json: dict[str, object] = Field(sa_column=Column(JSON, nullable=False))
    engine_run_id: str | None = Field(default=None, sa_column=Column(String, nullable=True, index=True))
    emitted_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    created_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
