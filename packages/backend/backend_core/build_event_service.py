from __future__ import annotations

import logging
import time
from typing import Any

from sqlmodel import Session

from backend_core import build_runs_service as build_run_service
from backend_core.domain.build_runs.live import BuildNotification, hub as build_hub
from backend_core.domain.compute import schemas as compute_schemas

logger = logging.getLogger(__name__)
_SLOW_EVENT_SERIALIZATION_SECONDS = 0.1


async def publish_build_notification(namespace: str, build_id: str, latest_sequence: int) -> None:
    await build_hub.publish(BuildNotification(namespace=namespace, build_id=build_id, latest_sequence=latest_sequence))


def persist_build_event(
    session: Session,
    *,
    build_id: str,
    execution_generation: int,
    event: compute_schemas.BuildEvent,
    resource_config_json: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int] | None:
    event_row = build_run_service.append_build_event(
        session,
        build_id=build_id,
        event=event,
        resource_config_json=resource_config_json,
        expected_execution_generation=execution_generation,
    )
    appended = time.perf_counter()
    if event_row is None:
        return None
    normalized = build_run_service.serialize_event_row(event_row)
    serialized = time.perf_counter()
    if serialized - appended >= _SLOW_EVENT_SERIALIZATION_SECONDS:
        logger.warning(
            'Slow build event response serialization build_id=%s event_type=%s serialize_ms=%.1f',
            build_id,
            event.type,
            (serialized - appended) * 1000,
        )
    return normalized, event_row.sequence
