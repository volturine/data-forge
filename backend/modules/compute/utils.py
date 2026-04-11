import time
from typing import Any

import polars as pl

from core.config import settings
from core.exceptions import EngineTimeoutError, StepNotFoundError
from modules.compute.core.base import ComputeEngine, EngineResult


def find_step_index(steps: list[dict], target_step_id: str) -> int:
    if target_step_id == 'source':
        return -1
    for idx, step in enumerate(steps):
        if step.get('id') == target_step_id:
            return idx
    raise StepNotFoundError(target_step_id)


def is_step_applied(step: dict) -> bool:
    return step.get('is_applied') is not False


def _build_step_map(steps: list[dict]) -> dict[str, dict]:
    return {str(s['id']): s for s in steps if s.get('id')}


def apply_steps(steps: list[dict]) -> list[dict]:
    applied = [step for step in steps if is_step_applied(step)]
    if not applied:
        return []

    step_map = _build_step_map(steps)

    applied_ids = {str(s['id']) for s in applied if s.get('id')}

    def resolve_parent(step_id: str, seen: set[str] | None = None) -> str | None:
        step = step_map.get(step_id)
        if not step:
            return None
        deps = step.get('depends_on') or []
        if not deps:
            return None
        parent_id = deps[0]
        if not parent_id:
            return None
        parent_id = str(parent_id)
        if parent_id in applied_ids:
            return parent_id
        visited = seen or set()
        if parent_id in visited:
            return None
        return resolve_parent(parent_id, visited | {parent_id})

    next_steps: list[dict] = []
    for step in applied:
        step_id = step.get('id')
        if not step_id:
            next_steps.append(step)
            continue
        parent_id = resolve_parent(str(step_id))
        if parent_id:
            next_steps.append({**step, 'depends_on': [parent_id]})
            continue
        next_steps.append({**step, 'depends_on': []})

    return next_steps


def resolve_applied_target(steps: list[dict], target_step_id: str) -> str:
    if target_step_id == 'source':
        return 'source'

    step_map = _build_step_map(steps)

    if target_step_id not in step_map:
        return 'source'

    if is_step_applied(step_map[target_step_id]):
        return target_step_id

    current: str | None = target_step_id
    seen: set[str] = set()
    while True:
        if current is None:
            return 'source'
        step = step_map.get(current)
        if not step:
            return 'source'
        deps = step.get('depends_on') or []
        if not deps:
            return 'source'
        parent = deps[0]
        if not parent:
            return 'source'
        parent_id = str(parent)
        if parent_id in seen:
            return 'source'
        seen.add(parent_id)
        parent_step = step_map.get(parent_id)
        if parent_step and is_step_applied(parent_step):
            return parent_id
        current = parent_id


def _engine_result_to_dict(result: EngineResult) -> dict[str, Any]:
    """Normalize compute engine result payloads for service-layer consumption."""
    return {
        'job_id': result.job_id,
        'data': result.data,
        'error': result.error,
        'error_kind': result.error_kind,
        'error_details': result.error_details or {},
        'step_timings': result.step_timings,
        'query_plan': result.query_plan,
        'read_duration_ms': result.read_duration_ms,
        'write_duration_ms': result.write_duration_ms,
    }


def await_engine_result(engine: ComputeEngine, timeout: int, job_id: str | None = None) -> dict:
    deadline = time.monotonic() + timeout
    result = engine.get_result(timeout=0, job_id=job_id)
    if result is not None:
        return _engine_result_to_dict(result)
    while True:
        if not engine.is_process_alive():
            return {
                'data': None,
                'error': 'Compute process died unexpectedly.',
                'error_kind': 'engine_process_died',
                'error_details': {},
                'job_id': job_id,
            }
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise EngineTimeoutError(f'Operation timed out after {timeout} seconds', timeout)

        poll_timeout = min(0.1, max(0.01, remaining))
        result = engine.get_result(timeout=poll_timeout, job_id=job_id)
        if result is not None:
            return _engine_result_to_dict(result)


def build_datasource_config(datasource, overrides: dict | None = None) -> dict:
    return {'source_type': datasource.source_type, **datasource.config, **(overrides or {})}


def normalize_timezones(lf: pl.LazyFrame, schema: pl.Schema | None = None) -> pl.LazyFrame:
    if not settings.normalize_tz:
        return lf

    schema = schema or lf.collect_schema()
    exprs: list[pl.Expr] = []

    for name, dtype in schema.items():
        if not isinstance(dtype, pl.Datetime):
            continue
        tz = dtype.time_zone
        expr = pl.col(name).dt.replace_time_zone(settings.timezone) if tz is None else pl.col(name).dt.convert_time_zone(settings.timezone)
        exprs.append(expr.alias(name))

    if not exprs:
        return lf
    return lf.with_columns(exprs)
