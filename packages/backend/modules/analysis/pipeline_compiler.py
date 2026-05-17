from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modules.analysis.step_schemas import normalize_step_config


@dataclass(frozen=True, slots=True)
class CompiledStep:
    id: str
    type: str
    config: dict[str, object]
    depends_on: tuple[str, ...]
    is_applied: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "config": self.config,
            "depends_on": list(self.depends_on),
            "is_applied": self.is_applied,
        }


def compile_step(
    *,
    step_id: str,
    step_type: str,
    config: dict[str, Any],
    depends_on: list[str],
    is_applied: bool | None,
) -> CompiledStep:
    """Validate and canonicalize one UI/persisted step into executable pipeline form."""
    if not step_id.strip():
        raise ValueError("Pipeline step id is required")
    canonical_config = normalize_step_config(step_type, config)
    return CompiledStep(
        id=step_id,
        type=step_type,
        config=canonical_config,
        depends_on=tuple(depends_on),
        is_applied=is_applied,
    )
