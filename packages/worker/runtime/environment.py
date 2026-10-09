"""Read runtime environment variables with one-release rename aliases."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def read_env(name: str, default: str = "", *, legacy_names: tuple[str, ...] = ()) -> str:
    value = os.environ.get(name)
    if value is not None and value.strip():
        return value

    for legacy_name in legacy_names:
        legacy_value = os.environ.get(legacy_name)
        if legacy_value is None or not legacy_value.strip():
            continue
        logger.warning(
            "Deprecated environment variable %s is in use; use %s instead. The compatibility alias will be removed after this release.",
            legacy_name,
            name,
        )
        return legacy_value
    return default


def read_int(
    name: str,
    default: int,
    *,
    legacy_names: tuple[str, ...] = (),
    min_value: int | None = None,
    max_value: int | None = None,
) -> int:
    raw = read_env(name, str(default), legacy_names=legacy_names)
    value = int(raw)
    if min_value is not None and value < min_value:
        raise RuntimeError(f"{name} must be at least {min_value}, got {value}")
    if max_value is not None and value > max_value:
        raise RuntimeError(f"{name} must be at most {max_value}, got {value}")
    return value
