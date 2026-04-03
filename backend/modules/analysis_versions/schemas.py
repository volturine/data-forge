from datetime import datetime

from pydantic import BaseModel, ConfigDict

from modules.analysis.pipeline_types import AnalysisPipelineDefinition


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

    pipeline_definition: AnalysisPipelineDefinition


class AnalysisVersionUpdate(BaseModel):
    name: str
