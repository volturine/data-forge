import time

import polars as pl

from core.config import settings
from core.exceptions import EngineTimeoutError, StepNotFoundError


def find_step_index(pipeline_steps: list[dict], target_step_id: str) -> int:
    if target_step_id == 'source':
        return -1
    for idx, step in enumerate(pipeline_steps):
        if step.get('id') == target_step_id:
            return idx
    raise StepNotFoundError(target_step_id)


def is_step_applied(step: dict) -> bool:
    return step.get('is_applied') is not False


def apply_pipeline_steps(pipeline_steps: list[dict]) -> list[dict]:
    applied = [step for step in pipeline_steps if is_step_applied(step)]
    if not applied:
        return []

    step_map: dict[str, dict] = {}
    for step in pipeline_steps:
        step_id = step.get('id')
        if not step_id:
            continue
        step_map[str(step_id)] = step

    applied_ids: set[str] = set()
    for step in applied:
        step_id = step.get('id')
        if not step_id:
            continue
        applied_ids.add(str(step_id))

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
        next_seen = set(visited)
        next_seen.add(parent_id)
        return resolve_parent(parent_id, next_seen)

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


def resolve_applied_target(pipeline_steps: list[dict], target_step_id: str) -> str:
    if target_step_id == 'source':
        return 'source'

    step_map: dict[str, dict] = {}
    for step in pipeline_steps:
        step_id = step.get('id')
        if not step_id:
            continue
        step_map[str(step_id)] = step

    if target_step_id not in step_map:
        return 'source'

    if is_step_applied(step_map[target_step_id]):
        return target_step_id

    current: str | None = target_step_id
    seen: set[str] = set()
    while True:
        if current is None:
            return 'source'
        step = step_map.get(current) or {}
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


def await_engine_result(engine, timeout: int, job_id: str | None = None) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        if not engine.is_process_alive():
            return {
                'data': None,
                'error': 'Compute process died unexpectedly.',
                'job_id': job_id,
            }
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise EngineTimeoutError(f'Operation timed out after {timeout} seconds', timeout)

        poll_timeout = min(0.1, max(0.01, remaining))
        result_data = engine.get_result(timeout=poll_timeout, job_id=job_id)
        if result_data:
            return result_data


def build_datasource_config(datasource, overrides: dict | None = None) -> dict:
    base = {
        'source_type': datasource.source_type,
        **datasource.config,
    }
    if not overrides:
        return base
    return {**base, **overrides}


def normalize_timezones(lf: pl.LazyFrame, schema: pl.Schema | None = None) -> pl.LazyFrame:
    if not settings.normalize_tz:
        return lf

    schema = schema or lf.collect_schema()
    exprs: list[pl.Expr] = []

    for name, dtype in schema.items():
        if not isinstance(dtype, pl.Datetime):
            continue
        tz = dtype.time_zone
        if tz is None:
            exprs.append(pl.col(name).dt.replace_time_zone(settings.timezone).alias(name))
            continue
        exprs.append(pl.col(name).dt.convert_time_zone(settings.timezone).alias(name))

    if not exprs:
        return lf
    return lf.with_columns(exprs)
