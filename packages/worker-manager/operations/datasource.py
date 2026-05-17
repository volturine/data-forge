import asyncio
import contextvars
import hashlib
import json
from collections import deque
from collections.abc import Callable
from threading import Lock

import polars as pl
from contracts.compute.base import OperationHandler, OperationParams
from contracts.datasource.source_types import DataSourceType
from contracts.enums import DataForgeStrEnum
from core.iceberg_metadata import resolve_iceberg_branch_metadata_path
from pydantic import ConfigDict

from datasources.datasource_loading import load_datasource_frame
from operations.step_converter import convert_step_format


class DatasourceLoadType(DataForgeStrEnum):
    DUCKDB = "duckdb"


class IcebergReader(DataForgeStrEnum):
    NATIVE = "native"
    PYICEBERG = "pyiceberg"


class DatasourceParams(OperationParams):
    model_config = ConfigDict(extra="allow")

    source_type: DataSourceType | DatasourceLoadType = DataSourceType.FILE
    analysis_tab_id: str | None = None
    analysis_pipeline: dict | None = None
    file_path: str | None = None
    file_type: str | None = None
    options: dict | None = None
    csv_options: dict | None = None
    sheet_name: str | None = None
    start_row: int | None = None
    start_col: int | None = None
    end_col: int | None = None
    end_row: int | None = None
    has_header: bool | None = None
    table_name: str | None = None
    named_range: str | None = None
    cell_range: str | None = None
    connection_string: str | None = None
    query: str | None = None
    db_path: str | None = None
    read_only: bool = True
    metadata_path: str | None = None
    branch: str | None = None
    namespace_name: str | None = None
    snapshot_id: str | None = None
    snapshot_timestamp_ms: int | None = None
    storage_options: dict | None = None
    reader: IcebergReader | None = None


class DatasourceHandler(OperationHandler):
    SOURCE_LOADERS: dict[str, Callable[["DatasourceHandler", DatasourceParams], pl.LazyFrame]] = {}

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = DatasourceParams.model_validate(params)
        loader = self.SOURCE_LOADERS.get(validated.source_type.value)
        if not loader:
            allowed = ", ".join(sorted(self.SOURCE_LOADERS))
            raise ValueError(f"Unsupported source type: {validated.source_type}. Allowed: {allowed}")
        return loader(self, validated)

    async def call_async(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        return await asyncio.to_thread(self.__call__, lf, params)

    def _load_file(self, config: DatasourceParams) -> pl.LazyFrame:
        return load_datasource_frame(config.model_dump(mode="json"))

    def _load_database(self, config: DatasourceParams) -> pl.LazyFrame:
        return load_datasource_frame(config.model_dump(mode="json"))

    def _load_duckdb(self, config: DatasourceParams) -> pl.LazyFrame:
        return load_datasource_frame(config.model_dump(mode="json"))

    def _load_iceberg(self, config: DatasourceParams) -> pl.LazyFrame:
        if config.snapshot_id is None and config.snapshot_timestamp_ms is not None and config.metadata_path is not None:
            metadata_path = resolve_iceberg_branch_metadata_path(
                config.metadata_path,
                config.branch,
                namespace_name=config.namespace_name,
            )
            from pyiceberg.table import StaticTable

            table = StaticTable.from_metadata(metadata_path)
            snapshot = table.snapshot_as_of_timestamp(config.snapshot_timestamp_ms)
            if snapshot is None:
                raise ValueError("Iceberg snapshot not found for the selected timestamp")
            config = config.model_copy(update={"snapshot_id": str(snapshot.snapshot_id)})
        return load_datasource_frame(config.model_dump(mode="json"))

    def _load_analysis(self, config: DatasourceParams) -> pl.LazyFrame:
        pipeline = config.analysis_pipeline
        if isinstance(pipeline, dict):
            pipeline_id = pipeline.get("analysis_id")
            if pipeline_id:
                return _load_analysis_pipeline(pipeline, str(pipeline_id), config.analysis_tab_id)
        raise ValueError("analysis_pipeline is required for analysis datasource loading")


_analysis_stack_var: contextvars.ContextVar[tuple[tuple[str, str | None], ...]] = contextvars.ContextVar(
    "_analysis_stack",
    default=(),
)
_ANALYSIS_CACHE: dict[str, pl.LazyFrame] = {}
_ANALYSIS_CACHE_KEYS: deque[str] = deque()
_ANALYSIS_CACHE_LOCK = Lock()
_ANALYSIS_CACHE_MAX = 20


def _get_analysis_stack() -> tuple[tuple[str, str | None], ...]:
    return _analysis_stack_var.get()


def _load_analysis_pipeline(pipeline: dict, analysis_id: str, tab_id: str | None) -> pl.LazyFrame:
    stack = _get_analysis_stack()
    stack_key = (analysis_id, tab_id)
    if stack_key in stack:
        raise ValueError("Analysis pipeline contains a circular reference")
    token = _analysis_stack_var.set((*stack, stack_key))
    try:
        cache_key = _analysis_cache_key(pipeline, tab_id)
        cached = _get_analysis_cache(cache_key)
        if cached is not None:
            return cached
        frame = _build_analysis_from_pipeline(pipeline, tab_id)
        _store_analysis_cache(cache_key, frame)
        return frame
    finally:
        _analysis_stack_var.reset(token)


def _analysis_cache_key(pipeline: dict, tab_id: str | None) -> str:
    payload = {
        "analysis_id": pipeline.get("analysis_id"),
        "tab_id": tab_id,
        "tabs": pipeline.get("tabs", []),
    }
    data = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _resolve_pipeline_datasource(pipeline: dict, datasource: dict) -> dict:
    datasource_id = datasource.get("id")
    if not isinstance(datasource_id, str) or not datasource_id:
        raise ValueError("Analysis tab missing datasource.id")
    config = datasource.get("config")
    if not isinstance(config, dict):
        raise ValueError("Analysis tab datasource.config must be a dict")
    branch = config.get("branch")
    if not isinstance(branch, str) or not branch.strip():
        raise ValueError("Analysis tab datasource.config.branch is required")
    analysis_tab_id = datasource.get("analysis_tab_id")
    if isinstance(analysis_tab_id, str) and analysis_tab_id:
        return {
            "source_type": DataSourceType.ANALYSIS.value,
            "analysis_id": str(pipeline.get("analysis_id") or ""),
            "analysis_tab_id": analysis_tab_id,
            **config,
        }
    source_type = DataSourceType.read(datasource.get("source_type"), default=None)
    if source_type is None:
        raise ValueError(f"Analysis pipeline missing datasource metadata for {datasource_id}")
    return {"source_type": source_type.value, **config}


def _step_source_payload(step_config: dict, source_id: str) -> dict | None:
    direct = step_config.get("right_source_datasource")
    if isinstance(direct, dict) and direct.get("id") == source_id:
        return direct
    many = step_config.get("source_datasources")
    if not isinstance(many, list):
        return None
    return next(
        (item for item in many if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id") == source_id),
        None,
    )


def _get_analysis_cache(key: str) -> pl.LazyFrame | None:
    with _ANALYSIS_CACHE_LOCK:
        return _ANALYSIS_CACHE.get(key)


def _store_analysis_cache(key: str, frame: pl.LazyFrame) -> None:
    with _ANALYSIS_CACHE_LOCK:
        if key in _ANALYSIS_CACHE:
            return
        _ANALYSIS_CACHE[key] = frame
        _ANALYSIS_CACHE_KEYS.append(key)
        if len(_ANALYSIS_CACHE_KEYS) <= _ANALYSIS_CACHE_MAX:
            return
        oldest = _ANALYSIS_CACHE_KEYS.popleft()
        _ANALYSIS_CACHE.pop(oldest, None)


def _resolve_analysis_tab(tabs: list[dict], analysis_tab_id: str | None) -> dict:
    selected = None
    if analysis_tab_id:
        selected = next((tab for tab in tabs if tab.get("id") == analysis_tab_id), None)
    if not selected:
        selected = next((tab for tab in tabs if tab.get("steps")), None)
    if not selected:
        raise ValueError("Analysis pipeline missing tab steps")
    return selected


def _resolve_tab_chain(tabs: list[dict], target_tab_id: str) -> list[dict]:
    output_to_tab: dict[str, dict] = {}
    tab_input: dict[str, str] = {}
    output_map: dict[str, str] = {}
    for tab in tabs:
        tab_id = tab.get("id")
        output = tab.get("output") if isinstance(tab, dict) else None
        output_id = output.get("result_id") if isinstance(output, dict) else None
        if not tab_id or not output_id:
            continue
        output_map[str(tab_id)] = str(output_id)
    for tab in tabs:
        tid = tab.get("id")
        output = tab.get("output") if isinstance(tab, dict) else None
        output_id = output.get("result_id") if isinstance(output, dict) else None
        datasource = tab.get("datasource") if isinstance(tab, dict) else None
        input_id = datasource.get("id") if isinstance(datasource, dict) else None
        if tid and output_id:
            output_to_tab[str(output_id)] = tab
        if tid and input_id:
            tab_input[str(tid)] = str(input_id)

    ordered: list[dict] = []
    seen: set[str] = set()
    current_id = target_tab_id
    while current_id:
        if current_id in seen:
            break
        seen.add(current_id)
        current_tab = next((tab for tab in tabs if tab.get("id") == current_id), None)
        if not current_tab:
            break
        ordered.append(current_tab)
        input_ds = tab_input.get(current_id)
        if input_ds and input_ds in output_to_tab:
            upstream_tab = output_to_tab[input_ds]
            current_id = str(upstream_tab.get("id")) if upstream_tab.get("id") else ""
            continue
        break
    ordered.reverse()
    return ordered


def _build_tab_pipeline(
    tab: dict,
    pipeline: dict,
    cache: dict[str, pl.LazyFrame],
) -> pl.LazyFrame:
    datasource = tab.get("datasource") if isinstance(tab, dict) else None
    if not isinstance(datasource, dict):
        raise ValueError("Analysis tab datasource must be a dict")
    datasource_id = datasource.get("id")
    if not datasource_id:
        raise ValueError("Analysis tab missing datasource.id")

    if datasource_id in cache:
        base_frame = cache[datasource_id]
    else:
        merged = _resolve_pipeline_datasource(pipeline, datasource)
        analysis_id = pipeline.get("analysis_id")
        analysis_id = str(analysis_id) if analysis_id is not None else None
        if (
            analysis_id
            and DataSourceType.read(merged.get("source_type"), default=None) == DataSourceType.ANALYSIS
            and str(merged.get("analysis_id")) == analysis_id
        ):
            merged = {**merged, "analysis_pipeline": pipeline}

        base_frame = load_datasource(merged)

    steps = tab.get("steps", [])
    if not isinstance(steps, list):
        raise ValueError("Analysis tab steps must be a list")

    from runtime.compute_utils import apply_steps

    steps = apply_steps(steps)
    additional = _collect_analysis_sources(steps, pipeline, cache)

    from runtime.compute_engine import PolarsComputeEngine

    for step in steps:
        step_id = step.get("id") or "step"
        backend_step = convert_step_format(step)
        right_source_raw = backend_step.params.get("right_source")
        right_source_id = right_source_raw if isinstance(right_source_raw, str) else None
        right_lf = cache.get(right_source_id) if right_source_id is not None else None
        base_frame = PolarsComputeEngine._apply_step(
            base_frame,
            backend_step,
            right_sources=additional,
            right_lf=right_lf,
        )
        cache[step_id] = base_frame

    output = tab.get("output") if isinstance(tab, dict) else None
    output_id = output.get("result_id") if isinstance(output, dict) else None
    if output_id:
        cache[str(output_id)] = base_frame

    return base_frame


def _build_analysis_from_pipeline(pipeline: dict, analysis_tab_id: str | None) -> pl.LazyFrame:
    tabs = pipeline.get("tabs", [])
    if not isinstance(tabs, list) or not tabs:
        raise ValueError("Analysis pipeline missing tabs")

    selected = _resolve_analysis_tab(tabs, analysis_tab_id)
    target_id = selected.get("id") if selected else None
    if not target_id:
        raise ValueError("Analysis pipeline missing tab id")

    chain = _resolve_tab_chain(tabs, str(target_id))
    cache: dict[str, pl.LazyFrame] = {}
    last_frame: pl.LazyFrame | None = None
    for tab in chain:
        last_frame = _build_tab_pipeline(tab, pipeline, cache)

    if last_frame is None:
        raise ValueError("Analysis pipeline did not produce a LazyFrame")

    return last_frame


def _collect_analysis_sources(
    steps: list[dict],
    pipeline: dict,
    cache: dict[str, pl.LazyFrame],
) -> dict[str, pl.LazyFrame]:
    additional: dict[str, pl.LazyFrame] = {}
    output_to_tab = {}
    tabs = pipeline.get("tabs", [])
    if isinstance(tabs, list):
        for tab in tabs:
            if not isinstance(tab, dict):
                continue
            tab_id = tab.get("id")
            output = tab.get("output")
            output_id = output.get("result_id") if isinstance(output, dict) else None
            if isinstance(tab_id, str) and isinstance(output_id, str) and output_id:
                output_to_tab[output_id] = tab_id
    for step in steps:
        config = step.get("config", {})
        if not isinstance(config, dict):
            continue
        right_source_id = config.get("right_source") or config.get("rightDataSource")

        union_sources = config.get("sources", [])
        if isinstance(union_sources, str):
            union_sources = [union_sources]

        source_ids = ([right_source_id] if right_source_id else []) + union_sources

        for source_id in source_ids:
            if not source_id:
                continue
            if str(source_id) in cache:
                additional[str(source_id)] = cache[str(source_id)]
                continue
            if str(source_id) in output_to_tab:
                next_config = {
                    "source_type": DataSourceType.ANALYSIS.value,
                    "analysis_id": str(pipeline.get("analysis_id") or ""),
                    "analysis_tab_id": output_to_tab[str(source_id)],
                    "analysis_pipeline": pipeline,
                }
            else:
                raw = _step_source_payload(config, str(source_id))
                if not isinstance(raw, dict):
                    raise ValueError(f"Analysis pipeline missing datasource config for {source_id}")
                next_config = _resolve_pipeline_datasource(pipeline, raw)
                if DataSourceType.read(next_config.get("source_type"), default=None) == DataSourceType.ANALYSIS:
                    next_config = {**next_config, "analysis_pipeline": pipeline}
            additional[str(source_id)] = load_datasource(next_config)

    return additional


DatasourceHandler.SOURCE_LOADERS = {
    DataSourceType.FILE.value: DatasourceHandler._load_file,
    DataSourceType.DATABASE.value: DatasourceHandler._load_database,
    DatasourceLoadType.DUCKDB.value: DatasourceHandler._load_duckdb,
    DataSourceType.ICEBERG.value: DatasourceHandler._load_iceberg,
    DataSourceType.ANALYSIS.value: DatasourceHandler._load_analysis,
}


def load_datasource(config: dict) -> pl.LazyFrame:
    return DatasourceHandler()(pl.LazyFrame(), config)


async def load_datasource_async(config: dict) -> pl.LazyFrame:
    return await asyncio.to_thread(load_datasource, config)
