from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from contracts.analysis.pipeline_types import PipelineDefinition, PipelineTab
from contracts.analysis.step_types import STEP_TYPES, get_step_dependency_values
from contracts.datasource.models import DataSource
from contracts.datasource.source_types import DataSourceFileType, DataSourceType
from contracts.step_config_enums import (
    DeduplicateKeep,
    FilterLogic,
    FilterOperator,
    FilterValueType,
    GroupByAggregationFunction,
    JoinHow,
    PivotAggregateFunction,
)

from modules.analysis.step_schemas import FilterConfig
from modules.export.models import CodeExportFormat
from modules.export.utils import export_slug

_POLARS_CAST_MAP = {
    "Int64": "Int64",
    "Float64": "Float64",
    "Boolean": "Boolean",
    "String": "Utf8",
    "Utf8": "Utf8",
    "Date": "Date",
    "Datetime": "Datetime",
}

_SQL_CAST_MAP = {
    "Int64": "BIGINT",
    "Float64": "DOUBLE PRECISION",
    "Boolean": "BOOLEAN",
    "String": "TEXT",
    "Utf8": "TEXT",
    "Date": "DATE",
    "Datetime": "TIMESTAMP",
}


@dataclass(frozen=True)
class ExportSelection:
    ordered_tabs: list[PipelineTab]
    target_tab: PipelineTab
    tab_map: dict[str, PipelineTab]


CodeGenerator = Callable[[ExportSelection, dict[str, DataSource]], tuple[str, list[str]]]
_CODE_GENERATORS: dict[CodeExportFormat, CodeGenerator] = {}


def code_generator(format_name: CodeExportFormat) -> Callable[[CodeGenerator], CodeGenerator]:
    def register(generator: CodeGenerator) -> CodeGenerator:
        _CODE_GENERATORS[format_name] = generator
        return generator

    return register


def generate_code(format_name: CodeExportFormat, selection: ExportSelection, datasources_by_id: dict[str, DataSource]) -> tuple[str, list[str]]:
    try:
        generator = _CODE_GENERATORS[format_name]
    except KeyError as exc:
        raise ValueError(f"Unsupported export format '{format_name.value}'") from exc
    return generator(selection, datasources_by_id)


def _identifier(value: str) -> str:
    ident = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_")
    if not ident:
        ident = "item"
    if ident[0].isdigit():
        ident = f"v_{ident}"
    return ident


def _safe_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)


def _safe_py(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, (bool, int, float)) or value is None:
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_safe_py(item) for item in value) + "]"
    if isinstance(value, dict):
        pairs = ", ".join(f"{_safe_py(k)}: {_safe_py(v)}" for k, v in value.items())
        return "{" + pairs + "}"
    return json.dumps(str(value), ensure_ascii=True)


def _sql_quote(value: str) -> str:
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _tab_dependencies(tab: PipelineTab) -> set[str]:
    deps: set[str] = set()
    source_tab_id = tab.datasource.analysis_tab_id
    if isinstance(source_tab_id, str) and source_tab_id:
        deps.add(source_tab_id)
    for step in tab.steps:
        deps.update(get_step_dependency_values(step.type, step.config))
    return deps


def select_tabs(pipeline: PipelineDefinition, tab_id: str | None) -> ExportSelection:
    if not pipeline.tabs:
        raise ValueError("Analysis has no tabs to export")

    tab_map = {tab.id: tab for tab in pipeline.tabs}
    order_index = {tab.id: idx for idx, tab in enumerate(pipeline.tabs)}

    if tab_id:
        target_tab = tab_map.get(tab_id)
        if target_tab is None:
            raise ValueError(f"Tab {tab_id} not found")
        required: set[str] = set()
        stack = [tab_id]
        while stack:
            current = stack.pop()
            if current in required:
                continue
            required.add(current)
            current_tab = tab_map.get(current)
            if current_tab is None:
                continue
            for dep in _tab_dependencies(current_tab):
                if dep in tab_map:
                    stack.append(dep)
    else:
        required = set(tab_map.keys())
        target_tab = pipeline.tabs[-1]

    in_degree = {tid: 0 for tid in required}
    graph: dict[str, list[str]] = {tid: [] for tid in required}
    for tid in required:
        tab = tab_map[tid]
        for dep in _tab_dependencies(tab):
            if dep not in required:
                continue
            graph[dep].append(tid)
            in_degree[tid] += 1

    queue = deque(
        sorted(
            (tid for tid, deg in in_degree.items() if deg == 0),
            key=lambda tid: order_index[tid],
        )
    )
    ordered_ids: list[str] = []
    while queue:
        tid = queue.popleft()
        ordered_ids.append(tid)
        for child in sorted(graph[tid], key=lambda cid: order_index[cid]):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    if len(ordered_ids) < len(required):
        missing = sorted(required - set(ordered_ids), key=lambda tid: order_index[tid])
        ordered_ids.extend(missing)

    ordered_tabs = [tab_map[tid] for tid in ordered_ids]
    return ExportSelection(ordered_tabs=ordered_tabs, target_tab=target_tab, tab_map=tab_map)


def _datasource_path_constant(
    tab: PipelineTab,
    datasource: DataSource | None,
    used: set[str],
) -> tuple[str, str]:
    base = _identifier(f"source_{export_slug(tab.name, fallback='item')}_path").upper()
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    if datasource is not None:
        replacement = _identifier(f"replace_with_{datasource.name}_path").upper()
    else:
        replacement = _identifier(f"replace_with_datasource_{tab.datasource.id}_path").upper()
    return candidate, replacement


def _scan_expression(datasource: DataSource | None, path_const: str) -> tuple[str, str | None]:
    if datasource is None:
        return (
            f"pl.scan_parquet({path_const})",
            "datasource metadata is missing; defaulting to parquet scanner",
        )
    config = datasource.config if isinstance(datasource.config, dict) else {}
    source_type = DataSourceType.read(datasource.source_type, default=None)
    file_type = DataSourceFileType.read(config.get("file_type"), default=None)
    if source_type == DataSourceType.FILE:
        match file_type:
            case DataSourceFileType.CSV:
                return f"pl.scan_csv({path_const})", None
            case DataSourceFileType.PARQUET:
                return f"pl.scan_parquet({path_const})", None
            case DataSourceFileType.JSON:
                return f"pl.read_json({path_const}).lazy()", None
            case DataSourceFileType.NDJSON:
                return f"pl.scan_ndjson({path_const})", None
            case DataSourceFileType.EXCEL:
                return f"pl.read_excel({path_const}).lazy()", None
            case _:
                return (
                    f"pl.scan_parquet({path_const})",
                    f"unsupported file_type '{config.get('file_type') or 'unknown'}'; defaulting to parquet scanner",
                )
    return (
        f"pl.scan_parquet({path_const})",
        f"source type '{datasource.source_type}' is not directly exportable; replace scanner with your own loader",
    )


def _polars_filter_expr(condition: dict[str, Any]) -> str | None:
    column = condition.get("column")
    if not isinstance(column, str) or not column:
        return None
    operator = FilterOperator.read(condition.get("operator"), default=FilterOperator.EQUAL)
    if operator is None:
        return None
    value_type = FilterValueType.read(condition.get("value_type"), default=FilterValueType.STRING)
    compare_column = condition.get("compare_column")
    column_expr = f"pl.col({json.dumps(column)})"

    if operator == FilterOperator.IS_NULL:
        return f"{column_expr}.is_null()"
    if operator == FilterOperator.IS_NOT_NULL:
        return f"{column_expr}.is_not_null()"

    if value_type == FilterValueType.COLUMN and isinstance(compare_column, str) and compare_column:
        rhs = f"pl.col({json.dumps(compare_column)})"
    else:
        rhs = _safe_py(condition.get("value"))

    if actual := operator.polars_binary_token:
        return f"{column_expr} {actual} {rhs}"
    if operator == FilterOperator.CONTAINS:
        return f"{column_expr}.str.contains({rhs}, literal=True)"
    if operator == FilterOperator.NOT_CONTAINS:
        return f"~{column_expr}.str.contains({rhs}, literal=True)"
    if operator == FilterOperator.STARTS_WITH:
        return f"{column_expr}.str.starts_with({rhs})"
    if operator == FilterOperator.ENDS_WITH:
        return f"{column_expr}.str.ends_with({rhs})"
    if operator == FilterOperator.IN:
        return f"{column_expr}.is_in({rhs})"
    if operator == FilterOperator.NOT_IN:
        return f"~{column_expr}.is_in({rhs})"
    return None


def _sql_filter_expr(condition: dict[str, Any]) -> str | None:
    column = condition.get("column")
    if not isinstance(column, str) or not column:
        return None
    operator = FilterOperator.read(condition.get("operator"), default=FilterOperator.EQUAL)
    if operator is None:
        return None
    value_type = FilterValueType.read(condition.get("value_type"), default=FilterValueType.STRING)
    compare_column = condition.get("compare_column")
    lhs = _sql_quote(column)

    if operator == FilterOperator.IS_NULL:
        return f"{lhs} IS NULL"
    if operator == FilterOperator.IS_NOT_NULL:
        return f"{lhs} IS NOT NULL"

    if value_type == FilterValueType.COLUMN and isinstance(compare_column, str) and compare_column:
        rhs = _sql_quote(compare_column)
    else:
        value = condition.get("value")
        if operator.is_membership:
            items = value if isinstance(value, list) else [value]
            rhs = "(" + ", ".join(_sql_literal(item) for item in items) + ")"
        else:
            rhs = _sql_literal(value)

    if actual := operator.sql_binary_token:
        return f"{lhs} {actual} {rhs}"
    if operator == FilterOperator.CONTAINS:
        return f"{lhs} LIKE ('%' || {rhs} || '%')"
    if operator == FilterOperator.NOT_CONTAINS:
        return f"{lhs} NOT LIKE ('%' || {rhs} || '%')"
    if operator == FilterOperator.STARTS_WITH:
        return f"{lhs} LIKE ({rhs} || '%')"
    if operator == FilterOperator.ENDS_WITH:
        return f"{lhs} LIKE ('%' || {rhs})"
    if operator == FilterOperator.IN:
        return f"{lhs} IN {rhs}"
    if operator == FilterOperator.NOT_IN:
        return f"{lhs} NOT IN {rhs}"
    return None


def _polars_group_agg_expr(aggregation: dict[str, Any]) -> str | None:
    column = aggregation.get("column")
    function_raw = aggregation.get("function")
    alias = aggregation.get("alias")
    if not isinstance(column, str) or not column:
        return None
    if not isinstance(function_raw, (str, GroupByAggregationFunction)):
        return None
    try:
        function = GroupByAggregationFunction.require(function_raw)
    except ValueError:
        return None
    alias_name = alias if isinstance(alias, str) and alias else function.default_alias(column)
    return function.render_polars_export(f"pl.col({json.dumps(column)})", json.dumps(alias_name))


def _sql_group_agg_expr(aggregation: dict[str, Any]) -> str | None:
    column = aggregation.get("column")
    function_raw = aggregation.get("function")
    alias = aggregation.get("alias")
    if not isinstance(column, str) or not column:
        return None
    if not isinstance(function_raw, (str, GroupByAggregationFunction)):
        return None
    try:
        function = GroupByAggregationFunction.require(function_raw)
    except ValueError:
        return None
    alias_name = alias if isinstance(alias, str) and alias else function.default_alias(column)
    return function.render_sql_export(_sql_quote(column), _sql_quote(alias_name))


@dataclass(slots=True)
class PolarsStepRenderContext:
    tab: PipelineTab
    step_type: str
    config: dict[str, Any]
    current_var: str
    next_var: str
    tab_last_var: dict[str, str]
    lines: list[str]
    warnings: list[str]

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def assign(self, expression: str) -> str:
        self.lines.append(f"{self.next_var} = {expression}")
        return self.next_var

    def alias_current(self, *, warning: str | None = None) -> str:
        if warning is not None:
            self.warn(warning)
        return self.assign(self.current_var)

    def keep_current(self, *, warning: str | None = None) -> str:
        if warning is not None:
            self.warn(warning)
        return self.current_var


@dataclass(frozen=True, slots=True)
class SqlStepRenderResult:
    body: str
    comments: tuple[str, ...] = ()


@dataclass(slots=True)
class SqlStepRenderContext:
    tab: PipelineTab
    step_type: str
    config: dict[str, Any]
    current_cte: str
    tab_final_cte: dict[str, str]
    warnings: list[str]

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def select_all(self) -> str:
        return f"SELECT * FROM {self.current_cte}"

    def result(self, body: str | None = None, *, comments: tuple[str, ...] = (), warning: str | None = None) -> SqlStepRenderResult:
        if warning is not None:
            self.warn(warning)
        return SqlStepRenderResult(body=body or self.select_all(), comments=comments)


PolarsStepRenderer = Callable[[PolarsStepRenderContext], str]
SqlStepRenderer = Callable[[SqlStepRenderContext], SqlStepRenderResult]
POLARS_STEP_RENDERERS: dict[str, PolarsStepRenderer] = {}
SQL_STEP_RENDERERS: dict[str, SqlStepRenderer] = {}


def polars_step_renderer(*step_types: str) -> Callable[[PolarsStepRenderer], PolarsStepRenderer]:
    def register(renderer: PolarsStepRenderer) -> PolarsStepRenderer:
        for step_type in step_types:
            POLARS_STEP_RENDERERS[step_type] = renderer
        return renderer

    return register


def sql_step_renderer(*step_types: str) -> Callable[[SqlStepRenderer], SqlStepRenderer]:
    def register(renderer: SqlStepRenderer) -> SqlStepRenderer:
        for step_type in step_types:
            SQL_STEP_RENDERERS[step_type] = renderer
        return renderer

    return register


@polars_step_renderer(STEP_TYPES.filter.value)
def render_polars_filter(context: PolarsStepRenderContext) -> str:
    conditions = [condition.model_dump(mode="json", exclude_none=True) for condition in FilterConfig.model_validate(context.config).conditions]
    logic = FilterLogic.read(str(context.config.get("logic", FilterLogic.AND.value)).upper(), default=FilterLogic.AND)
    exprs = [expr for cond in conditions if isinstance(cond, dict) if (expr := _polars_filter_expr(cond))]
    if not exprs:
        return context.alias_current(warning=f"Filter step in tab '{context.tab.name}' has no valid conditions")
    joiner = " & " if logic == FilterLogic.AND else " | "
    return context.assign(f"{context.current_var}.filter({joiner.join(exprs)})")


@polars_step_renderer(STEP_TYPES.select.value)
def render_polars_select(context: PolarsStepRenderContext) -> str:
    columns = context.config.get("columns")
    cast_map = context.config.get("cast_map")
    if isinstance(columns, list) and columns:
        quoted = "[" + ", ".join(json.dumps(col) for col in columns if isinstance(col, str)) + "]"
        current = context.assign(f"{context.current_var}.select({quoted})")
    else:
        current = context.alias_current(warning=f"Select step in tab '{context.tab.name}' has no columns and was treated as pass-through")
    if isinstance(cast_map, dict) and cast_map:
        casts: list[str] = []
        for column, dtype in cast_map.items():
            if not isinstance(column, str):
                continue
            mapped = _POLARS_CAST_MAP.get(str(dtype))
            if not mapped:
                context.warn(f"Select step in tab '{context.tab.name}' has unsupported cast type '{dtype}' for '{column}'")
                continue
            casts.append(f"pl.col({json.dumps(column)}).cast(pl.{mapped}).alias({json.dumps(column)})")
        if casts:
            cast_expr = "[" + ", ".join(casts) + "]"
            context.lines.append(f"{current} = {current}.with_columns({cast_expr})")
    return current


@polars_step_renderer(STEP_TYPES.drop.value)
def render_polars_drop(context: PolarsStepRenderContext) -> str:
    columns = context.config.get("columns")
    if not isinstance(columns, list) or not columns:
        return context.alias_current()
    quoted = "[" + ", ".join(json.dumps(col) for col in columns if isinstance(col, str)) + "]"
    return context.assign(f"{context.current_var}.drop({quoted})")


@polars_step_renderer(STEP_TYPES.sort.value)
def render_polars_sort(context: PolarsStepRenderContext) -> str:
    columns = context.config.get("columns")
    descending = context.config.get("descending")
    if not isinstance(columns, list) or not columns:
        return context.alias_current()
    cols = "[" + ", ".join(json.dumps(col) for col in columns if isinstance(col, str)) + "]"
    if isinstance(descending, list) and descending:
        desc = "[" + ", ".join("True" if bool(item) else "False" for item in descending) + "]"
        return context.assign(f"{context.current_var}.sort({cols}, descending={desc})")
    if isinstance(descending, bool):
        return context.assign(f"{context.current_var}.sort({cols}, descending={'True' if descending else 'False'})")
    return context.assign(f"{context.current_var}.sort({cols})")


@polars_step_renderer(STEP_TYPES.rename.value)
def render_polars_rename(context: PolarsStepRenderContext) -> str:
    mapping = context.config.get("column_mapping")
    if not isinstance(mapping, dict) or not mapping:
        return context.alias_current()
    return context.assign(f"{context.current_var}.rename({_safe_py(mapping)})")


@polars_step_renderer(STEP_TYPES.groupby.value)
def render_polars_groupby(context: PolarsStepRenderContext) -> str:
    group_by = context.config.get("group_by")
    aggregations = context.config.get("aggregations")
    agg_exprs = [expr for agg in aggregations if isinstance(agg, dict) if (expr := _polars_group_agg_expr(agg))] if isinstance(aggregations, list) else []
    if not (isinstance(group_by, list) and group_by and agg_exprs):
        return context.alias_current(warning=f"GroupBy step in tab '{context.tab.name}' is missing group_by or aggregations")
    group_cols = "[" + ", ".join(json.dumps(col) for col in group_by if isinstance(col, str)) + "]"
    agg_list = "[" + ", ".join(agg_exprs) + "]"
    return context.assign(f"{context.current_var}.group_by({group_cols}).agg({agg_list})")


@polars_step_renderer(STEP_TYPES.join.value)
def render_polars_join(context: PolarsStepRenderContext) -> str:
    right_source = context.config.get("right_source")
    join_columns = context.config.get("join_columns")
    raw_how = context.config.get("how")
    try:
        how = JoinHow.INNER if raw_how is None else JoinHow.require(raw_how)
    except ValueError:
        return context.alias_current(warning=f"Join step in tab '{context.tab.name}' has unsupported join type '{raw_how}'")
    suffix = str(context.config.get("suffix", "_right"))
    right_var = context.tab_last_var.get(str(right_source)) if isinstance(right_source, str) else None
    if right_var is None:
        return context.alias_current(warning=f"Join step in tab '{context.tab.name}' could not resolve right source '{right_source}'")
    if not how.requires_join_keys:
        return context.assign(f"{context.current_var}.join({right_var}, how={json.dumps(how.polars_how)})")
    if not (isinstance(join_columns, list) and join_columns):
        return context.alias_current(warning=f"Join step in tab '{context.tab.name}' has no join column mappings")
    left_cols = [
        pair.get("left_column") for pair in join_columns if isinstance(pair, dict) and isinstance(pair.get("left_column"), str) and pair.get("left_column")
    ]
    right_cols = [
        pair.get("right_column") for pair in join_columns if isinstance(pair, dict) and isinstance(pair.get("right_column"), str) and pair.get("right_column")
    ]
    if not (left_cols and right_cols):
        return context.alias_current(warning=f"Join step in tab '{context.tab.name}' has empty join column mappings")
    left_list = "[" + ", ".join(json.dumps(col) for col in left_cols) + "]"
    right_list = "[" + ", ".join(json.dumps(col) for col in right_cols) + "]"
    return context.assign(
        f"{context.current_var}.join({right_var}, left_on={left_list}, right_on={right_list}, how={json.dumps(how.polars_how)}, suffix={json.dumps(suffix)})",
    )


@polars_step_renderer(STEP_TYPES.expression.value)
def render_polars_expression(context: PolarsStepRenderContext) -> str:
    expression = context.config.get("expression")
    column_name = context.config.get("column_name")
    if not (isinstance(expression, str) and expression.strip() and isinstance(column_name, str) and column_name):
        return context.alias_current(warning=f"Expression step in tab '{context.tab.name}' is missing expression or column_name")
    return context.assign(f"{context.current_var}.with_columns(({expression}).alias({json.dumps(column_name)}))")


@polars_step_renderer(STEP_TYPES.with_columns.value)
def render_polars_with_columns(context: PolarsStepRenderContext) -> str:
    expressions = context.config.get("expressions")
    rendered: list[str] = []
    if isinstance(expressions, list):
        for expression in expressions:
            if not isinstance(expression, dict):
                continue
            name = expression.get("name")
            expr_type = expression.get("type")
            if not isinstance(name, str) or not name:
                continue
            if expr_type == "literal":
                rendered.append(f"pl.lit({_safe_py(expression.get('value'))}).alias({json.dumps(name)})")
            elif expr_type == "column" and isinstance(expression.get("column"), str):
                rendered.append(f"pl.col({json.dumps(expression['column'])}).alias({json.dumps(name)})")
            elif expr_type == "udf":
                context.warn(f"With Columns UDF expression '{name}' in tab '{context.tab.name}' is not exportable as pure Polars and was skipped")
            else:
                context.warn(f"With Columns expression '{name}' in tab '{context.tab.name}' has unsupported type '{expr_type}'")
    if not rendered:
        return context.alias_current()
    return context.assign(f"{context.current_var}.with_columns([{', '.join(rendered)}])")


@polars_step_renderer(STEP_TYPES.pivot.value)
def render_polars_pivot(context: PolarsStepRenderContext) -> str:
    on_col = context.config.get("columns")
    values = context.config.get("values")
    index = context.config.get("index")
    aggregate_function = str(context.config.get("aggregate_function", PivotAggregateFunction.FIRST.value))
    if not (isinstance(on_col, str) and on_col):
        return context.alias_current(warning=f"Pivot step in tab '{context.tab.name}' is missing columns")
    index_expr = "[" + ", ".join(json.dumps(col) for col in index if isinstance(col, str)) + "]" if isinstance(index, list) else "[]"
    values_expr = json.dumps(values) if isinstance(values, str) and values else "None"
    return context.assign(
        f"{context.current_var}.pivot(on={json.dumps(on_col)}, values={values_expr}, index={index_expr}, aggregate_function={json.dumps(aggregate_function)})",
    )


@polars_step_renderer(STEP_TYPES.unpivot.value)
def render_polars_unpivot(context: PolarsStepRenderContext) -> str:
    id_vars = context.config.get("id_vars")
    value_vars = context.config.get("value_vars")
    variable_name = str(context.config.get("variable_name", "variable"))
    value_name = str(context.config.get("value_name", "value"))
    if not (isinstance(value_vars, list) and value_vars):
        return context.alias_current(warning=f"Unpivot step in tab '{context.tab.name}' is missing value_vars")
    ids_expr = "[" + ", ".join(json.dumps(col) for col in id_vars if isinstance(col, str)) + "]" if isinstance(id_vars, list) else "[]"
    value_expr = "[" + ", ".join(json.dumps(col) for col in value_vars if isinstance(col, str)) + "]"
    return context.assign(
        f"{context.current_var}.unpivot(on={value_expr}, index={ids_expr}, variable_name={json.dumps(variable_name)}, value_name={json.dumps(value_name)})",
    )


@polars_step_renderer(STEP_TYPES.deduplicate.value)
def render_polars_deduplicate(context: PolarsStepRenderContext) -> str:
    subset = context.config.get("subset")
    keep = str(context.config.get("keep", DeduplicateKeep.FIRST.value))
    if isinstance(subset, list) and subset:
        subset_expr = "[" + ", ".join(json.dumps(col) for col in subset if isinstance(col, str)) + "]"
        return context.assign(f"{context.current_var}.unique(subset={subset_expr}, keep={json.dumps(keep)})")
    return context.assign(f"{context.current_var}.unique(keep={json.dumps(keep)})")


@polars_step_renderer(STEP_TYPES.sample.value)
def render_polars_sample(context: PolarsStepRenderContext) -> str:
    fraction = context.config.get("fraction", 0.5)
    seed = context.config.get("seed")
    if isinstance(seed, int):
        return context.assign(f"{context.current_var}.sample(fraction={_safe_py(fraction)}, seed={seed})")
    return context.assign(f"{context.current_var}.sample(fraction={_safe_py(fraction)})")


@polars_step_renderer(STEP_TYPES.limit.value)
def render_polars_limit(context: PolarsStepRenderContext) -> str:
    n = context.config.get("n", 100)
    return context.assign(f"{context.current_var}.limit({int(n) if isinstance(n, int) else 100})")


@polars_step_renderer(STEP_TYPES.view.value)
def render_polars_view(context: PolarsStepRenderContext) -> str:
    context.lines.append(f"{context.current_var}.show(limit=5)")
    return context.current_var


@polars_step_renderer(
    STEP_TYPES.download.value,
    STEP_TYPES.export.value,
    STEP_TYPES.chart.value,
    STEP_TYPES.plot_bar.value,
    STEP_TYPES.plot_horizontal_bar.value,
    STEP_TYPES.plot_area.value,
    STEP_TYPES.plot_heatgrid.value,
    STEP_TYPES.plot_histogram.value,
    STEP_TYPES.plot_scatter.value,
    STEP_TYPES.plot_line.value,
    STEP_TYPES.plot_pie.value,
    STEP_TYPES.plot_boxplot.value,
)
def render_polars_passthrough(context: PolarsStepRenderContext) -> str:
    return context.alias_current()


def render_unsupported_polars_step(context: PolarsStepRenderContext) -> str:
    context.lines.append(f'# Step type "{context.step_type}" is not directly exportable; keeping previous frame')
    return context.alias_current(
        warning=f'Step "{context.step_type}" in tab "{context.tab.name}" is not fully exportable to pure Polars. Original config: {_safe_json(context.config)}',
    )


@sql_step_renderer(STEP_TYPES.filter.value)
def render_sql_filter(context: SqlStepRenderContext) -> SqlStepRenderResult:
    conditions = [condition.model_dump(mode="json", exclude_none=True) for condition in FilterConfig.model_validate(context.config).conditions]
    logic = FilterLogic.read(str(context.config.get("logic", FilterLogic.AND.value)).upper(), default=FilterLogic.AND)
    exprs = [expr for cond in conditions if isinstance(cond, dict) if (expr := _sql_filter_expr(cond))]
    if not exprs:
        return context.result(warning=f"Filter step in tab '{context.tab.name}' has no valid SQL conditions")
    joiner = " AND " if logic == FilterLogic.AND else " OR "
    return context.result(f"SELECT * FROM {context.current_cte} WHERE " + joiner.join(exprs))


@sql_step_renderer(STEP_TYPES.select.value)
def render_sql_select(context: SqlStepRenderContext) -> SqlStepRenderResult:
    columns = context.config.get("columns")
    cast_map = context.config.get("cast_map")
    if not (isinstance(columns, list) and columns):
        return context.result(warning=f"Select step in tab '{context.tab.name}' has no columns and was treated as pass-through")
    rendered: list[str] = []
    for column in columns:
        if not isinstance(column, str):
            continue
        cast_type = cast_map.get(column) if isinstance(cast_map, dict) else None
        sql_type = _SQL_CAST_MAP.get(str(cast_type)) if cast_type else None
        if sql_type:
            rendered.append(f"CAST({_sql_quote(column)} AS {sql_type}) AS {_sql_quote(column)}")
        else:
            rendered.append(_sql_quote(column))
    return context.result(f"SELECT {', '.join(rendered)} FROM {context.current_cte}") if rendered else context.result()


@sql_step_renderer(STEP_TYPES.sort.value)
def render_sql_sort(context: SqlStepRenderContext) -> SqlStepRenderResult:
    columns = context.config.get("columns")
    descending = context.config.get("descending")
    if not (isinstance(columns, list) and columns):
        return context.result()
    clauses: list[str] = []
    for idx, column in enumerate(columns):
        if not isinstance(column, str):
            continue
        desc = False
        if isinstance(descending, list):
            desc = bool(descending[idx]) if idx < len(descending) else False
        elif isinstance(descending, bool):
            desc = descending
        clauses.append(f"{_sql_quote(column)} {'DESC' if desc else 'ASC'}")
    return context.result(f"SELECT * FROM {context.current_cte} ORDER BY " + ", ".join(clauses)) if clauses else context.result()


@sql_step_renderer(STEP_TYPES.groupby.value)
def render_sql_groupby(context: SqlStepRenderContext) -> SqlStepRenderResult:
    group_by = context.config.get("group_by")
    aggregations = context.config.get("aggregations")
    if not (isinstance(group_by, list) and group_by and isinstance(aggregations, list) and aggregations):
        return context.result(warning=f"GroupBy step in tab '{context.tab.name}' is missing group_by or aggregations")
    group_cols = [_sql_quote(col) for col in group_by if isinstance(col, str)]
    agg_exprs = [expr for agg in aggregations if isinstance(agg, dict) if (expr := _sql_group_agg_expr(agg))]
    if not (group_cols and agg_exprs):
        return context.result(warning=f"GroupBy step in tab '{context.tab.name}' has unsupported aggregation functions")
    return context.result("SELECT " + ", ".join(group_cols + agg_exprs) + f" FROM {context.current_cte} GROUP BY " + ", ".join(group_cols))


@sql_step_renderer(STEP_TYPES.join.value)
def render_sql_join(context: SqlStepRenderContext) -> SqlStepRenderResult:
    right_source = context.config.get("right_source")
    join_columns = context.config.get("join_columns")
    raw_how = context.config.get("how")
    try:
        how = JoinHow.INNER if raw_how is None else JoinHow.require(raw_how)
    except ValueError:
        return context.result(warning=f"Join step in tab '{context.tab.name}' has unsupported join type '{raw_how}'")
    right_columns = context.config.get("right_columns")
    right_cte = context.tab_final_cte.get(str(right_source)) if isinstance(right_source, str) else None
    if right_cte is None:
        return context.result(warning=f"Join step in tab '{context.tab.name}' could not resolve right source '{right_source}'")
    if not how.requires_join_keys:
        return context.result(f"SELECT l.*, r.* FROM {context.current_cte} AS l {how.sql_join_type} {right_cte} AS r")
    if not (isinstance(join_columns, list) and join_columns):
        return context.result(warning=f"Join step in tab '{context.tab.name}' has no join column mappings")
    on_parts: list[str] = []
    for pair in join_columns:
        if not isinstance(pair, dict):
            continue
        left_col = pair.get("left_column")
        right_col = pair.get("right_column")
        if isinstance(left_col, str) and isinstance(right_col, str) and left_col and right_col:
            on_parts.append(f"l.{_sql_quote(left_col)} = r.{_sql_quote(right_col)}")
    if not on_parts:
        return context.result(warning=f"Join step in tab '{context.tab.name}' has empty join column mappings")
    if isinstance(right_columns, list) and right_columns:
        right_select = ", ".join(f"r.{_sql_quote(col)} AS {_sql_quote(col)}" for col in right_columns if isinstance(col, str))
        select_clause = f"l.*, {right_select}" if right_select else "l.*, r.*"
    else:
        select_clause = "l.*, r.*"
    body = f"SELECT {select_clause} FROM {context.current_cte} AS l {how.sql_join_type} {right_cte} AS r ON " + " AND ".join(on_parts)
    return context.result(body)


@sql_step_renderer(STEP_TYPES.expression.value)
def render_sql_expression(context: SqlStepRenderContext) -> SqlStepRenderResult:
    expression = context.config.get("expression")
    column_name = context.config.get("column_name")
    if not (isinstance(expression, str) and expression.strip() and isinstance(column_name, str) and column_name):
        return context.result(warning=f"Expression step in tab '{context.tab.name}' is missing expression or column_name")
    return context.result(f"SELECT *, ({expression}) AS {_sql_quote(column_name)} FROM {context.current_cte}")


@sql_step_renderer(STEP_TYPES.limit.value)
def render_sql_limit(context: SqlStepRenderContext) -> SqlStepRenderResult:
    n = context.config.get("n", 100)
    n_value = int(n) if isinstance(n, int) else 100
    return context.result(f"SELECT * FROM {context.current_cte} LIMIT {n_value}")


@sql_step_renderer(STEP_TYPES.deduplicate.value)
def render_sql_deduplicate(context: SqlStepRenderContext) -> SqlStepRenderResult:
    subset = context.config.get("subset")
    keep = str(context.config.get("keep", DeduplicateKeep.FIRST.value))
    if isinstance(subset, list) and subset and keep == DeduplicateKeep.FIRST.value:
        cols = ", ".join(_sql_quote(col) for col in subset if isinstance(col, str))
        return context.result(f"SELECT DISTINCT ON ({cols}) * FROM {context.current_cte} ORDER BY {cols}")
    return context.result(
        comments=(
            f'-- WARNING: step "{context.step_type}" in tab "{context.tab.name}" cannot be represented exactly in SQL',
            f"-- Original config: {_safe_json(context.config)}",
        )
    )


@sql_step_renderer(STEP_TYPES.view.value, STEP_TYPES.download.value, STEP_TYPES.export.value)
def render_sql_passthrough(context: SqlStepRenderContext) -> SqlStepRenderResult:
    return context.result()


def render_unsupported_sql_step(context: SqlStepRenderContext) -> SqlStepRenderResult:
    context.warn(
        f'Step "{context.step_type}" in tab "{context.tab.name}" is not fully exportable to SQL. Original config: {_safe_json(context.config)}',
    )
    return context.result(
        comments=(
            f'-- WARNING: step "{context.step_type}" in tab "{context.tab.name}" is not directly translatable to SQL',
            f"-- Original config: {_safe_json(context.config)}",
        )
    )


@code_generator(CodeExportFormat.POLARS)
def generate_polars_code(
    selection: ExportSelection,
    datasources_by_id: dict[str, DataSource],
    *,
    include_header: bool = True,
) -> tuple[str, list[str]]:
    lines: list[str] = []
    warnings: list[str] = []

    def warn(message: str) -> None:
        if message not in warnings:
            warnings.append(message)

    if include_header:
        lines.extend(
            [
                "# Generated by Data-Forge code export (Polars)",
                "# Replace SOURCE_*_PATH placeholders with your local data paths.",
                "import polars as pl",
                "",
            ],
        )

    source_constants: dict[str, str] = {}
    used_constants: set[str] = set()
    for tab in selection.ordered_tabs:
        source_tab_id = tab.datasource.analysis_tab_id
        if isinstance(source_tab_id, str) and source_tab_id:
            continue
        datasource = datasources_by_id.get(tab.datasource.id)
        const_name, replacement = _datasource_path_constant(tab, datasource, used_constants)
        source_constants[tab.id] = const_name
        lines.append(f"{const_name} = {json.dumps(replacement)}")
    if source_constants:
        lines.append("")

    tab_last_var: dict[str, str] = {}
    for tab_index, tab in enumerate(selection.ordered_tabs, start=1):
        tab_slug = _identifier(f"tab_{tab_index}_{export_slug(tab.name, fallback='item')}")
        source_var = f"{tab_slug}_source"

        lines.append(f"# ---- Tab: {tab.name} ----")
        source_tab_id = tab.datasource.analysis_tab_id
        if isinstance(source_tab_id, str) and source_tab_id:
            parent_var = tab_last_var.get(source_tab_id)
            if parent_var:
                lines.append(f"{source_var} = {parent_var}")
            else:
                lines.append(f"{source_var} = pl.LazyFrame()")
                warn(f"Tab '{tab.name}' depends on missing tab '{source_tab_id}'")
        else:
            datasource = datasources_by_id.get(tab.datasource.id)
            path_const = source_constants.get(tab.id)
            if path_const is None:
                lines.append(f"{source_var} = pl.LazyFrame()")
                warn(f"Tab '{tab.name}' is missing datasource placeholder metadata")
            else:
                scan_expr, scan_warning = _scan_expression(datasource, path_const)
                lines.append(f"{source_var} = {scan_expr}")
                if scan_warning:
                    warn(f"Tab '{tab.name}': {scan_warning}")

        current_var = source_var
        for step_index, step in enumerate(tab.steps, start=1):
            next_var = f"{tab_slug}_step_{step_index}"
            lines.append(f"# Step {step_index}: {step.type}")
            context = PolarsStepRenderContext(
                tab=tab,
                step_type=step.type,
                config=step.config if isinstance(step.config, dict) else {},
                current_var=current_var,
                next_var=next_var,
                tab_last_var=tab_last_var,
                lines=lines,
                warnings=warnings,
            )
            renderer = POLARS_STEP_RENDERERS.get(step.type, render_unsupported_polars_step)
            current_var = renderer(context)

        tab_last_var[tab.id] = current_var
        lines.append(f"{tab_slug}_result = {current_var}")
        lines.append("")

    target_var = tab_last_var.get(selection.target_tab.id)
    if target_var:
        lines.append(f"result = {target_var}.collect()")
        lines.append("print(result)")
    else:
        lines.append("result = pl.DataFrame()")
        lines.append("print(result)")
        warn(f"Could not resolve target tab '{selection.target_tab.name}' for final collect")

    return "\n".join(lines).strip() + "\n", warnings


@code_generator(CodeExportFormat.SQL)
def generate_sql_code(
    selection: ExportSelection,
    datasources_by_id: dict[str, DataSource],
) -> tuple[str, list[str]]:
    warnings: list[str] = []

    def warn(message: str) -> None:
        if message not in warnings:
            warnings.append(message)

    source_tables: dict[str, str] = {}
    used_table_names: set[str] = set()
    for tab in selection.ordered_tabs:
        source_tab_id = tab.datasource.analysis_tab_id
        if isinstance(source_tab_id, str) and source_tab_id:
            continue
        datasource = datasources_by_id.get(tab.datasource.id)
        base = _identifier(export_slug(datasource.name if datasource else tab.name, fallback="item"))
        table_name = f"{base}_table"
        suffix = 2
        while table_name in used_table_names:
            table_name = f"{base}_table_{suffix}"
            suffix += 1
        used_table_names.add(table_name)
        source_tables[tab.id] = table_name

    header_lines = [
        "-- Generated by Data-Forge code export (SQL)",
        "-- PostgreSQL-compatible SQL (DuckDB-compatible for most clauses).",
        "-- Replace placeholder table names below with real table/view names.",
    ]
    for tab in selection.ordered_tabs:
        table_placeholder = source_tables.get(tab.id)
        if table_placeholder:
            datasource = datasources_by_id.get(tab.datasource.id)
            source_name = datasource.name if datasource else tab.datasource.id
            header_lines.append(f'-- {table_placeholder}: source "{source_name}"')
    header_lines.append("")

    ctes: list[str] = []
    tab_final_cte: dict[str, str] = {}

    for tab_index, tab in enumerate(selection.ordered_tabs, start=1):
        tab_alias = _identifier(f"tab_{tab_index}_{export_slug(tab.name, fallback='item')}")
        source_cte = f"{tab_alias}_source"
        source_tab_id = tab.datasource.analysis_tab_id
        if isinstance(source_tab_id, str) and source_tab_id:
            upstream_cte = tab_final_cte.get(source_tab_id)
            if upstream_cte:
                source_from = upstream_cte
            else:
                source_from = "(SELECT NULL WHERE FALSE)"
                warn(f"Tab '{tab.name}' depends on missing tab '{source_tab_id}'")
        else:
            source_from = source_tables.get(tab.id, "(SELECT NULL WHERE FALSE)")
            if source_from == "(SELECT NULL WHERE FALSE)":
                warn(f"Tab '{tab.name}' is missing datasource metadata for SQL export")

        ctes.append(f"{source_cte} AS (\n    SELECT * FROM {source_from}\n)")
        current_cte = source_cte

        for step_index, step in enumerate(tab.steps, start=1):
            step_cte = f"{tab_alias}_step_{step_index}"
            context = SqlStepRenderContext(
                tab=tab,
                step_type=step.type,
                config=step.config if isinstance(step.config, dict) else {},
                current_cte=current_cte,
                tab_final_cte=tab_final_cte,
                warnings=warnings,
            )
            renderer = SQL_STEP_RENDERERS.get(step.type, render_unsupported_sql_step)
            rendered = renderer(context)

            step_cte_block = ""
            if rendered.comments:
                step_cte_block += "\n".join(rendered.comments) + "\n"
            step_cte_block += f"{step_cte} AS (\n    {rendered.body}\n)"
            ctes.append(step_cte_block)
            current_cte = step_cte

        tab_final_cte[tab.id] = current_cte

    final_cte = tab_final_cte.get(selection.target_tab.id)
    if final_cte is None:
        warn(f"Could not resolve target tab '{selection.target_tab.name}' for final SELECT")
        query = "SELECT 1 WHERE FALSE"
    else:
        query = f"SELECT * FROM {final_cte}"

    sql = "\n".join(header_lines) + "WITH\n" + ",\n".join(ctes) + "\n" + query + ";\n"
    return sql, warnings
