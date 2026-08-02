from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from builds.build_live import ActiveBuild
from runtime.domain.compute import schemas as compute_schemas
from runtime.time import utc_now

BuildEmitter = Callable[[compute_schemas.BuildEvent], Awaitable[None]]


@dataclass(frozen=True)
class BuildEventContext:
    build_id: str
    analysis_id: str
    emitted_at: datetime
    current_kind: str | None
    current_datasource_id: str | None
    tab_id: str | None
    tab_name: str | None
    current_output_id: str | None
    current_output_name: str | None
    engine_run_id: str | None

    @classmethod
    def from_build(
        cls,
        build: ActiveBuild,
        analysis_id: str,
        *,
        emitted_at: datetime | None = None,
        current_kind: str | None = None,
        current_datasource_id: str | None = None,
        tab_id: str | None = None,
        tab_name: str | None = None,
        current_output_id: str | None = None,
        current_output_name: str | None = None,
        engine_run_id: str | None = None,
    ) -> "BuildEventContext":
        return cls(
            build_id=build.build_id,
            analysis_id=analysis_id,
            emitted_at=emitted_at or utc_now(),
            current_kind=current_kind if current_kind is not None else build.current_kind,
            current_datasource_id=current_datasource_id if current_datasource_id is not None else build.current_datasource_id,
            tab_id=tab_id,
            tab_name=tab_name,
            current_output_id=current_output_id if current_output_id is not None else build.current_output_id,
            current_output_name=current_output_name if current_output_name is not None else build.current_output_name,
            engine_run_id=engine_run_id if engine_run_id is not None else build.current_engine_run_id,
        )

    def payload(self) -> dict[str, object]:
        return {
            "build_id": self.build_id,
            "analysis_id": self.analysis_id,
            "emitted_at": self.emitted_at,
            "current_kind": self.current_kind,
            "current_datasource_id": self.current_datasource_id,
            "tab_id": self.tab_id,
            "tab_name": self.tab_name,
            "current_output_id": self.current_output_id,
            "current_output_name": self.current_output_name,
            "engine_run_id": self.engine_run_id,
        }


class BuildCancelledError(Exception):
    def __init__(
        self,
        run_id: str,
        *,
        cancelled_at: str | None = None,
        cancelled_by: str | None = None,
    ) -> None:
        super().__init__("Build cancelled")
        self.run_id = run_id
        self.cancelled_at = cancelled_at
        self.cancelled_by = cancelled_by


def event_model(payload: dict[str, object]) -> compute_schemas.BuildEvent:
    return compute_schemas.BuildEventAdapter.validate_python(payload)


def build_event(
    build: ActiveBuild,
    analysis_id: str,
    payload: dict[str, object],
) -> compute_schemas.BuildEvent:
    return event_model({**BuildEventContext.from_build(build, analysis_id).payload(), **payload})


async def emit_build_event(
    emitter: BuildEmitter | None,
    *,
    event: compute_schemas.BuildEvent,
) -> None:
    if emitter is not None:
        await emitter(event)


def estimate_remaining(elapsed_ms: int, completed_steps: int, total_steps: int) -> int | None:
    if completed_steps <= 0 or total_steps <= completed_steps:
        return None
    return int((elapsed_ms / completed_steps) * max(total_steps - completed_steps, 0))


async def emit_progress(
    emitter: BuildEmitter | None,
    *,
    build: ActiveBuild,
    analysis_id: str,
    progress: float,
    elapsed_ms: int,
    completed_steps: int,
    total_steps: int,
    current_step: str | None,
    current_step_index: int | None,
    tab_id: str | None,
    tab_name: str | None,
    current_output_id: str | None = None,
    current_output_name: str | None = None,
    engine_run_id: str | None = None,
) -> None:
    await emit_build_event(
        emitter,
        event=build_event(
            build,
            analysis_id,
            {
                "type": compute_schemas.BuildEventType.PROGRESS,
                "progress": progress,
                "elapsed_ms": elapsed_ms,
                "estimated_remaining_ms": estimate_remaining(elapsed_ms, completed_steps, total_steps),
                "current_step": current_step,
                "current_step_index": current_step_index,
                "total_steps": total_steps,
                "tab_id": tab_id,
                "tab_name": tab_name,
                "current_output_id": current_output_id,
                "current_output_name": current_output_name,
                "engine_run_id": engine_run_id,
            },
        ),
    )
