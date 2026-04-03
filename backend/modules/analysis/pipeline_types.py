from __future__ import annotations

from typing import NotRequired, Required, TypedDict

from modules.analysis.step_types import StepType


class AnalysisPipelineStep(TypedDict, total=False):
    id: Required[str]
    type: Required[StepType]
    config: Required[dict[str, object]]
    depends_on: NotRequired[list[str]]
    is_applied: NotRequired[bool | None]


class AnalysisTabDatasource(TypedDict):
    id: str
    analysis_tab_id: str | None
    config: dict[str, object]


class AnalysisTabOutput(TypedDict, total=False):
    result_id: Required[str]
    format: Required[str]
    filename: Required[str]
    datasource_type: str
    build_mode: str
    iceberg: dict[str, object]
    notification: dict[str, object] | None


class AnalysisTab(TypedDict):
    id: str
    name: str
    parent_id: str | None
    datasource: AnalysisTabDatasource
    output: AnalysisTabOutput
    steps: list[AnalysisPipelineStep]


class AnalysisPipelineDefinition(TypedDict, total=False):
    tabs: list[AnalysisTab]
    steps: list[AnalysisPipelineStep]
