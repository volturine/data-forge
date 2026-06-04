from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchedulerSettings:
    internal_api_base_url: str
    internal_api_token: str
    scheduler_check_interval: int
    log_level: str

    @classmethod
    def from_env(cls) -> SchedulerSettings:
        return cls(
            internal_api_base_url=_required_env("INTERNAL_API_BASE_URL").rstrip("/"),
            internal_api_token=_required_env("INTERNAL_API_TOKEN"),
            scheduler_check_interval=_required_positive_int_env("SCHEDULER_CHECK_INTERVAL"),
            log_level=os.environ.get("LOG_LEVEL", "info").lower(),
        )


class SchedulerApiClient:
    def __init__(self, *, base_url: str, token: str, timeout_seconds: float = 30.0, registration_retry_seconds: float = 90.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._registration_retry_seconds = registration_retry_seconds

    def register(self, *, worker_id: str, hostname: str, pid: int, capacity: int) -> None:
        self._post_registration(
            "/scheduler/register",
            {
                "worker_id": worker_id,
                "hostname": hostname,
                "pid": pid,
                "capacity": capacity,
            },
        )

    def heartbeat(self, *, worker_id: str) -> None:
        self._post("/scheduler/heartbeat", {"worker_id": worker_id})

    def stop(self, *, worker_id: str) -> None:
        self._post("/scheduler/stop", {"worker_id": worker_id})

    def run_due(self, *, worker_id: str) -> dict[str, Any]:
        return self._post("/scheduler/run-due", {"worker_id": worker_id})

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self._base_url}{path}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Internal-Token": self._token,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Backend scheduler RPC failed with HTTP {exc.code}: {detail}") from exc
        if not raw:
            return {}
        decoded = json.loads(raw.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise RuntimeError(f"Backend scheduler RPC returned non-object JSON: {decoded!r}")
        return decoded

    def _post_registration(self, path: str, payload: dict[str, object]) -> dict[str, Any]:
        deadline = time.monotonic() + self._registration_retry_seconds
        while True:
            try:
                return self._post(path, payload)
            except URLError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1.0)


async def scheduler_loop(
    stop_event: asyncio.Event,
    worker_id: str,
    *,
    client: SchedulerApiClient,
    check_interval_seconds: int,
    heartbeat_seconds: float = 5.0,
) -> None:
    await asyncio.to_thread(
        client.register,
        worker_id=worker_id,
        hostname=socket.gethostname(),
        pid=os.getpid(),
        capacity=1,
    )
    heartbeat_stop = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop_sync,
        kwargs={
            "client": client,
            "stop_signal": heartbeat_stop,
            "worker_id": worker_id,
            "heartbeat_seconds": heartbeat_seconds,
        },
        daemon=True,
    )
    heartbeat_thread.start()
    try:
        while not stop_event.is_set():
            result = await asyncio.to_thread(client.run_due, worker_id=worker_id)
            if _response_handled_work(result):
                _log_run_due_result(result)
                continue
            await _sleep_until_tick_or_stop(stop_event, check_interval_seconds)
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join()
        await asyncio.to_thread(client.stop, worker_id=worker_id)


def _response_handled_work(result: dict[str, Any]) -> bool:
    handled = result.get("handled")
    if isinstance(handled, bool):
        return handled
    raise RuntimeError(f"Backend scheduler RPC response is missing boolean handled: {result!r}")


def _log_run_due_result(result: dict[str, Any]) -> None:
    for item in _list_response_items(result, "enqueued"):
        logger.info(
            "Scheduler: enqueued schedule %s as build %s (namespace=%s datasource=%s)",
            item.get("schedule_id"),
            item.get("build_id"),
            item.get("namespace"),
            item.get("datasource_id"),
        )
    for item in _list_response_items(result, "failures"):
        logger.error(
            "Scheduler: enqueue failed for schedule %s (namespace=%s datasource=%s): %s",
            item.get("schedule_id"),
            item.get("namespace"),
            item.get("datasource_id"),
            item.get("error"),
        )


def _list_response_items(result: dict[str, Any], key: str) -> list[dict[str, Any]]:
    raw_items = result.get(key, [])
    if not isinstance(raw_items, list):
        raise RuntimeError(f"Backend scheduler RPC response has invalid {key}: {result!r}")
    items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise RuntimeError(f"Backend scheduler RPC response has invalid {key} item: {raw_item!r}")
        items.append(raw_item)
    return items


async def _sleep_until_tick_or_stop(stop_event: asyncio.Event, seconds: int) -> None:
    sleep_task = asyncio.create_task(asyncio.sleep(seconds))
    stop_task = asyncio.create_task(stop_event.wait())
    done, pending = await asyncio.wait({sleep_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        with contextlib.suppress(asyncio.CancelledError):
            await task


def _heartbeat_loop_sync(*, client: SchedulerApiClient, stop_signal: threading.Event, worker_id: str, heartbeat_seconds: float) -> None:
    while not stop_signal.wait(heartbeat_seconds):
        try:
            client.heartbeat(worker_id=worker_id)
        except Exception:
            logger.exception("Scheduler heartbeat failed")


def scheduler_id() -> str:
    return f"scheduler:{uuid.uuid4()}"


def install_stop_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def _stop() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _stop)


async def main() -> None:
    settings = SchedulerSettings.from_env()
    logging.basicConfig(level=settings.log_level.upper())
    logger.info("Starting scheduler process...")
    stop_event = asyncio.Event()
    install_stop_handlers(stop_event)
    client = SchedulerApiClient(base_url=settings.internal_api_base_url, token=settings.internal_api_token)
    await scheduler_loop(
        stop_event,
        scheduler_id(),
        client=client,
        check_interval_seconds=settings.scheduler_check_interval,
    )


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} must be configured for the scheduler runtime")
    return value.strip()


def _required_positive_int_env(name: str) -> int:
    raw_value = _required_env(name)
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw_value!r}") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be at least 1, got {value}")
    return value


if __name__ == "__main__":
    asyncio.run(main())
