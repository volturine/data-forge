"""Read runtime environment variables, treating blank values as unset."""

from __future__ import annotations

import os


def read_env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value if value is not None and value.strip() else default


def read_int(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    value = int(read_env(name, str(default)))
    if min_value is not None and value < min_value:
        raise RuntimeError(f"{name} must be at least {min_value}, got {value}")
    if max_value is not None and value > max_value:
        raise RuntimeError(f"{name} must be at most {max_value}, got {value}")
    return value
