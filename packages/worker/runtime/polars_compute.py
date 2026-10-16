from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable

import polars as pl

from operations import HANDLERS
from operations.datasource import load_datasource
from operations.plot import ChartParams, compute_chart_data, compute_overlay_datasets
from operations.step_converter import BackendStep, convert_step_format
from runtime.compute_utils import apply_steps, normalize_timezones
from runtime.domain.analysis.step_types import STEP_TYPES
from runtime.exceptions import IcebergMetadataPathNotFoundError, PipelineValidationError
from runtime.export_formats import get_export_format
from runtime.preview_cache import PreviewCache

logger = logging.getLogger(__name__)
_PREVIEW_CACHE = PreviewCache()


def classify_engine_error(exc: Exception) -> tuple[str, dict[str, object]]:
    if isinstance(exc, PipelineValidationError):
        return "pipeline_validation", {"details": exc.details}
    if isinstance(exc, IcebergMetadataPathNotFoundError):
        return "datasource_metadata_missing", {"metadata_path": exc.metadata_path}
    if isinstance(exc, FileNotFoundError):
        return "datasource_metadata_missing", {}
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 2:
        return "datasource_metadata_missing", {}
    message = str(exc)
    if ("NO_SUCH_KEY" in message or "RESOURCE_NOT_FOUND" in message) and "GetObject" in message:
        return "datasource_metadata_missing", {}
    if ("Failed to open local file" in message or "No such file or directory" in message) and "/metadata/" in message and ".metadata.json" in message:
        return "datasource_metadata_missing", {}
    if isinstance(exc, ValueError):
        return "value_error", {}
    if isinstance(exc, pl.exceptions.ComputeError) and str(exc) == "at least one key is required in a group_by operation":
        return "value_error", {}
    return "execution_error", {}


def _build_pipeline_details(
    datasource_config: dict,
    steps: list[dict],
    job_id: str,
    additional_datasources: dict[str, dict] | None = None,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
    preview_cache: PreviewCache | None = None,
) -> tuple[pl.LazyFrame, dict[str, float], float, str | None]:
    read_started = time.perf_counter()
    source_key: str | None = None
    if preview_cache is not None:
        datasource_config, source_key = preview_cache.source(datasource_config)
    right_configs: dict[str, dict] = {}
    right_keys: dict[str, str | None] = {}
    for ds_id, ds_config in (additional_datasources or {}).items():
        try:
            right_configs[ds_id], right_keys[ds_id] = preview_cache.source(ds_config) if preview_cache is not None else (ds_config, None)
        except Exception as e:
            logger.error(f"Failed to load additional datasource {ds_id}: {e}", exc_info=True)
            raise PipelineValidationError(
                f"Failed to load datasource {ds_id}: {e}",
                details={"datasource_id": ds_id},
            ) from e
    read_duration_ms = (time.perf_counter() - read_started) * 1000

    steps = apply_steps(steps)

    if not steps:
        read_started = time.perf_counter()
        cached = preview_cache.get(source_key) if preview_cache is not None else None
        lf = cached.lazy() if cached is not None else load_datasource(datasource_config)
        return lf, {}, read_duration_ms + (time.perf_counter() - read_started) * 1000, source_key

    step_map: dict[str, dict] = {}
    for step in steps:
        step_id = step.get("id")
        if not step_id:
            raise ValueError("Each pipeline step must include an id")
        step_map[step_id] = step

    dependency_map: dict[str, str | None] = {}
    dependents: dict[str, list[str]] = {}
    in_degree: dict[str, int] = dict.fromkeys(step_map, 0)

    for step_id, step in step_map.items():
        deps = step.get("depends_on") or []
        if len(deps) > 1:
            raise PipelineValidationError(
                f"Step {step_id} has multiple dependencies. Merge steps are not supported.",
                step_id=step_id,
            )

        if len(deps) == 0:
            dependency_map[step_id] = None
            continue

        dep_id = deps[0]
        if dep_id not in step_map:
            raise PipelineValidationError(
                f"Step {step_id} depends on missing step {dep_id}.",
                step_id=step_id,
                details={"missing_step_id": dep_id},
            )

        dependency_map[step_id] = dep_id
        dependents.setdefault(dep_id, []).append(step_id)
        in_degree[step_id] = in_degree.get(step_id, 0) + 1

    queue = deque(step_id for step_id, degree in in_degree.items() if degree == 0)
    ordered_steps: list[dict] = []
    while queue:
        current_id = queue.popleft()
        ordered_steps.append(step_map[current_id])
        for child_id in dependents.get(current_id, []):
            in_degree[child_id] = in_degree.get(child_id, 0) - 1
            if in_degree[child_id] == 0:
                queue.append(child_id)

    if len(ordered_steps) != len(step_map):
        raise PipelineValidationError("Pipeline contains a cycle. Remove cyclic dependencies to continue.")

    backend_steps: dict[str, BackendStep] = {}
    step_keys: dict[str, str | None] = {}
    cached_frames: dict[str, pl.DataFrame] = {}
    for idx, step in enumerate(ordered_steps):
        step_id = step["id"]
        try:
            backend_steps[step_id] = convert_step_format(step)
        except Exception as e:
            logger.error(f"Failed to convert step {idx}: {e}", exc_info=True)
            raise PipelineValidationError(
                f"Step conversion failed: {e!s}",
                step_id=str(step.get("id") or ""),
                details={"operation": step.get("type")},
            ) from e
        parent_id = dependency_map[step_id]
        parent_key = step_keys[parent_id] if parent_id is not None else source_key
        step_keys[step_id] = preview_cache.step_key(parent_key, backend_steps[step_id], right_keys) if preview_cache is not None else None
        cached = preview_cache.get(step_keys[step_id]) if preview_cache is not None else None
        if cached is not None:
            cached_frames[step_id] = cached

    # Each branch stops at its nearest materialized ancestor. Other branches,
    # including side effects, still execute even when one branch is cached.
    required_steps: set[str] = set()
    for step_id in step_map:
        if dependents.get(step_id):
            continue
        ancestor_id: str | None = step_id
        while ancestor_id is not None and ancestor_id not in required_steps:
            required_steps.add(ancestor_id)
            if ancestor_id in cached_frames:
                break
            ancestor_id = dependency_map[ancestor_id]

    read_started = time.perf_counter()
    lf = pl.LazyFrame()
    if any(dependency_map[step_id] is None and step_id not in cached_frames for step_id in required_steps):
        cached = preview_cache.get(source_key) if preview_cache is not None else None
        lf = cached.lazy() if cached is not None else load_datasource(datasource_config)
    required_sources: set[str] = set()
    for step_id in required_steps - cached_frames.keys():
        params = backend_steps[step_id].params
        right_source = params.get("right_source")
        if isinstance(right_source, str):
            required_sources.add(right_source)
        sources = params.get("sources")
        if isinstance(sources, list):
            required_sources.update(source for source in sources if isinstance(source, str))
    right_sources: dict[str, pl.LazyFrame] = {}
    for ds_id, ds_config in right_configs.items():
        if preview_cache is not None and ds_id not in required_sources:
            continue
        try:
            cached = preview_cache.get(right_keys[ds_id]) if preview_cache is not None else None
            right_sources[ds_id] = cached.lazy() if cached is not None else load_datasource(ds_config)
        except Exception as e:
            raise PipelineValidationError(f"Failed to load datasource {ds_id}: {e}", details={"datasource_id": ds_id}) from e
    read_duration_ms += (time.perf_counter() - read_started) * 1000

    schema_map: dict[str, pl.LazyFrame] = {}
    total_steps = len(ordered_steps)
    step_timings: dict[str, float] = {}
    for idx, step in enumerate(ordered_steps):
        step_id = step["id"]
        step_type = step.get("type") or ""
        backend_step = backend_steps[step_id]
        progress = (idx + 1) / total_steps
        step_name = backend_step.name or f"Step {idx + 1}"
        logger.debug(f"Job {job_id}: Processing {step_name} ({progress:.0%})")

        right_source_raw = backend_step.params.get("right_source")
        right_source_id = right_source_raw if isinstance(right_source_raw, str) else None
        right_lf = right_sources.get(right_source_id) if right_source_id is not None else None

        step_start = time.perf_counter()
        if progress_callback is not None:
            progress_callback(
                {
                    "type": "step_start",
                    "step_index": idx,
                    "step_id": str(step_id),
                    "step_name": step_name,
                    "step_type": step_type,
                    "total_steps": total_steps,
                }
            )
        try:
            if step_id in cached_frames:
                schema_map[step_id] = cached_frames[step_id].lazy()
            elif step_id in required_steps:
                parent_id = dependency_map[step_id]
                parent_frame = schema_map[parent_id] if parent_id is not None else lf
                schema_map[step_id] = apply_step(
                    parent_frame,
                    backend_step,
                    step_id=str(step_id),
                    right_sources=right_sources,
                    right_lf=right_lf,
                )
        except Exception as exc:
            if progress_callback is not None:
                progress_callback(
                    {
                        "type": "step_failed",
                        "step_index": idx,
                        "step_id": str(step_id),
                        "step_name": step_name,
                        "step_type": step_type,
                        "error": str(exc),
                        "total_steps": total_steps,
                    }
                )
            raise
        timing_label = step_type or f"step_{idx + 1}"
        if timing_label in step_timings:
            counter = 2
            while f"{timing_label}_{counter}" in step_timings:
                counter += 1
            timing_label = f"{timing_label}_{counter}"
        step_timings[timing_label] = (time.perf_counter() - step_start) * 1000
        if progress_callback is not None:
            progress_callback(
                {
                    "type": "step_complete",
                    "step_index": idx,
                    "step_id": str(step_id),
                    "step_name": step_name,
                    "step_type": step_type,
                    "duration_ms": int(step_timings[timing_label]),
                    "row_count": None,
                    "total_steps": total_steps,
                    "progress": progress,
                }
            )

    result_id = ordered_steps[-1]["id"]
    return schema_map[result_id], step_timings, read_duration_ms, step_keys[result_id]


def _build_pipeline_with_plans(
    datasource_config: dict,
    steps: list[dict],
    job_id: str,
    additional_datasources: dict[str, dict] | None,
    progress_callback: Callable[[dict[str, object]], None] | None,
    preview_cache: PreviewCache | None = None,
) -> tuple[pl.LazyFrame, dict[str, float], float, dict[str, str], str | None]:
    """Build the pipeline frame and report its optimized/unoptimized query plans."""
    lf, step_timings, read_duration_ms, cache_key = _build_pipeline_details(
        datasource_config, steps, job_id, additional_datasources, progress_callback, preview_cache
    )
    query_plans = {"optimized": lf.explain(optimized=True), "unoptimized": lf.explain(optimized=False)}
    if progress_callback is not None:
        progress_callback({"type": "plan", "optimized_plan": query_plans["optimized"], "unoptimized_plan": query_plans["unoptimized"]})
    return lf, step_timings, read_duration_ms, query_plans, cache_key


def _resolve_chart_preview(
    lf: pl.LazyFrame,
    steps: list[dict],
    row_limit: int,
    offset: int,
) -> tuple[pl.LazyFrame, dict | None]:
    """If the last step is a chart, compute chart data and metadata."""
    if not steps:
        return lf, None
    last_step = steps[-1]
    last_type = str(last_step.get("type", ""))
    if not STEP_TYPES.is_chart_step_type(last_type):
        return lf, None

    chart_config = last_step.get("config", {})
    chart_type = STEP_TYPES.chart_type(last_type)
    if chart_type:
        chart_config = {**chart_config, "chart_type": chart_type}
    chart_model = ChartParams.model_validate(chart_config)
    preview_lf = compute_chart_data(lf, chart_config)
    metadata = {
        "y_axis_scale": chart_model.y_axis_scale,
        "y_axis_min": chart_model.y_axis_min,
        "y_axis_max": chart_model.y_axis_max,
        "display_units": chart_model.display_units,
        "decimal_places": chart_model.decimal_places,
        "legend_position": chart_model.legend_position,
        "title": chart_model.title,
        "overlays": compute_overlay_datasets(
            lf,
            chart_model,
            row_limit=row_limit,
            offset=offset,
        ),
        "reference_lines": [line.model_dump() for line in chart_model.reference_lines],
    }
    return preview_lf, metadata


def execute_preview(
    datasource_config: dict,
    steps: list[dict],
    row_limit: int,
    offset: int,
    job_id: str,
    additional_datasources: dict[str, dict] | None = None,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> dict:
    """Execute pipeline and return limited rows for preview."""
    lf, step_timings, read_duration_ms, query_plans, cache_key = _build_pipeline_with_plans(
        datasource_config, steps, job_id, additional_datasources, progress_callback, _PREVIEW_CACHE
    )

    preview_lf, metadata = _resolve_chart_preview(lf, steps, row_limit, offset)

    # Get schema from lazy frame (no collection needed)
    schema_obj = preview_lf.collect_schema()
    schema = {col: str(dtype) for col, dtype in schema_obj.items()}
    collect_started = time.perf_counter()
    if metadata is None:
        raw_page = _PREVIEW_CACHE.collect(cache_key, preview_lf, offset, row_limit)
        preview_df = normalize_timezones(raw_page.lazy(), schema_obj).collect()
    else:
        preview_df = normalize_timezones(preview_lf, schema_obj).slice(offset, row_limit).collect()
    collect_duration_ms = (time.perf_counter() - collect_started) * 1000

    result: dict = {
        "schema": schema,
        "row_count": preview_df.height,  # Rows in this preview page
        "data": preview_df.to_dicts(),
        "query_plan": query_plans["optimized"],
        "query_plans": query_plans,
        "step_timings": step_timings,
        "read_duration_ms": read_duration_ms,
        "collect_duration_ms": collect_duration_ms,
    }

    if metadata:
        result["metadata"] = metadata

    return result


def execute_export(
    datasource_config: dict,
    steps: list[dict],
    output_path: str,
    export_format: str,
    job_id: str,
    additional_datasources: dict[str, dict] | None = None,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> dict:
    """Execute pipeline and write full results to file."""
    lf, step_timings, read_duration_ms, query_plans, _cache_key = _build_pipeline_with_plans(
        datasource_config, steps, job_id, additional_datasources, progress_callback
    )

    fmt = get_export_format(export_format)
    schema = {col: str(dtype) for col, dtype in lf.collect_schema().items()}

    if progress_callback is not None:
        progress_callback({"type": "compute_start"})

    write_started = time.perf_counter()
    row_count = fmt.write(lf, output_path)
    write_duration_ms = (time.perf_counter() - write_started) * 1000

    if progress_callback is not None:
        progress_callback({"type": "compute_complete", "duration_ms": write_duration_ms})

    return {
        "output_path": output_path,
        "export_format": export_format,
        "row_count": row_count,
        "schema": schema,
        "query_plan": query_plans["optimized"],
        "query_plans": query_plans,
        "step_timings": step_timings,
        "read_duration_ms": read_duration_ms,
        "write_duration_ms": write_duration_ms,
    }


def execute_schema(
    datasource_config: dict,
    steps: list[dict],
    job_id: str,
    additional_datasources: dict[str, dict] | None = None,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> dict:
    """Execute pipeline and return schema without collecting full data."""
    lf, step_timings, read_duration_ms, query_plans, _cache_key = _build_pipeline_with_plans(
        datasource_config, steps, job_id, additional_datasources, progress_callback
    )
    # Get schema from lazy frame (no full collection needed)
    schema = {col: str(dtype) for col, dtype in lf.collect_schema().items()}

    return {
        "schema": schema,
        "columns": list(schema.keys()),
        "step_timings": step_timings,
        "query_plan": query_plans["optimized"],
        "query_plans": query_plans,
        "read_duration_ms": read_duration_ms,
    }


def execute_row_count(
    datasource_config: dict,
    steps: list[dict],
    job_id: str,
    additional_datasources: dict[str, dict] | None = None,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> dict:
    """Execute pipeline and return row count without collecting full data."""
    lf, step_timings, read_duration_ms, query_plans, _cache_key = _build_pipeline_with_plans(
        datasource_config, steps, job_id, additional_datasources, progress_callback
    )

    collect_started = time.perf_counter()
    row_count = lf.select(pl.len()).collect().item()
    collect_duration_ms = (time.perf_counter() - collect_started) * 1000

    return {
        "row_count": int(row_count),
        "step_timings": step_timings,
        "query_plan": query_plans["optimized"],
        "query_plans": query_plans,
        "read_duration_ms": read_duration_ms,
        "collect_duration_ms": collect_duration_ms,
    }


def apply_step(
    lf: pl.LazyFrame,
    step: BackendStep,
    step_id: str,
    right_sources: dict[str, pl.LazyFrame] | None = None,
    right_lf: pl.LazyFrame | None = None,
) -> pl.LazyFrame:
    """Apply a single transformation step to the LazyFrame."""
    operation = step.operation
    if not operation:
        raise ValueError("Step operation is required")
    params = step.params

    handler = HANDLERS.get(operation)

    if not handler:
        raise ValueError(f"Unsupported operation: {operation}")

    return handler(lf, params, right_lf=right_lf, right_sources=right_sources, step_id=step_id)
