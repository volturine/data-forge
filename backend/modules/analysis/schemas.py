from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from modules.analysis.step_schemas import StepType


class PipelineStepSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: StepType
    config: dict
    depends_on: list[str] = []
    is_applied: bool | None = None


class TabDatasourceConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra='allow')

    branch: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class TabDatasourceSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[
        str,
        StringConstraints(min_length=1, strip_whitespace=True),
        Field(
            description=('ID of an existing datasource from GET /api/v1/datasource. Must be a real datasource ID, not an invented value.')
        ),
    ]
    analysis_tab_id: str | None = None
    config: TabDatasourceConfig


class TabOutputSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra='allow')

    output_datasource_id: Annotated[
        str,
        StringConstraints(min_length=1, strip_whitespace=True),
        Field(description=('ID of an existing datasource to write output to. Typically the same datasource ID used in datasource.id.')),
    ]
    format: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    filename: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class TabSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    parent_id: str | None = None
    datasource: TabDatasourceSchema
    output: TabOutputSchema
    steps: list[PipelineStepSchema] = []


class AnalysisCreateSchema(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    description: str | None = None
    tabs: list[TabSchema]

    @model_validator(mode='before')
    @classmethod
    def reject_pipeline_steps(cls, data: Any) -> Any:
        if isinstance(data, dict) and 'pipeline_steps' in data:
            raise ValueError("'pipeline_steps' is not accepted; use 'tabs'")
        return data


class AnalysisUpdateSchema(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    tabs: list[TabSchema]
    client_id: str | None = None
    lock_token: str | None = None

    @model_validator(mode='before')
    @classmethod
    def reject_pipeline_steps(cls, data: Any) -> Any:
        if isinstance(data, dict) and 'pipeline_steps' in data:
            raise ValueError("'pipeline_steps' is not accepted; use 'tabs'")
        return data


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
