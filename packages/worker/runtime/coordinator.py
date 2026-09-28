"""Load the worker coordinator from its standalone entrypoint.

The combined runtime image runs from the backend directory, whose ``main.py``
is the HTTP entrypoint. Importing by module name would therefore select the
wrong application. Load the worker entrypoint by its package path instead;
there is still one implementation and the standalone worker command remains
available for local development and integration tests.
"""

import importlib.util
import sys
from pathlib import Path

_WORKER_ENTRYPOINT = Path(__file__).resolve().parents[1] / "main.py"
_ENTRYPOINT_SPEC = importlib.util.spec_from_file_location("dataforge_worker_entrypoint", _WORKER_ENTRYPOINT)
if _ENTRYPOINT_SPEC is None or _ENTRYPOINT_SPEC.loader is None:
    raise ImportError(f"Unable to load worker coordinator from {_WORKER_ENTRYPOINT}")
_ENTRYPOINT_MODULE = importlib.util.module_from_spec(_ENTRYPOINT_SPEC)
sys.modules[_ENTRYPOINT_SPEC.name] = _ENTRYPOINT_MODULE
_ENTRYPOINT_SPEC.loader.exec_module(_ENTRYPOINT_MODULE)

run_runtime_coordinator = _ENTRYPOINT_MODULE.run_runtime_coordinator

__all__ = ["run_runtime_coordinator"]
