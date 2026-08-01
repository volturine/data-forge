from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class EngineStatusInfo:
    """Worker-reported engine snapshot fields persisted by the API process."""

    analysis_id: str
    resource_id: str
    status: str
    process_id: int | None
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
