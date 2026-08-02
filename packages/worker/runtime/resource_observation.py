import asyncio
import contextlib
import logging

from builds.build_live import ActiveBuild
from runtime.build_events import BuildEmitter, build_event, emit_build_event
from runtime.compute_monitor import monitor_engine_resources
from runtime.domain.compute.base import ComputeEngine
from runtime.internal_api import BuildJobLeaseLost

logger = logging.getLogger(__name__)


def resource_summary(engine: ComputeEngine) -> dict[str, int | None]:
    # Runtime engines expose effective_resources after their process handshake.
    effective = engine.effective_resources if getattr(engine, "effective_resources", None) else {}
    return {
        key: int(value) if isinstance(value, int) else None
        for key, value in {
            "max_threads": effective.get("max_threads"),
            "max_memory_mb": effective.get("max_memory_mb"),
            "streaming_chunk_size": effective.get("streaming_chunk_size"),
        }.items()
    }


async def stream_resource_events(
    *,
    build: ActiveBuild,
    analysis_id: str,
    engine: ComputeEngine,
    emitter: BuildEmitter | None,
    tab_id: str | None,
    tab_name: str | None,
) -> None:
    async for resource in monitor_engine_resources(engine):
        await emit_build_event(
            emitter,
            event=build_event(
                build,
                analysis_id,
                {"type": "resources", "tab_id": tab_id, "tab_name": tab_name, **resource},
            ),
        )


def observe_stream_task(task: asyncio.Task[object]) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None and not isinstance(error, BuildJobLeaseLost):
        logger.error("Build event stream stopped after its owner exited", exc_info=(type(error), error, error.__traceback__))


async def stop_stream_task(task: asyncio.Task[object] | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
