from typing import Any

import polars as pl

from runtime.config import settings
from runtime.domain.compute.base import ComputeWorker, ComputeWorkerResult
from runtime.exceptions import step_not_found


def find_step_index(steps: list[dict], target_step_id: str) -> int:
    if target_step_id == "source":
        return -1
    for idx, step in enumerate(steps):
        if step.get("id") == target_step_id:
            return idx
    raise step_not_found(target_step_id)


def is_step_applied(step: dict) -> bool:
    return step.get("is_applied") is not False


def _build_step_map(steps: list[dict]) -> dict[str, dict]:
    return {str(s["id"]): s for s in steps if s.get("id")}


def _nearest_applied_ancestor(step_id: str, step_map: dict[str, dict], applied_ids: set[str]) -> str | None:
    step = step_map.get(step_id)
    if step is None:
        return None

    dependencies = step.get("depends_on") or []
    if not dependencies or not dependencies[0]:
        return None

    parent_id = str(dependencies[0])
    seen: set[str] = set()
    while parent_id not in applied_ids:
        if parent_id in seen:
            return None
        seen.add(parent_id)

        parent = step_map.get(parent_id)
        if parent is None:
            return None
        dependencies = parent.get("depends_on") or []
        if not dependencies or not dependencies[0]:
            return None
        parent_id = str(dependencies[0])

    return parent_id


def apply_steps(steps: list[dict]) -> list[dict]:
    applied = [step for step in steps if is_step_applied(step)]
    if not applied:
        return []

    step_map = _build_step_map(steps)

    applied_ids = {str(s["id"]) for s in applied if s.get("id")}

    next_steps: list[dict] = []
    for step in applied:
        step_id = step.get("id")
        if not step_id:
            next_steps.append(step)
            continue
        parent_id = _nearest_applied_ancestor(str(step_id), step_map, applied_ids)
        if parent_id:
            next_steps.append({**step, "depends_on": [parent_id]})
            continue
        next_steps.append({**step, "depends_on": []})

    return next_steps


def resolve_applied_target(steps: list[dict], target_step_id: str) -> str:
    if target_step_id == "source":
        return "source"

    step_map = _build_step_map(steps)

    if target_step_id not in step_map:
        return "source"

    if is_step_applied(step_map[target_step_id]):
        return target_step_id

    applied_ids = {step_id for step_id, step in step_map.items() if is_step_applied(step)}
    return _nearest_applied_ancestor(target_step_id, step_map, applied_ids) or "source"


def _compute_worker_result_to_dict(result: ComputeWorkerResult) -> dict[str, Any]:
    """Normalize compute engine result payloads for service-layer consumption."""
    return {
        "job_id": result.job_id,
        "data": result.data,
        "error": result.error,
        "error_kind": result.error_kind,
        "error_details": result.error_details or {},
        "step_timings": result.step_timings,
        "query_plan": result.query_plan,
        "read_duration_ms": result.read_duration_ms,
        "write_duration_ms": result.write_duration_ms,
        "collect_duration_ms": result.collect_duration_ms,
    }


def await_compute_worker_result(engine: ComputeWorker, job_id: str | None = None) -> dict:
    result = engine.get_result(timeout=0, job_id=job_id)
    if result is not None:
        return _compute_worker_result_to_dict(result)
    while True:
        if not engine.is_process_alive():
            return {
                "data": None,
                "error": "Compute process died unexpectedly.",
                "error_kind": "engine_process_died",
                "error_details": {},
                "job_id": job_id,
            }
        result = engine.get_result(timeout=0.1, job_id=job_id)
        if result is not None:
            return _compute_worker_result_to_dict(result)


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
