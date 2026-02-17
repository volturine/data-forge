from __future__ import annotations


def normalize_step_timings(values: dict | None) -> dict[str, float]:
    if not values:
        return {}
    normalized: dict[str, float] = {}
    for key, value in values.items():
        try:
            normalized[str(key)] = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return normalized
