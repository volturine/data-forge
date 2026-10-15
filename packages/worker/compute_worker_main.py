from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

from runtime.environment import read_env


def _load_bootstrap_if_present() -> None:
    path = Path(
        read_env(
            "COMPUTE_WORKER_BOOTSTRAP_PATH",
            "/run/dataforge-secrets/compute-worker.json",
            legacy_names=("ENGINE_BOOTSTRAP_PATH",),
        )
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    if not isinstance(payload, dict):
        raise ValueError(f"Compute worker bootstrap document {path} must be a JSON object")
    for key, value in payload.items():
        if isinstance(value, str):
            os.environ[key] = value
    # The document lives on a container tmpfs; a read-only or root-owned mount
    # must not stop the engine from starting with the credentials it loaded.
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def main() -> None:
    _load_bootstrap_if_present()
    from runtime.compute_worker_server import main as run_compute_worker_server

    run_compute_worker_server()


if __name__ == "__main__":
    main()
