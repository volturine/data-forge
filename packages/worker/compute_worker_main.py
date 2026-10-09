from __future__ import annotations

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
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            for key, value in payload.items():
                if isinstance(key, str) and isinstance(value, str):
                    os.environ[key] = value
        path.unlink(missing_ok=True)
    except Exception:
        pass


def main() -> None:
    _load_bootstrap_if_present()
    from runtime.compute_worker_server import main as run_compute_worker_server

    run_compute_worker_server()


if __name__ == "__main__":
    main()
