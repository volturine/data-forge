from __future__ import annotations

import socket
from datetime import UTC, timedelta

from backend_core import runtime_workers_service as runtime_worker_service
from backend_core.database import run_settings_db
from backend_core.domain.runtime_workers.models import RuntimeWorkerKind
from backend_core.time import utc_now


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
    age = utc_now() - row.last_heartbeat_at.replace(tzinfo=UTC)
    return age <= timedelta(seconds=heartbeat_seconds)
