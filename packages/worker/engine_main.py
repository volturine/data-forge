from __future__ import annotations

import json
import os
import time
from pathlib import Path


def _load_bootstrap() -> None:
    path = Path(os.environ.get("ENGINE_BOOTSTRAP_PATH", "/run/dataforge-secrets/engine.json"))
    deadline = time.monotonic() + float(os.environ.get("ENGINE_BOOTSTRAP_TIMEOUT_SECONDS", "30"))
    while not path.exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("Engine credential bootstrap did not arrive before its deadline")
        time.sleep(0.05)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Engine credential bootstrap must be an object")
    for key, value in payload.items():
        if isinstance(key, str) and isinstance(value, str):
            os.environ[key] = value
    path.unlink(missing_ok=True)


def main() -> None:
    _load_bootstrap()
    from runtime.engine_server import main as run_engine_server

    run_engine_server()


if __name__ == "__main__":
    main()
