import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from modules.analysis.step_types import is_step_type


class PipelineStepSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    config: dict[str, object]
    depends_on: list[str] = Field(default_factory=list)
    is_applied: bool | None = None

    @field_validator('type')
    @classmethod
    def validate_type(cls, value: str) -> str:
        if not is_step_type(value):
            raise ValueError(f"Unknown step type '{value}'")
        return value


class TabDatasourceConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra='allow')

    branch: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class TabDatasourceSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[
        str,
        StringConstraints(min_length=1, strip_whitespace=True),
        Field(
            description=('ID of an existing datasource from GET /api/v1/datasource. Must be a real datasource ID, not an invented value.'),
        ),
    ]
    analysis_tab_id: str | None = None
    config: TabDatasourceConfig


_UUID4_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$', re.IGNORECASE)


class TabOutputSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra='allow')

    result_id: Annotated[
        str,
        StringConstraints(min_length=1, strip_whitespace=True),
        Field(
            description=(
                "UUID v4 for this tab's output. When creating a new analysis, call generate_uuid to get one. "
                'When updating an existing analysis, reuse the current result_id from the analysis response.'
            ),
        ),
    ]
    format: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    filename: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]

    @field_validator('result_id')
    @classmethod
    def validate_uuid4(cls, v: str) -> str:
        if not _UUID4_RE.match(v):
            raise ValueError(f'result_id must be a valid UUID v4, got: {v!r}')
        return v


class TabSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    parent_id: str | None = None
    datasource: TabDatasourceSchema
    output: TabOutputSchema
    steps: list[PipelineStepSchema] = Field(default_factory=list)


def _reject_pipeline_steps(data: Any) -> Any:
    if isinstance(data, dict) and 'pipeline_steps' in data:
        raise ValueError("'pipeline_steps' is not accepted; use 'tabs'")
    return data


def _reject_status(data: Any) -> Any:
    if isinstance(data, dict) and 'status' in data:
        raise ValueError("'status' is not accepted on analysis payloads; build lifecycle is tracked separately")
    return data


class _RejectPipelineStepsModel(BaseModel):
    @model_validator(mode='before')
    @classmethod
    def reject_pipeline_steps(cls, data: Any) -> Any:
        return _reject_status(_reject_pipeline_steps(data))


class AnalysisCreateSchema(_RejectPipelineStepsModel):
    name: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    description: str | None = None
    tabs: list[TabSchema]


class AnalysisUpdateSchema(_RejectPipelineStepsModel):
    name: str | None = None
    description: str | None = None
    tabs: list[TabSchema]


class AnalysisResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    pipeline_definition: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    result_path: str | None
    thumbnail: str | None


class AnalysisGalleryItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    thumbnail: str | None
    created_at: datetime
    updated_at: datetime


class CodeExportFormat(StrEnum):
    POLARS = 'polars'
    SQL = 'sql'


class CodeExportRequestSchema(BaseModel):
    model_config = ConfigDict(extra='forbid')

    format: CodeExportFormat
    tab_id: str | None = None


class CodeExportResponseSchema(BaseModel):
    model_config = ConfigDict(extra='forbid')

    code: str
    warnings: list[str] = Field(default_factory=list)
    filename: str
    format: CodeExportFormat
    tab_id: str | None = None
