from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AnalysisVersionSummary(BaseModel):
    """Lightweight version info for list endpoints (excludes pipeline_definition)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    analysis_id: str
    version: int
    name: str
    description: str | None
    created_at: datetime


class AnalysisVersionResponse(AnalysisVersionSummary):
    """Full version response including pipeline_definition."""

    pipeline_definition: dict[str, Any]


class AnalysisVersionUpdate(BaseModel):
    name: str
