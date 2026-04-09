import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from modules.analysis.models import AnalysisStatus
from modules.analysis.step_schemas import StepType


class AnalysisVariableType(StrEnum):
    STRING = 'string'
    NUMBER = 'number'
    BOOLEAN = 'boolean'
    SINGLE_SELECT = 'single_select'
    MULTI_SELECT = 'multi_select'
    DATE = 'date'
    DATE_RANGE = 'date_range'


class DashboardWidgetType(StrEnum):
    DATASET_PREVIEW = 'dataset_preview'
    CHART = 'chart'
    METRIC_KPI = 'metric_kpi'
    TEXT_HEADER = 'text_header'


class MetricAggregation(StrEnum):
    SUM = 'sum'
    MEAN = 'mean'
    MIN = 'min'
    MAX = 'max'
    COUNT = 'count'
    MEDIAN = 'median'
    N_UNIQUE = 'n_unique'


class VariableOptionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    value: str | int | float | bool


class VariableOptionSourceSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tab_id: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    column: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    limit: int = Field(100, ge=1, le=500)


class DateRangeValueSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    end: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class VariableDefinitionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    label: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    type: AnalysisVariableType
    default_value: Any
    required: bool = True
    options: list[VariableOptionSchema] = Field(default_factory=list)
    option_source: VariableOptionSourceSchema | None = None


class VariableRefSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: Literal['variable_ref']
    variable_id: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    value_key: Literal['start', 'end'] | None = None


class DashboardLayoutItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    widget_id: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    x: int = Field(0, ge=0)
    y: int = Field(0, ge=0)
    w: int = Field(6, ge=1, le=12)
    h: int = Field(2, ge=1, le=8)


class DatasetPreviewWidgetConfigSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page_size: int = Field(25, ge=1, le=200)
    searchable: bool = True


class MetricComparisonSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    aggregation: MetricAggregation
    column: str | None = None
    label: str | None = None


class MetricWidgetConfigSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    aggregation: MetricAggregation
    column: str | None = None
    comparison: MetricComparisonSchema | None = None


class TextHeaderWidgetConfigSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    text: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    level: int = Field(2, ge=1, le=6)


class DashboardWidgetSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    type: DashboardWidgetType
    title: str = ''
    description: str | None = None
    source_tab_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class DashboardDefinitionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    name: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    description: str | None = None
    layout: list[DashboardLayoutItemSchema] = Field(default_factory=list)
    widgets: list[DashboardWidgetSchema] = Field(default_factory=list)


class DashboardDetailResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    dashboard: DashboardDefinitionSchema
    variables: list[VariableDefinitionSchema]
    widget_dependencies: dict[str, list[str]]


class DashboardWidgetPageSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page: int = Field(1, ge=1)
    page_size: int = Field(25, ge=1, le=200)


class DashboardSelectionFilterSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    column: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    values: list[str | int | float | bool] = Field(default_factory=list)


class DashboardRunRequestSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    variable_values: dict[str, Any] = Field(default_factory=dict)
    widget_ids: list[str] | None = None
    widget_page: dict[str, DashboardWidgetPageSchema] = Field(default_factory=dict)
    selection_filters: dict[str, DashboardSelectionFilterSchema] = Field(default_factory=dict)


class DatasetPreviewResultSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    columns: list[str]
    column_types: dict[str, str] = Field(default_factory=dict)
    rows: list[dict[str, Any]]
    row_count: int
    page: int
    page_size: int


class ChartResultSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    schema_map: dict[str, str] = Field(serialization_alias='schema', validation_alias='schema')
    data: list[dict[str, Any]]
    config: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class MetricResultSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label: str
    value: str | int | float
    comparison: str | int | float | None = None


class TextHeaderResultSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    text: str
    level: int


class DashboardWidgetRunResultSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    widget_id: str
    type: DashboardWidgetType
    title: str
    source_tab_id: str | None = None
    variable_ids: list[str] = Field(default_factory=list)
    status: Literal['success', 'empty', 'error'] = 'success'
    last_refresh_at: datetime
    variable_state: dict[str, Any]
    dataset: DatasetPreviewResultSchema | None = None
    chart: ChartResultSchema | None = None
    metric: MetricResultSchema | None = None
    header: TextHeaderResultSchema | None = None
    error: str | None = None


class DashboardRunResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    dashboard_id: str
    variable_state: dict[str, Any]
    widget_dependencies: dict[str, list[str]]
    widgets: list[DashboardWidgetRunResultSchema]


class PipelineStepSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: StepType
    config: dict[str, object]
    depends_on: list[str] = Field(default_factory=list)
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


class _RejectPipelineStepsModel(BaseModel):
    @model_validator(mode='before')
    @classmethod
    def reject_pipeline_steps(cls, data: Any) -> Any:
        return _reject_pipeline_steps(data)


class DashboardValidateRequestSchema(_RejectPipelineStepsModel):
    name: str | None = None
    description: str | None = None
    tabs: list[TabSchema]
    variables: list[VariableDefinitionSchema] = Field(default_factory=list)
    dashboards: list[DashboardDefinitionSchema] = Field(default_factory=list)


class AnalysisCreateSchema(_RejectPipelineStepsModel):
    name: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    description: str | None = None
    tabs: list[TabSchema]
    variables: list[VariableDefinitionSchema] = Field(default_factory=list)
    dashboards: list[DashboardDefinitionSchema] = Field(default_factory=list)


class AnalysisUpdateSchema(_RejectPipelineStepsModel):
    name: str | None = None
    description: str | None = None
    status: AnalysisStatus | None = None
    tabs: list[TabSchema]
    variables: list[VariableDefinitionSchema] = Field(default_factory=list)
    dashboards: list[DashboardDefinitionSchema] = Field(default_factory=list)


class AnalysisResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    pipeline_definition: dict[str, Any]
    status: AnalysisStatus
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
