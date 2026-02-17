from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AnalysisVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    analysis_id: str
    version: int
    name: str
    description: str | None
    pipeline_definition: dict
    created_at: datetime


class AnalysisVersionUpdate(BaseModel):
    name: str
