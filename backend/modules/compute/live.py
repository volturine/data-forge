from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import WebSocket

from modules.compute import schemas

logger = logging.getLogger(__name__)

_MAX_LOGS = 200
_MAX_RESOURCES = 60
_MAX_EVENTS = 500
_MAX_FINISHED_BUILDS = 100
_FINISHED_BUILD_TTL_SECONDS = 900
_LOG_MESSAGE_MAX = 4000
_EVENT_INTERVAL_SECONDS = {
    schemas.BuildEventType.PROGRESS.value: 0.1,
    schemas.BuildEventType.RESOURCES.value: 0.5,
    schemas.BuildEventType.LOG.value: 0.05,
}
_ANSI_RE = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
_CONTROL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _safe_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _safe_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _safe_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _sanitize_log_message(value: object) -> str:
    if not isinstance(value, str):
        return ''
    text = _ANSI_RE.sub('', value)
    text = _CONTROL_RE.sub('', text)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = '\n'.join(line.rstrip() for line in text.split('\n'))
    text = text.strip()
    if len(text) <= _LOG_MESSAGE_MAX:
        return text
    return text[: _LOG_MESSAGE_MAX - 1] + '…'


def _normalize_payload(payload: dict) -> dict:
    normalized = dict(payload)
    event_type = _safe_str(normalized.get('type'))
    if event_type == schemas.BuildEventType.LOG.value:
        normalized['message'] = _sanitize_log_message(normalized.get('message'))
    return normalized


def _should_throttle(build: ActiveBuild, payload: dict) -> bool:
    event_type = _safe_str(payload.get('type'))
    if event_type is None:
        return False
    min_interval = _EVENT_INTERVAL_SECONDS.get(event_type)
    if min_interval is None:
        return False
    now = time.monotonic()
    last = build.last_event_sent_at.get(event_type)
    if last is None or now - last >= min_interval:
        build.last_event_sent_at[event_type] = now
        return False
    build.last_throttled_event[event_type] = payload
    return True


def _consume_throttled(build: ActiveBuild, payload: dict) -> list[dict]:
    event_type = _safe_str(payload.get('type'))
    if event_type is None:
        return []
    if event_type in {schemas.BuildEventType.COMPLETE.value, schemas.BuildEventType.FAILED.value}:
        queued = list(build.last_throttled_event.values())
        build.last_throttled_event.clear()
        return queued
    delayed = build.last_throttled_event.pop(event_type, None)
    if delayed is None:
        return []
    build.last_event_sent_at[event_type] = time.monotonic()
    return [delayed]


def _coerce_level(value: object) -> schemas.BuildLogLevel:
    if isinstance(value, schemas.BuildLogLevel):
        return value
    if isinstance(value, str):
        try:
            return schemas.BuildLogLevel(value)
        except ValueError:
            return schemas.BuildLogLevel.INFO
    return schemas.BuildLogLevel.INFO


def _coerce_status(value: object) -> schemas.ActiveBuildStatus:
    if isinstance(value, schemas.ActiveBuildStatus):
        return value
    if isinstance(value, str):
        try:
            return schemas.ActiveBuildStatus(value)
        except ValueError:
            return schemas.ActiveBuildStatus.RUNNING
    return schemas.ActiveBuildStatus.RUNNING


@dataclass(slots=True)
class ActiveBuild:
    build_id: str
    analysis_id: str
    analysis_name: str
    namespace: str
    starter: schemas.BuildStarter
    started_at: datetime
    total_steps: int = 0
    total_tabs: int = 0
    status: schemas.ActiveBuildStatus = schemas.ActiveBuildStatus.RUNNING
    progress: float = 0.0
    elapsed_ms: int = 0
    estimated_remaining_ms: int | None = None
    current_step: str | None = None
    current_step_index: int | None = None
    current_tab_id: str | None = None
    current_tab_name: str | None = None
    current_output_id: str | None = None
    current_output_name: str | None = None
    duration_ms: int | None = None
    error: str | None = None
    updated_at: datetime = field(default_factory=_utcnow)
    finished_at: datetime | None = None
    results: list[schemas.BuildTabResult] = field(default_factory=list)
    steps: dict[tuple[str | None, str], schemas.BuildStepSnapshot] = field(default_factory=dict)
    query_plans: list[schemas.BuildQueryPlanSnapshot] = field(default_factory=list)
    resources: deque[schemas.BuildResourceSnapshot] = field(default_factory=lambda: deque(maxlen=_MAX_RESOURCES))
    logs: deque[schemas.BuildLogEntry] = field(default_factory=lambda: deque(maxlen=_MAX_LOGS))
    events: deque[dict] = field(default_factory=lambda: deque(maxlen=_MAX_EVENTS))
    perf_started_at: float = field(default_factory=time.perf_counter)
    last_emitted_at: float = field(default_factory=time.monotonic)
    resource_config: schemas.BuildResourceConfigSummary | None = None
    last_event_sent_at: dict[str, float] = field(default_factory=dict)
    last_throttled_event: dict[str, dict] = field(default_factory=dict)

    def add_event(self, payload: dict) -> None:
        self.updated_at = _utcnow()
        self.events.append(payload)
        self.last_emitted_at = time.monotonic()

    def update_progress(
        self,
        progress: float,
        elapsed_ms: int,
        estimated_remaining_ms: int | None,
        current_step: str | None,
        current_step_index: int | None,
        total_steps: int,
    ) -> None:
        self.updated_at = _utcnow()
        self.progress = progress
        self.elapsed_ms = elapsed_ms
        self.estimated_remaining_ms = estimated_remaining_ms
        self.current_step = current_step
        self.current_step_index = current_step_index
        self.total_steps = total_steps
        if self.duration_ms is None and self.status == schemas.ActiveBuildStatus.RUNNING:
            self.duration_ms = elapsed_ms

    def update_status(self, status: schemas.ActiveBuildStatus, duration_ms: int, error: str | None = None) -> None:
        now = _utcnow()
        self.status = status
        self.duration_ms = duration_ms
        self.elapsed_ms = duration_ms
        self.error = error
        self.updated_at = now
        self.finished_at = now

    def upsert_step(self, step: schemas.BuildStepSnapshot) -> None:
        self.updated_at = _utcnow()
        self.steps[(step.tab_id, step.step_id)] = step

    def add_query_plan(self, plan: schemas.BuildQueryPlanSnapshot) -> None:
        self.updated_at = _utcnow()
        self.query_plans = [item for item in self.query_plans if not (item.tab_id == plan.tab_id and item.tab_name == plan.tab_name)]
        self.query_plans.append(plan)

    def add_resource(self, item: schemas.BuildResourceSnapshot) -> None:
        self.updated_at = _utcnow()
        self.resources.append(item)

    def add_log(self, item: schemas.BuildLogEntry) -> None:
        self.updated_at = _utcnow()
        self.logs.append(item)

    def summary(self) -> schemas.ActiveBuildSummary:
        return schemas.ActiveBuildSummary(
            build_id=self.build_id,
            analysis_id=self.analysis_id,
            analysis_name=self.analysis_name,
            namespace=self.namespace,
            status=self.status,
            started_at=self.started_at,
            starter=self.starter,
            resource_config=self.resource_config,
            progress=self.progress,
            elapsed_ms=self.elapsed_ms,
            estimated_remaining_ms=self.estimated_remaining_ms,
            current_step=self.current_step,
            current_step_index=self.current_step_index,
            total_steps=self.total_steps,
            current_tab_id=self.current_tab_id,
            current_tab_name=self.current_tab_name,
            current_output_id=self.current_output_id,
            current_output_name=self.current_output_name,
            total_tabs=self.total_tabs,
        )

    def detail(self) -> schemas.ActiveBuildDetail:
        return schemas.ActiveBuildDetail(
            **self.summary().model_dump(),
            steps=sorted(self.steps.values(), key=lambda item: item.build_step_index),
            query_plans=self.query_plans,
            latest_resources=self.resources[-1] if self.resources else None,
            resources=list(self.resources),
            logs=list(self.logs),
            results=self.results,
            duration_ms=self.duration_ms,
            error=self.error,
        )


class ActiveBuildRegistry:
    def __init__(self) -> None:
        self._builds: dict[str, ActiveBuild] = {}
        self._watchers: dict[str, set[WebSocket]] = {}
        self._list_watchers: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def create_build(
        self, analysis_id: str, analysis_name: str, namespace: str, starter: schemas.BuildStarter, total_tabs: int = 0
    ) -> ActiveBuild:
        build = ActiveBuild(
            build_id=str(uuid.uuid4()),
            analysis_id=analysis_id,
            analysis_name=analysis_name,
            namespace=namespace,
            starter=starter,
            started_at=_utcnow(),
            total_tabs=total_tabs,
        )
        async with self._lock:
            self._prune_finished_locked()
            self._builds[build.build_id] = build
            self._watchers.setdefault(build.build_id, set())
        return build

    async def clear(self) -> None:
        async with self._lock:
            self._builds.clear()
            self._watchers.clear()
            self._list_watchers.clear()

    async def prune_finished(self) -> None:
        async with self._lock:
            self._prune_finished_locked()

    async def get_build(self, build_id: str) -> ActiveBuild | None:
        async with self._lock:
            return self._builds.get(build_id)

    async def list_builds(self, status: schemas.ActiveBuildStatus | None = None) -> list[schemas.ActiveBuildSummary]:
        async with self._lock:
            self._prune_finished_locked()
            builds = list(self._builds.values())
        if status is not None:
            builds = [build for build in builds if build.status == status]
        builds.sort(key=lambda item: item.started_at, reverse=True)
        return [build.summary() for build in builds]

    async def add_watcher(self, build_id: str, websocket: WebSocket) -> bool:
        async with self._lock:
            if build_id not in self._builds:
                return False
            self._watchers.setdefault(build_id, set()).add(websocket)
        return True

    async def remove_watcher(self, build_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            watchers = self._watchers.get(build_id)
            if not watchers:
                return
            watchers.discard(websocket)

    async def publish(self, build_id: str, payload: dict) -> None:
        async with self._lock:
            build = self._builds.get(build_id)
            if build is None:
                return
            normalized = _normalize_payload(payload)
            build.add_event(normalized)
            if _should_throttle(build, normalized):
                return
            queued = _consume_throttled(build, normalized)
            outbound = [*queued, normalized]
            sockets = list(self._watchers.get(build_id, set()))
            list_sockets = list(self._list_watchers.get(build.namespace, set()))
        stale: list[WebSocket] = []
        for message in outbound:
            for websocket in sockets:
                try:
                    await websocket.send_json(message)
                except Exception:
                    stale.append(websocket)
        stale_lists: list[WebSocket] = []
        for message in outbound:
            for websocket in list_sockets:
                try:
                    await websocket.send_json(message)
                except Exception:
                    stale_lists.append(websocket)
        if not stale and not stale_lists:
            return
        async with self._lock:
            watchers = self._watchers.get(build_id)
            if watchers:
                for websocket in stale:
                    watchers.discard(websocket)
            list_watchers = self._list_watchers.get(build.namespace)
            if list_watchers:
                for websocket in stale_lists:
                    list_watchers.discard(websocket)
            event_type = _safe_str(normalized.get('type'))
            if event_type in {schemas.BuildEventType.COMPLETE.value, schemas.BuildEventType.FAILED.value}:
                self._prune_finished_locked()

    async def add_list_watcher(self, namespace: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._list_watchers.setdefault(namespace, set()).add(websocket)

    async def remove_list_watcher(self, namespace: str, websocket: WebSocket) -> None:
        async with self._lock:
            watchers = self._list_watchers.get(namespace)
            if not watchers:
                return
            watchers.discard(websocket)

    async def apply_event(self, build_id: str, payload: dict) -> ActiveBuild | None:
        async with self._lock:
            build = self._builds.get(build_id)
            if build is None:
                return None
            normalized = _normalize_payload(payload)
            event_type = _safe_str(normalized.get('type'))
            build.current_tab_id = _safe_str(normalized.get('tab_id')) or build.current_tab_id
            build.current_tab_name = _safe_str(normalized.get('tab_name')) or build.current_tab_name
            build.current_output_id = _safe_str(normalized.get('current_output_id')) or build.current_output_id
            build.current_output_name = _safe_str(normalized.get('current_output_name')) or build.current_output_name
            if event_type == schemas.BuildEventType.PLAN.value:
                optimized = _safe_str(normalized.get('optimized_plan')) or ''
                unoptimized = _safe_str(normalized.get('unoptimized_plan')) or ''
                build.add_query_plan(
                    schemas.BuildQueryPlanSnapshot(
                        tab_id=_safe_str(normalized.get('tab_id')),
                        tab_name=_safe_str(normalized.get('tab_name')),
                        optimized_plan=optimized,
                        unoptimized_plan=unoptimized,
                    )
                )
            if event_type == schemas.BuildEventType.STEP_START.value:
                snapshot = schemas.BuildStepSnapshot(
                    build_step_index=_safe_int(normalized.get('build_step_index')) or 0,
                    step_index=_safe_int(normalized.get('step_index')) or 0,
                    step_id=_safe_str(normalized.get('step_id')) or 'unknown',
                    step_name=_safe_str(normalized.get('step_name')) or 'Unnamed step',
                    step_type=_safe_str(normalized.get('step_type')) or 'unknown',
                    tab_id=_safe_str(normalized.get('tab_id')),
                    tab_name=_safe_str(normalized.get('tab_name')),
                    state=schemas.BuildStepState.RUNNING,
                )
                build.upsert_step(snapshot)
            if event_type == schemas.BuildEventType.STEP_COMPLETE.value:
                snapshot = schemas.BuildStepSnapshot(
                    build_step_index=_safe_int(normalized.get('build_step_index')) or 0,
                    step_index=_safe_int(normalized.get('step_index')) or 0,
                    step_id=_safe_str(normalized.get('step_id')) or 'unknown',
                    step_name=_safe_str(normalized.get('step_name')) or 'Unnamed step',
                    step_type=_safe_str(normalized.get('step_type')) or 'unknown',
                    tab_id=_safe_str(normalized.get('tab_id')),
                    tab_name=_safe_str(normalized.get('tab_name')),
                    state=schemas.BuildStepState.COMPLETED,
                    duration_ms=_safe_int(normalized.get('duration_ms')),
                    row_count=_safe_int(normalized.get('row_count')),
                )
                build.upsert_step(snapshot)
            if event_type == schemas.BuildEventType.STEP_FAILED.value:
                snapshot = schemas.BuildStepSnapshot(
                    build_step_index=_safe_int(normalized.get('build_step_index')) or 0,
                    step_index=_safe_int(normalized.get('step_index')) or 0,
                    step_id=_safe_str(normalized.get('step_id')) or 'unknown',
                    step_name=_safe_str(normalized.get('step_name')) or 'Unnamed step',
                    step_type=_safe_str(normalized.get('step_type')) or 'unknown',
                    tab_id=_safe_str(normalized.get('tab_id')),
                    tab_name=_safe_str(normalized.get('tab_name')),
                    state=schemas.BuildStepState.FAILED,
                    error=_safe_str(normalized.get('error')),
                )
                build.upsert_step(snapshot)
            if event_type == schemas.BuildEventType.PROGRESS.value:
                build.update_progress(
                    progress=_safe_float(normalized.get('progress')),
                    elapsed_ms=_safe_int(normalized.get('elapsed_ms')) or build.elapsed_ms,
                    estimated_remaining_ms=_safe_int(normalized.get('estimated_remaining_ms')),
                    current_step=_safe_str(normalized.get('current_step')),
                    current_step_index=_safe_int(normalized.get('current_step_index')),
                    total_steps=_safe_int(normalized.get('total_steps')) or build.total_steps,
                )
            if event_type == schemas.BuildEventType.RESOURCES.value:
                build.add_resource(
                    schemas.BuildResourceSnapshot(
                        sampled_at=_utcnow(),
                        cpu_percent=_safe_float(normalized.get('cpu_percent')),
                        memory_mb=_safe_float(normalized.get('memory_mb')),
                        memory_limit_mb=_safe_float(normalized.get('memory_limit_mb'))
                        if normalized.get('memory_limit_mb') is not None
                        else None,
                        active_threads=_safe_int(normalized.get('active_threads')) or 0,
                        max_threads=_safe_int(normalized.get('max_threads')),
                    )
                )
            if event_type == schemas.BuildEventType.LOG.value:
                build.add_log(
                    schemas.BuildLogEntry(
                        timestamp=_utcnow(),
                        level=_coerce_level(normalized.get('level')),
                        message=_safe_str(normalized.get('message')) or '',
                        step_name=_safe_str(normalized.get('step_name')),
                        step_id=_safe_str(normalized.get('step_id')),
                        tab_id=_safe_str(normalized.get('tab_id')),
                        tab_name=_safe_str(normalized.get('tab_name')),
                    )
                )
            if event_type == schemas.BuildEventType.COMPLETE.value:
                build.results = [
                    schemas.BuildTabResult.model_validate(item) for item in normalized.get('results', []) if isinstance(item, dict)
                ]
                build.update_progress(
                    progress=1.0,
                    elapsed_ms=_safe_int(normalized.get('elapsed_ms')) or build.elapsed_ms,
                    estimated_remaining_ms=0,
                    current_step=build.current_step,
                    current_step_index=build.current_step_index,
                    total_steps=_safe_int(normalized.get('total_steps')) or build.total_steps,
                )
                build.update_status(
                    schemas.ActiveBuildStatus.COMPLETED,
                    duration_ms=_safe_int(normalized.get('duration_ms')) or build.elapsed_ms,
                )
            if event_type == schemas.BuildEventType.FAILED.value:
                build.results = [
                    schemas.BuildTabResult.model_validate(item) for item in normalized.get('results', []) if isinstance(item, dict)
                ]
                build.update_progress(
                    progress=_safe_float(normalized.get('progress'), build.progress),
                    elapsed_ms=_safe_int(normalized.get('elapsed_ms')) or build.elapsed_ms,
                    estimated_remaining_ms=None,
                    current_step=build.current_step,
                    current_step_index=build.current_step_index,
                    total_steps=_safe_int(normalized.get('total_steps')) or build.total_steps,
                )
                build.update_status(
                    schemas.ActiveBuildStatus.FAILED,
                    duration_ms=_safe_int(normalized.get('duration_ms')) or build.elapsed_ms,
                    error=_safe_str(normalized.get('error')),
                )
            return build

    def _prune_finished_locked(self) -> None:
        now = _utcnow()
        removable: set[str] = set()
        finished: list[ActiveBuild] = []
        for build in self._builds.values():
            if build.status not in {schemas.ActiveBuildStatus.COMPLETED, schemas.ActiveBuildStatus.FAILED}:
                continue
            finished.append(build)
            finished_at = build.finished_at or build.updated_at
            if (now - finished_at).total_seconds() > _FINISHED_BUILD_TTL_SECONDS:
                removable.add(build.build_id)

        finished.sort(key=lambda item: item.finished_at or item.updated_at, reverse=True)
        for build in finished[_MAX_FINISHED_BUILDS:]:
            removable.add(build.build_id)

        for build_id in removable:
            self._builds.pop(build_id, None)
            self._watchers.pop(build_id, None)


registry = ActiveBuildRegistry()
