from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class AnalysisTemplate:
    id: str
    name: str
    description: str
    icon: str
    required_input_columns: tuple[str, ...]
    steps: tuple[dict[str, Any], ...]

    def to_summary(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'icon': self.icon,
            'step_count': len(self.steps),
        }

    def to_detail(self) -> dict[str, Any]:
        return {
            **self.to_summary(),
            'required_input_columns': list(self.required_input_columns),
            'steps': [dict(step) for step in self.steps],
        }


def _template_file() -> Path:
    return Path(__file__).with_name('builtin_templates.json')


@lru_cache(maxsize=1)
def load_builtin_templates() -> tuple[AnalysisTemplate, ...]:
    payload = json.loads(_template_file().read_text())
    templates: list[AnalysisTemplate] = []
    for item in payload:
        steps = tuple(item.get('steps', []))
        templates.append(
            AnalysisTemplate(
                id=str(item['id']),
                name=str(item['name']),
                description=str(item['description']),
                icon=str(item.get('icon', 'file')),
                required_input_columns=tuple(str(value) for value in item.get('required_input_columns', [])),
                steps=steps,
            ),
        )
    return tuple(templates)


def list_templates() -> list[dict[str, Any]]:
    return [template.to_summary() for template in load_builtin_templates()]


def get_template(template_id: str) -> AnalysisTemplate:
    for template in load_builtin_templates():
        if template.id == template_id:
            return template
    raise ValueError(f"Unknown analysis template '{template_id}'")
