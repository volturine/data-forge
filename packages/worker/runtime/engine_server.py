from __future__ import annotations

import logging
import json
import os
import tempfile
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import grpc
import requests
from google.protobuf.timestamp_pb2 import Timestamp

from dataforge_protocol import engine_runtime_pb2, engine_runtime_pb2_grpc
from runtime.compute_engine import PolarsComputeEngine
from runtime.domain.compute.base import EngineResult
from runtime.export_formats import get_export_format
from runtime.json_values import dict_to_struct, encode_json_bytes

logger = logging.getLogger(__name__)

ENGINE_PROTOCOL_VERSION = 2
_TOKEN_METADATA_KEY = "x-engine-token"
_MAX_RETAINED_COMPLETED_JOBS = 8
_MAX_TOTAL_JOBS = 100
_MAX_PROGRESS_EVENTS = 256


@dataclass(slots=True)
class _JobState:
    job_id: str
    events: deque[tuple[int, dict[str, object]]] = field(default_factory=lambda: deque(maxlen=_MAX_PROGRESS_EVENTS))
    next_sequence: int = 1
    result: EngineResult | None = None
    done: bool = False
    condition: threading.Condition = field(default_factory=threading.Condition)

    def emit_progress(self, event: dict[str, object]) -> None:
        with self.condition:
            self.events.append((self.next_sequence, {"emitted_at": datetime.now(UTC).isoformat(), **event}))
            self.next_sequence += 1
            self.condition.notify_all()

    def complete(self, result: EngineResult) -> None:
        with self.condition:
            self.result = result
            self.done = True
            self.condition.notify_all()


class _EngineJobs:
    def __init__(self) -> None:
        self._jobs: OrderedDict[str, _JobState] = OrderedDict()
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="polars-engine-job")
        self._accepting = True

    def submit(self, *, job_id: str, kind: str, payload: dict[str, object]) -> _JobState:
        with self._lock:
            if not self._accepting:
                raise RuntimeError("Engine is shutting down")
            if job_id in self._jobs:
                return self._jobs[job_id]
            self._evict_completed_locked()
            if len(self._jobs) >= _MAX_TOTAL_JOBS:
                raise RuntimeError("Engine job queue limit reached")
            state = _JobState(job_id=job_id)
            self._jobs[job_id] = state
            self._executor.submit(self._run, state, kind, payload)
            return state

    def _evict_completed_locked(self) -> None:
        completed_ids = [job_id for job_id, state in self._jobs.items() if state.done]
        for job_id in completed_ids[:-_MAX_RETAINED_COMPLETED_JOBS]:
            del self._jobs[job_id]

    def get(self, job_id: str) -> _JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def pop_completed(self, job_id: str) -> _JobState | None:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None or not state.done:
                return state
            return self._jobs.pop(job_id)

    def shutdown(self) -> None:
        with self._lock:
            self._accepting = False
        self._executor.shutdown(wait=False, cancel_futures=False)

    def _run(self, state: _JobState, kind: str, payload: dict[str, object]) -> None:
        try:
            result = _execute_job(job_id=state.job_id, kind=kind, payload=payload, progress_callback=state.emit_progress)
        except Exception as exc:
            error_kind, error_details = PolarsComputeEngine._classify_engine_error(exc)
            logger.exception("Engine job %s failed", state.job_id)
            result = EngineResult(
                job_id=state.job_id,
                data=None,
                error=str(exc),
                error_kind=error_kind,
                error_details=error_details,
            )
        state.complete(result)
        with self._lock:
            self._evict_completed_locked()


def _required_mapping(payload: dict[str, object], field_name: str) -> dict[str, object]:
    value = payload.get(field_name)
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} is required")
    return value


def _optional_mapping(payload: dict[str, object], field_name: str) -> dict[str, dict[str, object]]:
    value = payload.get(field_name, {})
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return {str(key): item for key, item in value.items() if isinstance(item, dict)}


def _required_steps(payload: dict[str, object]) -> list[dict[str, object]]:
    value = payload.get("steps")
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("steps must be an array of objects")
    return value


def _execute_job(
    *,
    job_id: str,
    kind: str,
    payload: dict[str, object],
    progress_callback: Callable[[dict[str, object]], None],
) -> EngineResult:
    datasource_config = _required_mapping(payload, "datasource_config")
    steps = _required_steps(payload)
    additional_datasources = _optional_mapping(payload, "additional_datasources")
    result_data: dict[str, object]

    if kind == "preview":
        row_limit = payload.get("row_limit", 1000)
        offset = payload.get("offset", 0)
        if not isinstance(row_limit, int) or not isinstance(offset, int):
            raise ValueError("row_limit and offset must be integers")
        result_data = PolarsComputeEngine.execute_preview(datasource_config, steps, row_limit, offset, job_id, additional_datasources, progress_callback)
    elif kind == "export":
        artifact_url = payload.get("artifact_url")
        artifact_upload_url = payload.get("artifact_upload_url")
        export_format = payload.get("export_format", "csv")
        if not isinstance(artifact_url, str) or not artifact_url.startswith("s3://"):
            raise ValueError("artifact_url must be an s3:// URL")
        if not isinstance(artifact_upload_url, str) or not artifact_upload_url.startswith(("http://", "https://")):
            raise ValueError("artifact_upload_url must be an HTTP(S) URL")
        if not isinstance(export_format, str) or not export_format:
            raise ValueError("export_format is required")
        export = get_export_format(export_format)
        descriptor, output_path = tempfile.mkstemp(suffix=export.extension)
        os.close(descriptor)
        try:
            result_data = PolarsComputeEngine.execute_export(
                datasource_config, steps, output_path, export_format, job_id, additional_datasources, progress_callback
            )
            with Path(output_path).open("rb") as artifact:
                response = requests.put(
                    artifact_upload_url,
                    data=artifact,
                    headers={"Content-Type": export.content_type},
                    timeout=(10, 600),
                )
            response.raise_for_status()
            result_data["output_path"] = artifact_url
        finally:
            Path(output_path).unlink(missing_ok=True)
    elif kind == "schema":
        result_data = PolarsComputeEngine.execute_schema(datasource_config, steps, job_id, additional_datasources, progress_callback)
    elif kind == "row_count":
        result_data = PolarsComputeEngine.execute_row_count(datasource_config, steps, job_id, additional_datasources, progress_callback)
    else:
        raise ValueError(f"Unsupported engine job kind: {kind}")

    step_timings = result_data.pop("step_timings", {})
    query_plan = result_data.pop("query_plan", None)
    raw_read = result_data.pop("read_duration_ms", None)
    raw_write = result_data.pop("write_duration_ms", None)
    raw_collect = result_data.pop("collect_duration_ms", None)
    return EngineResult(
        job_id=job_id,
        data=result_data,
        error=None,
        step_timings=step_timings if isinstance(step_timings, dict) else {},
        query_plan=query_plan if isinstance(query_plan, str) else None,
        read_duration_ms=float(raw_read) if isinstance(raw_read, int | float) else None,
        write_duration_ms=float(raw_write) if isinstance(raw_write, int | float) else None,
        collect_duration_ms=float(raw_collect) if isinstance(raw_collect, int | float) else None,
    )


def _result_message(result: EngineResult) -> engine_runtime_pb2.EngineJobResult:
    message = engine_runtime_pb2.EngineJobResult(job_id=result.job_id or "unknown", step_timings=dict_to_struct(result.step_timings))
    if result.data is not None:
        message.data_json = encode_json_bytes(result.data)
    if result.error is not None:
        message.error = result.error
    if result.error_kind is not None:
        message.error_kind = result.error_kind
    if result.error_details is not None:
        message.error_details_json = encode_json_bytes(result.error_details)
    if result.query_plan is not None:
        message.query_plan = result.query_plan
    if result.read_duration_ms is not None:
        message.read_duration_ms = result.read_duration_ms
    if result.write_duration_ms is not None:
        message.write_duration_ms = result.write_duration_ms
    if result.collect_duration_ms is not None:
        message.collect_duration_ms = result.collect_duration_ms
    return message


def _timestamp(value: datetime) -> Timestamp:
    message = Timestamp()
    message.FromDatetime(value)
    return message


class PolarsEngineServicer(engine_runtime_pb2_grpc.PolarsEngineServiceServicer):
    def __init__(
        self,
        *,
        engine_identity: str,
        application_version: str,
        token: str,
        on_shutdown: Callable[[], None],
        heartbeat_timeout_seconds: int = 15,
    ) -> None:
        self._engine_identity = engine_identity
        self._application_version = application_version
        self._token = token
        self._on_shutdown = on_shutdown
        self._jobs = _EngineJobs()
        self._shutdown = threading.Event()
        self._last_heartbeat = time.monotonic()
        self._heartbeat_timeout_seconds = heartbeat_timeout_seconds
        threading.Thread(target=self._watch_heartbeat, name="engine-heartbeat-watchdog", daemon=True).start()

    def _watch_heartbeat(self) -> None:
        while not self._shutdown.wait(max(1.0, self._heartbeat_timeout_seconds / 3)):
            if time.monotonic() - self._last_heartbeat <= self._heartbeat_timeout_seconds:
                continue
            logger.error("Worker heartbeat expired; stopping orphaned engine %s", self._engine_identity)
            self._shutdown.set()
            self._jobs.shutdown()
            self._on_shutdown()
            return

    def _require_token(self, context: grpc.ServicerContext) -> bool:
        if not self._token:
            return True
        metadata = dict(context.invocation_metadata())
        if metadata.get(_TOKEN_METADATA_KEY) == self._token:
            return True
        context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid engine token")
        return False

    def Health(self, request: engine_runtime_pb2.EngineHealthRequest, context: grpc.ServicerContext) -> engine_runtime_pb2.EngineHealthResponse:
        self._require_token(context)
        self._last_heartbeat = time.monotonic()
        return engine_runtime_pb2.EngineHealthResponse(
            engine_identity=self._engine_identity,
            protocol_version=ENGINE_PROTOCOL_VERSION,
            application_version=self._application_version,
            ready=not self._shutdown.is_set(),
        )

    def SubmitJob(self, request: engine_runtime_pb2.EngineSubmitJobRequest, context: grpc.ServicerContext) -> engine_runtime_pb2.EngineJobReference:
        self._require_token(context)
        if request.protocol_version != ENGINE_PROTOCOL_VERSION:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, "Engine protocol version mismatch")
        try:
            payload = json.loads(request.payload_json)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"Invalid job payload JSON: {exc}")
        if not isinstance(payload, dict):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Job payload JSON must be an object")
        try:
            self._jobs.submit(job_id=request.job_id, kind=request.kind, payload=payload)
        except RuntimeError as exc:
            context.abort(grpc.StatusCode.UNAVAILABLE, str(exc))
        return engine_runtime_pb2.EngineJobReference(job_id=request.job_id)

    def WatchJob(self, request: engine_runtime_pb2.EngineWatchJobRequest, context: grpc.ServicerContext) -> Iterator[engine_runtime_pb2.EngineJobEvent]:
        self._require_token(context)
        state = self._jobs.get(request.job_id)
        if state is None:
            context.abort(grpc.StatusCode.NOT_FOUND, "Engine job was not found")
        sequence = request.after_sequence
        assert state is not None
        while context.is_active():
            with state.condition:
                while state.next_sequence <= sequence + 1 and not state.done and context.is_active():
                    state.condition.wait(timeout=0.25)
                if state.events and sequence < state.events[0][0] - 1:
                    context.abort(grpc.StatusCode.OUT_OF_RANGE, "Requested progress events have been evicted")
                for event_sequence, raw_event in tuple(state.events):
                    if event_sequence <= sequence:
                        continue
                    event = dict(raw_event)
                    sequence = event_sequence
                    emitted_at = datetime.fromisoformat(str(event.pop("emitted_at")).replace("Z", "+00:00"))
                    yield engine_runtime_pb2.EngineJobEvent(
                        job_id=request.job_id,
                        sequence=event_sequence,
                        emitted_at=_timestamp(emitted_at),
                        progress_json=encode_json_bytes(event),
                    )
                if state.done:
                    if state.result is not None:
                        yield engine_runtime_pb2.EngineJobEvent(
                            job_id=request.job_id,
                            sequence=sequence + 1,
                            emitted_at=_timestamp(datetime.now(UTC)),
                            result=_result_message(state.result),
                        )
                    return

    def GetJobResult(self, request: engine_runtime_pb2.EngineGetJobResultRequest, context: grpc.ServicerContext) -> engine_runtime_pb2.EngineJobResult:
        self._require_token(context)
        state = self._jobs.pop_completed(request.job_id)
        if state is None:
            context.abort(grpc.StatusCode.NOT_FOUND, "Engine job was not found")
        assert state is not None
        with state.condition:
            if not state.done or state.result is None:
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, "Engine job has not completed")
            return _result_message(state.result)

    def Shutdown(self, request: engine_runtime_pb2.EngineShutdownRequest, context: grpc.ServicerContext) -> engine_runtime_pb2.EngineShutdownResponse:
        self._require_token(context)
        self._shutdown.set()
        self._jobs.shutdown()
        self._on_shutdown()
        return engine_runtime_pb2.EngineShutdownResponse(accepted=True)


def run_engine_server(*, host: str, port: int, engine_identity: str, application_version: str, token: str, heartbeat_timeout_seconds: int = 15) -> None:
    server = grpc.server(
        ThreadPoolExecutor(max_workers=8), options=(("grpc.max_send_message_length", 128 * 1024 * 1024), ("grpc.max_receive_message_length", 128 * 1024 * 1024))
    )

    def stop_server() -> None:
        threading.Thread(target=lambda: server.stop(grace=1), name="polars-engine-stop", daemon=True).start()

    engine_runtime_pb2_grpc.add_PolarsEngineServiceServicer_to_server(
        PolarsEngineServicer(
            engine_identity=engine_identity,
            application_version=application_version,
            token=token,
            on_shutdown=stop_server,
            heartbeat_timeout_seconds=heartbeat_timeout_seconds,
        ),
        server,
    )
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    logger.info("Polars engine server listening on %s:%s for %s", host, port, engine_identity)
    try:
        server.wait_for_termination()
    finally:
        server.stop(grace=1)


def main() -> None:
    run_engine_server(
        host=os.environ.get("ENGINE_RPC_HOST", "0.0.0.0"),
        port=int(os.environ.get("ENGINE_RPC_PORT", "50053")),
        engine_identity=os.environ.get("ENGINE_IDENTITY", "unknown"),
        application_version=os.environ.get("APP_VERSION", "unknown"),
        token=os.environ.get("ENGINE_RPC_TOKEN", ""),
        heartbeat_timeout_seconds=int(os.environ.get("ENGINE_HEARTBEAT_TIMEOUT_SECONDS", "15")),
    )


if __name__ == "__main__":
    main()
