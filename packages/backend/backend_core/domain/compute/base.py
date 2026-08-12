from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class EngineStatusInfo:
    """Worker-reported engine snapshot fields persisted by the API process."""

    analysis_id: str
    resource_id: str
    status: str
    container_id: str | None
    image_digest: str | None
    lifecycle_status: str | None
    termination_reason: str | None
    exit_code: int | None
    oom_killed: bool | None
    supervisor_id: str | None
    owner_id: str | None
    last_activity: str | None
    current_job_id: str | None
    resource_config: dict[str, Any] | None
    effective_resources: dict[str, Any] | None
    defaults: dict[str, Any]
    scope: str | None = None
    reuse_policy: str | None = None
    datasource_id: str | None = None
    build_id: str | None = None
    current_build_id: str | None = None
    current_engine_run_id: str | None = None
