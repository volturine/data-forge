from __future__ import annotations

import logging
import os


def configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "info").strip().upper() or "INFO"
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        raise RuntimeError(f"LOG_LEVEL must be a valid Python logging level, got {level_name!r}")
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
