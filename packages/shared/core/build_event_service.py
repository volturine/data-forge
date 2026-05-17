from __future__ import annotations

import asyncio
from typing import Any

from sqlmodel import Session

from contracts.build_runs.live import BuildNotification, hub as build_hub
from contracts.compute import schemas as compute_schemas
from contracts.runtime import ipc as runtime_ipc
from core import build_runs_service as build_run_service


async def publish_build_notification(namespace: str, build_id: str, latest_sequence: int) -> None:
    await build_hub.publish(BuildNotification(namespace=namespace, build_id=build_id, latest_sequence=latest_sequence))
    await asyncio.to_thread(runtime_ipc.notify_api_build, namespace, build_id, latest_sequence)


async def persist_build_event(
    session: Session, *, namespace: str, build_id: str, event: compute_schemas.BuildEvent, resource_config_json: dict[str, Any] | None = None
) -> tuple[dict[str, Any], int] | None:
    event_row = build_run_service.append_build_event(session, build_id=build_id, event=event, resource_config_json=resource_config_json)
    if event_row is None:
        return None
    normalized = build_run_service.serialize_event_row(event_row)
    await publish_build_notification(namespace, build_id, latest_sequence=event_row.sequence)
    return normalized, event_row.sequence
