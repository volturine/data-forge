from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
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


def _preload_engine_server() -> Callable[[], None]:
    """Import the heavy Polars engine server while bootstrap is in flight.

    Docker image layers are already local; the remaining cold-start cost is
    Python importing Polars/Arrow. Overlap that with credential bootstrap so
    container start is not fully serial.
    """
    from runtime.engine_server import main as run_engine_server

    return run_engine_server


def main() -> None:
    preloaded: dict[str, Callable[[], None] | BaseException] = {}

    def preload() -> None:
        try:
            preloaded["main"] = _preload_engine_server()
        except BaseException as exc:  # noqa: BLE001 - surface import failures on the main thread
            preloaded["error"] = exc

    thread = threading.Thread(target=preload, name="engine-preload", daemon=True)
    thread.start()
    _load_bootstrap()
    thread.join()
    error = preloaded.get("error")
    if isinstance(error, BaseException):
        raise error
    run_engine_server = preloaded.get("main")
    if not callable(run_engine_server):
        raise RuntimeError("Engine server failed to preload")
    run_engine_server()


if __name__ == "__main__":
    main()
