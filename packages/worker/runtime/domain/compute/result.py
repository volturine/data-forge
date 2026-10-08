from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ComputeWorkerResult:
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
