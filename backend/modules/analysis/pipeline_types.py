from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class VariableOption:
    label: str
    value: str | int | float | bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VariableOption:
        return cls(
            label=str(data.get('label', '')),
            value=data.get('value', ''),
        )

    def to_dict(self) -> dict[str, Any]:
        return {'label': self.label, 'value': self.value}


@dataclass(slots=True)
class VariableOptionSource:
    tab_id: str
    column: str
    limit: int = 100

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VariableOptionSource:
        raw_limit = data.get('limit', 100)
        limit = raw_limit if isinstance(raw_limit, int) else 100
        return cls(
            tab_id=str(data.get('tab_id', '')),
            column=str(data.get('column', '')),
            limit=limit,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'tab_id': self.tab_id,
            'column': self.column,
            'limit': self.limit,
        }


@dataclass(slots=True)
class AnalysisVariable:
    id: str
    label: str
    type: str
    default_value: Any
    required: bool = True
    options: list[VariableOption] = field(default_factory=list)
    option_source: VariableOptionSource | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalysisVariable:
        raw_options = data.get('options', [])
        raw_option_source = data.get('option_source')
        return cls(
            id=str(data.get('id', '')),
            label=str(data.get('label', '')),
            type=str(data.get('type', '')),
            default_value=data.get('default_value'),
            required=bool(data.get('required', True)),
            options=[VariableOption.from_dict(option) for option in raw_options if isinstance(option, dict)],
            option_source=(VariableOptionSource.from_dict(raw_option_source) if isinstance(raw_option_source, dict) else None),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            'id': self.id,
            'label': self.label,
            'type': self.type,
            'default_value': self.default_value,
            'required': self.required,
            'options': [option.to_dict() for option in self.options],
        }
        if self.option_source is not None:
            result['option_source'] = self.option_source.to_dict()
        return result


@dataclass(slots=True)
class DashboardLayoutItem:
    widget_id: str
    x: int
    y: int
    w: int
    h: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DashboardLayoutItem:
        return cls(
            widget_id=str(data.get('widget_id', '')),
            x=int(data.get('x', 0)),
            y=int(data.get('y', 0)),
            w=int(data.get('w', 0)),
            h=int(data.get('h', 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'widget_id': self.widget_id,
            'x': self.x,
            'y': self.y,
            'w': self.w,
            'h': self.h,
        }


@dataclass(slots=True)
class DashboardWidget:
    id: str
    type: str
    title: str
    config: dict[str, Any]
    source_tab_id: str | None = None
    description: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DashboardWidget:
        raw_config = data.get('config')
        return cls(
            id=str(data.get('id', '')),
            type=str(data.get('type', '')),
            title=str(data.get('title', '')),
            source_tab_id=data.get('source_tab_id'),
            description=data.get('description'),
            config=raw_config if isinstance(raw_config, dict) else {},
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            'id': self.id,
            'type': self.type,
            'title': self.title,
            'config': self.config,
            'source_tab_id': self.source_tab_id,
        }
        if self.description is not None:
            result['description'] = self.description
        return result


@dataclass(slots=True)
class DashboardDefinition:
    id: str
    name: str
    description: str | None = None
    layout: list[DashboardLayoutItem] = field(default_factory=list)
    widgets: list[DashboardWidget] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DashboardDefinition:
        raw_layout = data.get('layout', [])
        raw_widgets = data.get('widgets', [])
        return cls(
            id=str(data.get('id', '')),
            name=str(data.get('name', '')),
            description=data.get('description'),
            layout=[DashboardLayoutItem.from_dict(item) for item in raw_layout if isinstance(item, dict)],
            widgets=[DashboardWidget.from_dict(widget) for widget in raw_widgets if isinstance(widget, dict)],
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            'id': self.id,
            'name': self.name,
            'layout': [item.to_dict() for item in self.layout],
            'widgets': [widget.to_dict() for widget in self.widgets],
        }
        if self.description is not None:
            result['description'] = self.description
        return result


@dataclass(slots=True)
class PipelineStep:
    """A single step in an analysis pipeline tab."""

    id: str
    type: str
    config: dict[str, object]
    depends_on: list[str] = field(default_factory=list)
    is_applied: bool | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineStep:
        raw_config = data.get('config')
        raw_deps = data.get('depends_on')
        return cls(
            id=str(data.get('id', '')),
            type=str(data.get('type', '')),
            config=raw_config if isinstance(raw_config, dict) else {},
            depends_on=list(raw_deps) if isinstance(raw_deps, list) else [],
            is_applied=data.get('is_applied'),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'type': self.type,
            'config': self.config,
            'depends_on': self.depends_on,
            'is_applied': self.is_applied,
        }


@dataclass(slots=True)
class TabDatasource:
    """Datasource reference within an analysis tab."""

    id: str
    config: dict[str, Any]
    analysis_tab_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TabDatasource:
        raw_config = data.get('config')
        return cls(
            id=str(data.get('id', '')),
            config=raw_config if isinstance(raw_config, dict) else {},
            analysis_tab_id=data.get('analysis_tab_id'),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            'id': self.id,
            'config': self.config,
            # Keep explicit null for stable API contracts and downstream validators.
            'analysis_tab_id': self.analysis_tab_id,
        }
        return result


@dataclass(slots=True)
class TabOutput:
    """Output configuration for an analysis tab."""

    result_id: str
    format: str
    filename: str
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TabOutput:
        extra = {k: v for k, v in data.items() if k not in {'result_id', 'format', 'filename'}}
        return cls(
            result_id=str(data.get('result_id', '')),
            format=str(data.get('format', '')),
            filename=str(data.get('filename', '')),
            extra=extra,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'result_id': self.result_id,
            'format': self.format,
            'filename': self.filename,
            **self.extra,
        }


@dataclass(slots=True)
class PipelineTab:
    """A single tab in an analysis pipeline."""

    id: str
    name: str
    datasource: TabDatasource
    output: TabOutput
    steps: list[PipelineStep] = field(default_factory=list)
    parent_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineTab:
        raw_ds = data.get('datasource')
        raw_output = data.get('output')
        raw_steps = data.get('steps', [])
        return cls(
            id=str(data.get('id', '')),
            name=str(data.get('name', '')),
            datasource=TabDatasource.from_dict(raw_ds if isinstance(raw_ds, dict) else {}),
            output=TabOutput.from_dict(raw_output if isinstance(raw_output, dict) else {}),
            steps=[PipelineStep.from_dict(s) for s in raw_steps if isinstance(s, dict)],
            parent_id=data.get('parent_id'),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            'id': self.id,
            'name': self.name,
            'datasource': self.datasource.to_dict(),
            'output': self.output.to_dict(),
            'steps': [s.to_dict() for s in self.steps],
        }
        if self.parent_id is not None:
            result['parent_id'] = self.parent_id
        return result


@dataclass(slots=True)
class PipelineDefinition:
    """The full pipeline definition for an analysis, stored as JSON."""

    tabs: list[PipelineTab] = field(default_factory=list)
    variables: list[AnalysisVariable] = field(default_factory=list)
    dashboards: list[DashboardDefinition] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineDefinition:
        raw_tabs = data.get('tabs', [])
        raw_variables = data.get('variables', [])
        raw_dashboards = data.get('dashboards', [])
        return cls(
            tabs=[PipelineTab.from_dict(t) for t in raw_tabs if isinstance(t, dict)],
            variables=[AnalysisVariable.from_dict(v) for v in raw_variables if isinstance(v, dict)],
            dashboards=[DashboardDefinition.from_dict(d) for d in raw_dashboards if isinstance(d, dict)],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'tabs': [t.to_dict() for t in self.tabs],
            'variables': [variable.to_dict() for variable in self.variables],
            'dashboards': [dashboard.to_dict() for dashboard in self.dashboards],
        }

    def find_tab(self, tab_id: str) -> PipelineTab:
        """Find a tab by ID or raise ValueError."""
        tab = next((t for t in self.tabs if t.id == tab_id), None)
        if not tab:
            raise ValueError(f'Tab {tab_id} not found')
        return tab


def parse_pipeline(raw: dict[str, Any]) -> PipelineDefinition:
    """Parse a raw JSON dict (from DB) into a PipelineDefinition."""
    return PipelineDefinition.from_dict(raw)
