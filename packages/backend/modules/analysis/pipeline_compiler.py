from __future__ import annotations

from typing import Any

from modules.analysis.step_schemas import normalize_step_config


def compile_step(
    *,
    step_id: str,
    step_type: str,
    config: dict[str, Any],
) -> dict[str, object]:
    """Validate a step ID and return its canonical config."""
    if not step_id.strip():
        raise ValueError('Pipeline step id is required')
    return normalize_step_config(step_type, config)
