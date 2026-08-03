from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineDefinition:
        raw_tabs = data.get('tabs', [])
        return cls(
            tabs=[PipelineTab.from_dict(t) for t in raw_tabs if isinstance(t, dict)],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'tabs': [t.to_dict() for t in self.tabs],
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
