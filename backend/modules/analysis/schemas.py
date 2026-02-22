from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PipelineStepSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    config: dict
    depends_on: list[str] = []
    is_applied: bool | None = None


class TabSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    type: str = 'datasource'
    parent_id: str | None = None
    datasource_id: str | None = None
    datasource_config: dict | None = None
    output_datasource_id: str | None = None
    steps: list[PipelineStepSchema] = []


class AnalysisCreateSchema(BaseModel):
    name: str
    description: str | None = None
    datasource_ids: list[str]
    pipeline_steps: list[PipelineStepSchema]
    tabs: list[TabSchema] = []
    output_branch: str | None = None


class AnalysisUpdateSchema(BaseModel):
    name: str | None = None
    description: str | None = None
    pipeline_steps: list[PipelineStepSchema] | None = None
    status: str | None = None
    tabs: list[TabSchema] | None = None
    client_id: str | None = None
    lock_token: str | None = None
    output_branch: str | None = None


class AnalysisResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    pipeline_definition: dict
    status: str
    created_at: datetime
    updated_at: datetime
    result_path: str | None
    thumbnail: str | None
    tabs: list[TabSchema] = []


class AnalysisGalleryItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    thumbnail: str | None
    created_at: datetime
    updated_at: datetime
