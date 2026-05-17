from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta

from contracts.runtime_workers.models import RuntimeWorkerKind
from core import runtime_workers_service as runtime_worker_service
from core.database import run_settings_db


def _now() -> datetime:
    return datetime.now(UTC)


def worker_healthy(*, kind: RuntimeWorkerKind, heartbeat_seconds: float = 15.0, hostname: str | None = None) -> bool:
    host = hostname or socket.gethostname()

    def _read(session):
        rows = runtime_worker_service.list_workers(session, kind=kind)
        for row in reversed(rows):
            if row.hostname != host:
                continue
            if row.stopped_at is not None:
                continue
            return row
        return None

    row = run_settings_db(_read)
    if row is None:
        return False
    age = _now() - row.last_heartbeat_at.replace(tzinfo=UTC)
    return age <= timedelta(seconds=heartbeat_seconds)
