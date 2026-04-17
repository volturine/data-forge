from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass
from typing import Any

from modules.analysis.pipeline_types import PipelineDefinition, PipelineTab
from modules.datasource.models import DataSource

_FILTER_BINARY_OPERATORS = {'=', '==', '!=', '>', '<', '>=', '<='}
_FILTER_IN_OPERATORS = {'in', 'not_in'}

_POLARS_CAST_MAP = {
    'Int64': 'Int64',
    'Float64': 'Float64',
    'Boolean': 'Boolean',
    'String': 'Utf8',
    'Utf8': 'Utf8',
    'Date': 'Date',
    'Datetime': 'Datetime',
}

_SQL_CAST_MAP = {
    'Int64': 'BIGINT',
    'Float64': 'DOUBLE PRECISION',
    'Boolean': 'BOOLEAN',
    'String': 'TEXT',
    'Utf8': 'TEXT',
    'Date': 'DATE',
    'Datetime': 'TIMESTAMP',
}

_SQL_AGG_MAP = {
    'sum': 'SUM',
    'mean': 'AVG',
    'avg': 'AVG',
    'min': 'MIN',
    'max': 'MAX',
    'count': 'COUNT',
    'median': 'PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {expr})',
    'std': 'STDDEV_POP',
    'n_unique': 'COUNT_DISTINCT',
}


@dataclass(frozen=True)
class ExportSelection:
    ordered_tabs: list[PipelineTab]
    target_tab: PipelineTab
    tab_map: dict[str, PipelineTab]


def _slug(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r'[^a-z0-9]+', '_', lowered).strip('_')
    return slug or 'item'


def _identifier(value: str) -> str:
    ident = re.sub(r'[^a-zA-Z0-9_]+', '_', value).strip('_')
    if not ident:
        ident = 'item'
    if ident[0].isdigit():
        ident = f'v_{ident}'
    return ident


def _safe_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)


def _safe_py(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, (bool, int, float)) or value is None:
        return repr(value)
    if isinstance(value, list):
        return '[' + ', '.join(_safe_py(item) for item in value) + ']'
    if isinstance(value, dict):
        pairs = ', '.join(f'{_safe_py(k)}: {_safe_py(v)}' for k, v in value.items())
        return '{' + pairs + '}'
    return json.dumps(str(value), ensure_ascii=True)


def _sql_quote(value: str) -> str:
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


def _sql_literal(value: Any) -> str:
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
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
        if step.type == 'join':
            right_source = step.config.get('right_source')
            if isinstance(right_source, str) and right_source:
                deps.add(right_source)
        if step.type == 'union_by_name':
            raw_sources = step.config.get('sources')
            if isinstance(raw_sources, list):
                for source in raw_sources:
                    if isinstance(source, str) and source:
                        deps.add(source)
    return deps


def select_tabs(pipeline: PipelineDefinition, tab_id: str | None) -> ExportSelection:
    if not pipeline.tabs:
        raise ValueError('Analysis has no tabs to export')

    tab_map = {tab.id: tab for tab in pipeline.tabs}
    order_index = {tab.id: idx for idx, tab in enumerate(pipeline.tabs)}

    if tab_id:
        target_tab = tab_map.get(tab_id)
        if target_tab is None:
            raise ValueError(f'Tab {tab_id} not found')
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

    queue = deque(sorted((tid for tid, deg in in_degree.items() if deg == 0), key=lambda tid: order_index[tid]))
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
    base = _identifier(f'source_{_slug(tab.name)}_path').upper()
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f'{base}_{suffix}'
        suffix += 1
    used.add(candidate)
    if datasource is not None:
        replacement = _identifier(f'replace_with_{datasource.name}_path').upper()
    else:
        replacement = _identifier(f'replace_with_datasource_{tab.datasource.id}_path').upper()
    return candidate, replacement


def _scan_expression(datasource: DataSource | None, path_const: str) -> tuple[str, str | None]:
    if datasource is None:
        return f'pl.scan_parquet({path_const})', 'datasource metadata is missing; defaulting to parquet scanner'
    config = datasource.config if isinstance(datasource.config, dict) else {}
    source_type = datasource.source_type
    file_type = str(config.get('file_type', '')).lower()
    if source_type == 'file':
        if file_type == 'csv':
            return f'pl.scan_csv({path_const})', None
        if file_type == 'parquet':
            return f'pl.scan_parquet({path_const})', None
        if file_type in {'ndjson', 'jsonl'}:
            return f'pl.scan_ndjson({path_const})', None
        return (
            f'pl.scan_parquet({path_const})',
            f"unsupported file_type '{file_type or 'unknown'}'; defaulting to parquet scanner",
        )
    return (
        f'pl.scan_parquet({path_const})',
        f"source type '{source_type}' is not directly exportable; replace scanner with your own loader",
    )


def _normalize_filter_conditions(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_conditions = config.get('conditions')
    if isinstance(raw_conditions, list):
        normalized = [item for item in raw_conditions if isinstance(item, dict)]
        if normalized:
            return normalized

    legacy_column = config.get('column')
    if isinstance(legacy_column, str) and legacy_column:
        raise ValueError('legacy single-condition filter config is not supported; provide conditions[] explicitly')
    return []


def _polars_filter_expr(condition: dict[str, Any]) -> str | None:
    column = condition.get('column')
    if not isinstance(column, str) or not column:
        return None
    operator = str(condition.get('operator', '='))
    value_type = str(condition.get('value_type', 'string'))
    compare_column = condition.get('compare_column')
    column_expr = f'pl.col({json.dumps(column)})'

    if operator == 'is_null':
        return f'{column_expr}.is_null()'
    if operator == 'is_not_null':
        return f'{column_expr}.is_not_null()'

    if value_type == 'column' and isinstance(compare_column, str) and compare_column:
        rhs = f'pl.col({json.dumps(compare_column)})'
    else:
        rhs = _safe_py(condition.get('value'))

    if operator in {'=', '==', '!=', '>', '<', '>=', '<='}:
        actual = '==' if operator == '=' else operator
        return f'{column_expr} {actual} {rhs}'
    if operator == 'contains':
        return f'{column_expr}.str.contains({rhs}, literal=True)'
    if operator == 'not_contains':
        return f'~{column_expr}.str.contains({rhs}, literal=True)'
    if operator == 'starts_with':
        return f'{column_expr}.str.starts_with({rhs})'
    if operator == 'ends_with':
        return f'{column_expr}.str.ends_with({rhs})'
    if operator == 'in':
        return f'{column_expr}.is_in({rhs})'
    if operator == 'not_in':
        return f'~{column_expr}.is_in({rhs})'
    return None


def _sql_filter_expr(condition: dict[str, Any]) -> str | None:
    column = condition.get('column')
    if not isinstance(column, str) or not column:
        return None
    operator = str(condition.get('operator', '='))
    value_type = str(condition.get('value_type', 'string'))
    compare_column = condition.get('compare_column')
    lhs = _sql_quote(column)

    if operator == 'is_null':
        return f'{lhs} IS NULL'
    if operator == 'is_not_null':
        return f'{lhs} IS NOT NULL'

    if value_type == 'column' and isinstance(compare_column, str) and compare_column:
        rhs = _sql_quote(compare_column)
    else:
        value = condition.get('value')
        if operator in _FILTER_IN_OPERATORS:
            items = value if isinstance(value, list) else [value]
            rhs = '(' + ', '.join(_sql_literal(item) for item in items) + ')'
        else:
            rhs = _sql_literal(value)

    if operator in _FILTER_BINARY_OPERATORS:
        actual = '=' if operator == '==' else operator
        return f'{lhs} {actual} {rhs}'
    if operator == 'contains':
        return f"{lhs} LIKE ('%' || {rhs} || '%')"
    if operator == 'not_contains':
        return f"{lhs} NOT LIKE ('%' || {rhs} || '%')"
    if operator == 'starts_with':
        return f"{lhs} LIKE ({rhs} || '%')"
    if operator == 'ends_with':
        return f"{lhs} LIKE ('%' || {rhs})"
    if operator == 'in':
        return f'{lhs} IN {rhs}'
    if operator == 'not_in':
        return f'{lhs} NOT IN {rhs}'
    return None


def _polars_group_agg_expr(aggregation: dict[str, Any]) -> str | None:
    column = aggregation.get('column')
    function = aggregation.get('function')
    alias = aggregation.get('alias')
    if not isinstance(column, str) or not column:
        return None
    if not isinstance(function, str) or not function:
        return None
    alias_name = alias if isinstance(alias, str) and alias else f'{column}_{function}'
    func = function.lower()
    if func == 'n_unique':
        return f'pl.col({json.dumps(column)}).n_unique().alias({json.dumps(alias_name)})'
    return f'pl.col({json.dumps(column)}).{func}().alias({json.dumps(alias_name)})'


def _sql_group_agg_expr(aggregation: dict[str, Any]) -> str | None:
    column = aggregation.get('column')
    function = aggregation.get('function')
    alias = aggregation.get('alias')
    if not isinstance(column, str) or not column:
        return None
    if not isinstance(function, str) or not function:
        return None
    alias_name = alias if isinstance(alias, str) and alias else f'{column}_{function}'
    func = function.lower()
    template = _SQL_AGG_MAP.get(func)
    if template is None:
        return None
    expr = _sql_quote(column)
    if template == 'COUNT_DISTINCT':
        rendered = f'COUNT(DISTINCT {expr})'
    elif '{expr}' in template:
        rendered = template.format(expr=expr)
    else:
        rendered = f'{template}({expr})'
    return f'{rendered} AS {_sql_quote(alias_name)}'


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
                '# Generated by Data-Forge code export (Polars)',
                '# Replace SOURCE_*_PATH placeholders with your local data paths.',
                'import polars as pl',
                '',
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
        lines.append(f'{const_name} = {json.dumps(replacement)}')
    if source_constants:
        lines.append('')

    tab_last_var: dict[str, str] = {}
    for tab_index, tab in enumerate(selection.ordered_tabs, start=1):
        tab_slug = _identifier(f'tab_{tab_index}_{_slug(tab.name)}')
        source_var = f'{tab_slug}_source'

        lines.append(f'# ---- Tab: {tab.name} ----')
        source_tab_id = tab.datasource.analysis_tab_id
        if isinstance(source_tab_id, str) and source_tab_id:
            parent_var = tab_last_var.get(source_tab_id)
            if parent_var:
                lines.append(f'{source_var} = {parent_var}')
            else:
                lines.append(f'{source_var} = pl.LazyFrame()')
                warn(f"Tab '{tab.name}' depends on missing tab '{source_tab_id}'")
        else:
            datasource = datasources_by_id.get(tab.datasource.id)
            path_const = source_constants.get(tab.id)
            if path_const is None:
                lines.append(f'{source_var} = pl.LazyFrame()')
                warn(f"Tab '{tab.name}' is missing datasource placeholder metadata")
            else:
                scan_expr, scan_warning = _scan_expression(datasource, path_const)
                lines.append(f'{source_var} = {scan_expr}')
                if scan_warning:
                    warn(f"Tab '{tab.name}': {scan_warning}")

        current_var = source_var
        for step_index, step in enumerate(tab.steps, start=1):
            next_var = f'{tab_slug}_step_{step_index}'
            advance_var = True
            lines.append(f'# Step {step_index}: {step.type}')
            config = step.config if isinstance(step.config, dict) else {}

            if step.type == 'filter':
                conditions = _normalize_filter_conditions(config)
                logic = str(config.get('logic', 'AND')).upper()
                exprs = [expr for cond in conditions if isinstance(cond, dict) if (expr := _polars_filter_expr(cond))]
                if exprs:
                    joiner = ' & ' if logic == 'AND' else ' | '
                    lines.append(f'{next_var} = {current_var}.filter({joiner.join(exprs)})')
                else:
                    lines.append(f'{next_var} = {current_var}')
                    warn(f"Filter step in tab '{tab.name}' has no valid conditions")
            elif step.type == 'select':
                columns = config.get('columns')
                cast_map = config.get('cast_map')
                if isinstance(columns, list) and columns:
                    quoted = '[' + ', '.join(json.dumps(col) for col in columns if isinstance(col, str)) + ']'
                    lines.append(f'{next_var} = {current_var}.select({quoted})')
                else:
                    lines.append(f'{next_var} = {current_var}')
                    warn(f"Select step in tab '{tab.name}' has no columns and was treated as pass-through")
                if isinstance(cast_map, dict) and cast_map:
                    casts: list[str] = []
                    for column, dtype in cast_map.items():
                        if not isinstance(column, str):
                            continue
                        mapped = _POLARS_CAST_MAP.get(str(dtype))
                        if not mapped:
                            warn(f"Select step in tab '{tab.name}' has unsupported cast type '{dtype}' for '{column}'")
                            continue
                        casts.append(f'pl.col({json.dumps(column)}).cast(pl.{mapped}).alias({json.dumps(column)})')
                    if casts:
                        cast_expr = '[' + ', '.join(casts) + ']'
                        lines.append(f'{next_var} = {next_var}.with_columns({cast_expr})')
            elif step.type == 'drop':
                columns = config.get('columns')
                if isinstance(columns, list) and columns:
                    quoted = '[' + ', '.join(json.dumps(col) for col in columns if isinstance(col, str)) + ']'
                    lines.append(f'{next_var} = {current_var}.drop({quoted})')
                else:
                    lines.append(f'{next_var} = {current_var}')
            elif step.type == 'sort':
                columns = config.get('columns')
                descending = config.get('descending')
                if isinstance(columns, list) and columns:
                    cols = '[' + ', '.join(json.dumps(col) for col in columns if isinstance(col, str)) + ']'
                    if isinstance(descending, list) and descending:
                        desc = '[' + ', '.join('True' if bool(item) else 'False' for item in descending) + ']'
                        lines.append(f'{next_var} = {current_var}.sort({cols}, descending={desc})')
                    elif isinstance(descending, bool):
                        lines.append(
                            f'{next_var} = {current_var}.sort({cols}, descending={"True" if descending else "False"})',
                        )
                    else:
                        lines.append(f'{next_var} = {current_var}.sort({cols})')
                else:
                    lines.append(f'{next_var} = {current_var}')
            elif step.type == 'rename':
                mapping = config.get('column_mapping')
                if isinstance(mapping, dict) and mapping:
                    lines.append(f'{next_var} = {current_var}.rename({_safe_py(mapping)})')
                else:
                    lines.append(f'{next_var} = {current_var}')
            elif step.type == 'groupby':
                group_by = config.get('group_by')
                aggregations = config.get('aggregations')
                agg_exprs: list[str] = []
                if isinstance(aggregations, list):
                    for agg in aggregations:
                        if not isinstance(agg, dict):
                            continue
                        expr = _polars_group_agg_expr(agg)
                        if expr:
                            agg_exprs.append(expr)
                if isinstance(group_by, list) and group_by and agg_exprs:
                    group_cols = '[' + ', '.join(json.dumps(col) for col in group_by if isinstance(col, str)) + ']'
                    agg_list = '[' + ', '.join(agg_exprs) + ']'
                    lines.append(f'{next_var} = {current_var}.group_by({group_cols}).agg({agg_list})')
                else:
                    lines.append(f'{next_var} = {current_var}')
                    warn(f"GroupBy step in tab '{tab.name}' is missing group_by or aggregations")
            elif step.type == 'join':
                right_source = config.get('right_source')
                join_columns = config.get('join_columns')
                how = str(config.get('how', 'inner')).lower()
                suffix = str(config.get('suffix', '_right'))
                right_var = tab_last_var.get(str(right_source)) if isinstance(right_source, str) else None
                if right_var and isinstance(join_columns, list) and join_columns:
                    left_on = [pair.get('left_column') for pair in join_columns if isinstance(pair, dict)]
                    right_on = [pair.get('right_column') for pair in join_columns if isinstance(pair, dict)]
                    left_cols = [col for col in left_on if isinstance(col, str) and col]
                    right_cols = [col for col in right_on if isinstance(col, str) and col]
                    if left_cols and right_cols:
                        left_list = '[' + ', '.join(json.dumps(col) for col in left_cols) + ']'
                        right_list = '[' + ', '.join(json.dumps(col) for col in right_cols) + ']'
                        mapped_how = 'full' if how == 'outer' else how
                        lines.append(
                            f'{next_var} = {current_var}.join('
                            f'{right_var}, left_on={left_list}, right_on={right_list}, '
                            f'how={json.dumps(mapped_how)}, suffix={json.dumps(suffix)})',
                        )
                    else:
                        lines.append(f'{next_var} = {current_var}')
                        warn(f"Join step in tab '{tab.name}' has empty join column mappings")
                else:
                    lines.append(f'{next_var} = {current_var}')
                    warn(f"Join step in tab '{tab.name}' could not resolve right source '{right_source}'")
            elif step.type == 'expression':
                expression = config.get('expression')
                column_name = config.get('column_name')
                if isinstance(expression, str) and expression.strip() and isinstance(column_name, str) and column_name:
                    lines.append(
                        f'{next_var} = {current_var}.with_columns(({expression}).alias({json.dumps(column_name)}))',
                    )
                else:
                    lines.append(f'{next_var} = {current_var}')
                    warn(f"Expression step in tab '{tab.name}' is missing expression or column_name")
            elif step.type == 'with_columns':
                expressions = config.get('expressions')
                rendered: list[str] = []
                if isinstance(expressions, list):
                    for expression in expressions:
                        if not isinstance(expression, dict):
                            continue
                        name = expression.get('name')
                        expr_type = expression.get('type')
                        if not isinstance(name, str) or not name:
                            continue
                        if expr_type == 'literal':
                            rendered.append(f'pl.lit({_safe_py(expression.get("value"))}).alias({json.dumps(name)})')
                        elif expr_type == 'column' and isinstance(expression.get('column'), str):
                            rendered.append(
                                f'pl.col({json.dumps(expression["column"])}).alias({json.dumps(name)})',
                            )
                        elif expr_type == 'udf':
                            warn(
                                f"With Columns UDF expression '{name}' in tab '{tab.name}' is not exportable "
                                'as pure Polars and was skipped',
                            )
                        else:
                            warn(f"With Columns expression '{name}' in tab '{tab.name}' has unsupported type '{expr_type}'")
                if rendered:
                    lines.append(f'{next_var} = {current_var}.with_columns([{", ".join(rendered)}])')
                else:
                    lines.append(f'{next_var} = {current_var}')
            elif step.type == 'pivot':
                on_col = config.get('columns')
                values = config.get('values')
                index = config.get('index')
                aggregate_function = str(config.get('aggregate_function', 'first'))
                if isinstance(on_col, str) and on_col:
                    index_expr = (
                        '[' + ', '.join(json.dumps(col) for col in index if isinstance(col, str)) + ']' if isinstance(index, list) else '[]'
                    )
                    values_expr = json.dumps(values) if isinstance(values, str) and values else 'None'
                    lines.append(
                        f'{next_var} = {current_var}.pivot('
                        f'on={json.dumps(on_col)}, values={values_expr}, index={index_expr}, '
                        f'aggregate_function={json.dumps(aggregate_function)})',
                    )
                else:
                    lines.append(f'{next_var} = {current_var}')
                    warn(f"Pivot step in tab '{tab.name}' is missing columns")
            elif step.type == 'unpivot':
                id_vars = config.get('id_vars')
                value_vars = config.get('value_vars')
                variable_name = str(config.get('variable_name', 'variable'))
                value_name = str(config.get('value_name', 'value'))
                if isinstance(value_vars, list) and value_vars:
                    ids_expr = (
                        '[' + ', '.join(json.dumps(col) for col in id_vars if isinstance(col, str)) + ']'
                        if isinstance(id_vars, list)
                        else '[]'
                    )
                    value_expr = '[' + ', '.join(json.dumps(col) for col in value_vars if isinstance(col, str)) + ']'
                    lines.append(
                        f'{next_var} = {current_var}.unpivot('
                        f'on={value_expr}, index={ids_expr}, variable_name={json.dumps(variable_name)}, '
                        f'value_name={json.dumps(value_name)})',
                    )
                else:
                    lines.append(f'{next_var} = {current_var}')
                    warn(f"Unpivot step in tab '{tab.name}' is missing value_vars")
            elif step.type == 'deduplicate':
                subset = config.get('subset')
                keep = str(config.get('keep', 'first'))
                if isinstance(subset, list) and subset:
                    subset_expr = '[' + ', '.join(json.dumps(col) for col in subset if isinstance(col, str)) + ']'
                    lines.append(f'{next_var} = {current_var}.unique(subset={subset_expr}, keep={json.dumps(keep)})')
                else:
                    lines.append(f'{next_var} = {current_var}.unique(keep={json.dumps(keep)})')
            elif step.type == 'sample':
                fraction = config.get('fraction', 0.5)
                seed = config.get('seed')
                if isinstance(seed, int):
                    lines.append(f'{next_var} = {current_var}.sample(fraction={_safe_py(fraction)}, seed={seed})')
                else:
                    lines.append(f'{next_var} = {current_var}.sample(fraction={_safe_py(fraction)})')
            elif step.type == 'limit':
                n = config.get('n', 100)
                lines.append(f'{next_var} = {current_var}.limit({int(n) if isinstance(n, int) else 100})')
            elif step.type == 'view':
                lines.append(f'{current_var}.show(limit=5)')
                advance_var = False
            elif step.type in {
                'download',
                'export',
                'chart',
                'plot_bar',
                'plot_horizontal_bar',
                'plot_area',
                'plot_heatgrid',
                'plot_histogram',
                'plot_scatter',
                'plot_line',
                'plot_pie',
                'plot_boxplot',
            }:
                lines.append(f'{next_var} = {current_var}')
            else:
                lines.append(f'# Step type "{step.type}" is not directly exportable; keeping previous frame')
                lines.append(f'{next_var} = {current_var}')
                warn(
                    f'Step "{step.type}" in tab "{tab.name}" is not fully exportable to pure Polars. Original config: {_safe_json(config)}',
                )

            if advance_var:
                current_var = next_var

        tab_last_var[tab.id] = current_var
        lines.append(f'{tab_slug}_result = {current_var}')
        lines.append('')

    target_var = tab_last_var.get(selection.target_tab.id)
    if target_var:
        lines.append(f'result = {target_var}.collect()')
        lines.append('print(result)')
    else:
        lines.append('result = pl.DataFrame()')
        lines.append('print(result)')
        warn(f"Could not resolve target tab '{selection.target_tab.name}' for final collect")

    return '\n'.join(lines).strip() + '\n', warnings


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
        base = _identifier(_slug(datasource.name if datasource else tab.name))
        table_name = f'{base}_table'
        suffix = 2
        while table_name in used_table_names:
            table_name = f'{base}_table_{suffix}'
            suffix += 1
        used_table_names.add(table_name)
        source_tables[tab.id] = table_name

    header_lines = [
        '-- Generated by Data-Forge code export (SQL)',
        '-- PostgreSQL-compatible SQL (DuckDB-compatible for most clauses).',
        '-- Replace placeholder table names below with real table/view names.',
    ]
    for tab in selection.ordered_tabs:
        table_placeholder = source_tables.get(tab.id)
        if table_placeholder:
            datasource = datasources_by_id.get(tab.datasource.id)
            source_name = datasource.name if datasource else tab.datasource.id
            header_lines.append(f'-- {table_placeholder}: source "{source_name}"')
    header_lines.append('')

    ctes: list[str] = []
    tab_final_cte: dict[str, str] = {}

    for tab_index, tab in enumerate(selection.ordered_tabs, start=1):
        tab_alias = _identifier(f'tab_{tab_index}_{_slug(tab.name)}')
        source_cte = f'{tab_alias}_source'
        source_tab_id = tab.datasource.analysis_tab_id
        if isinstance(source_tab_id, str) and source_tab_id:
            upstream_cte = tab_final_cte.get(source_tab_id)
            if upstream_cte:
                source_from = upstream_cte
            else:
                source_from = '(SELECT NULL WHERE FALSE)'
                warn(f"Tab '{tab.name}' depends on missing tab '{source_tab_id}'")
        else:
            source_from = source_tables.get(tab.id, '(SELECT NULL WHERE FALSE)')
            if source_from == '(SELECT NULL WHERE FALSE)':
                warn(f"Tab '{tab.name}' is missing datasource metadata for SQL export")

        ctes.append(f'{source_cte} AS (\n    SELECT * FROM {source_from}\n)')
        current_cte = source_cte

        for step_index, step in enumerate(tab.steps, start=1):
            step_cte = f'{tab_alias}_step_{step_index}'
            config = step.config if isinstance(step.config, dict) else {}
            comments: list[str] = []
            body = f'SELECT * FROM {current_cte}'

            if step.type == 'filter':
                conditions = _normalize_filter_conditions(config)
                logic = str(config.get('logic', 'AND')).upper()
                exprs = [expr for cond in conditions if isinstance(cond, dict) if (expr := _sql_filter_expr(cond))]
                if exprs:
                    joiner = ' AND ' if logic == 'AND' else ' OR '
                    body = f'SELECT * FROM {current_cte} WHERE ' + joiner.join(exprs)
                else:
                    warn(f"Filter step in tab '{tab.name}' has no valid SQL conditions")
            elif step.type == 'select':
                columns = config.get('columns')
                cast_map = config.get('cast_map')
                if isinstance(columns, list) and columns:
                    rendered: list[str] = []
                    for column in columns:
                        if not isinstance(column, str):
                            continue
                        cast_type = cast_map.get(column) if isinstance(cast_map, dict) else None
                        sql_type = _SQL_CAST_MAP.get(str(cast_type)) if cast_type else None
                        if sql_type:
                            rendered.append(f'CAST({_sql_quote(column)} AS {sql_type}) AS {_sql_quote(column)}')
                        else:
                            rendered.append(_sql_quote(column))
                    if rendered:
                        body = f'SELECT {", ".join(rendered)} FROM {current_cte}'
                else:
                    warn(f"Select step in tab '{tab.name}' has no columns and was treated as pass-through")
            elif step.type == 'sort':
                columns = config.get('columns')
                descending = config.get('descending')
                if isinstance(columns, list) and columns:
                    clauses: list[str] = []
                    for idx, column in enumerate(columns):
                        if not isinstance(column, str):
                            continue
                        desc = False
                        if isinstance(descending, list):
                            desc = bool(descending[idx]) if idx < len(descending) else False
                        elif isinstance(descending, bool):
                            desc = descending
                        clauses.append(f'{_sql_quote(column)} {"DESC" if desc else "ASC"}')
                    if clauses:
                        body = f'SELECT * FROM {current_cte} ORDER BY ' + ', '.join(clauses)
            elif step.type == 'groupby':
                group_by = config.get('group_by')
                aggregations = config.get('aggregations')
                if isinstance(group_by, list) and group_by and isinstance(aggregations, list) and aggregations:
                    group_cols = [_sql_quote(col) for col in group_by if isinstance(col, str)]
                    agg_exprs = [expr for agg in aggregations if isinstance(agg, dict) if (expr := _sql_group_agg_expr(agg))]
                    if group_cols and agg_exprs:
                        body = 'SELECT ' + ', '.join(group_cols + agg_exprs) + f' FROM {current_cte} GROUP BY ' + ', '.join(group_cols)
                    else:
                        warn(f"GroupBy step in tab '{tab.name}' has unsupported aggregation functions")
                else:
                    warn(f"GroupBy step in tab '{tab.name}' is missing group_by or aggregations")
            elif step.type == 'join':
                right_source = config.get('right_source')
                join_columns = config.get('join_columns')
                how = str(config.get('how', 'inner')).lower()
                right_columns = config.get('right_columns')
                right_cte = tab_final_cte.get(str(right_source)) if isinstance(right_source, str) else None
                if how == 'cross' and right_cte:
                    body = f'SELECT l.*, r.* FROM {current_cte} AS l CROSS JOIN {right_cte} AS r'
                elif right_cte and isinstance(join_columns, list) and join_columns:
                    on_parts: list[str] = []
                    for pair in join_columns:
                        if not isinstance(pair, dict):
                            continue
                        left_col = pair.get('left_column')
                        right_col = pair.get('right_column')
                        if isinstance(left_col, str) and isinstance(right_col, str) and left_col and right_col:
                            on_parts.append(f'l.{_sql_quote(left_col)} = r.{_sql_quote(right_col)}')
                    if on_parts:
                        join_type = {
                            'inner': 'INNER JOIN',
                            'left': 'LEFT JOIN',
                            'right': 'RIGHT JOIN',
                            'outer': 'FULL OUTER JOIN',
                        }.get(how, 'INNER JOIN')
                        if isinstance(right_columns, list) and right_columns:
                            right_select = ', '.join(
                                f'r.{_sql_quote(col)} AS {_sql_quote(col)}' for col in right_columns if isinstance(col, str)
                            )
                            select_clause = f'l.*, {right_select}' if right_select else 'l.*, r.*'
                        else:
                            select_clause = 'l.*, r.*'
                        body = f'SELECT {select_clause} FROM {current_cte} AS l {join_type} {right_cte} AS r ON ' + ' AND '.join(on_parts)
                    else:
                        warn(f"Join step in tab '{tab.name}' has empty join column mappings")
                else:
                    warn(f"Join step in tab '{tab.name}' could not resolve right source '{right_source}'")
            elif step.type == 'expression':
                expression = config.get('expression')
                column_name = config.get('column_name')
                if isinstance(expression, str) and expression.strip() and isinstance(column_name, str) and column_name:
                    body = f'SELECT *, ({expression}) AS {_sql_quote(column_name)} FROM {current_cte}'
                else:
                    warn(f"Expression step in tab '{tab.name}' is missing expression or column_name")
            elif step.type == 'limit':
                n = config.get('n', 100)
                n_value = int(n) if isinstance(n, int) else 100
                body = f'SELECT * FROM {current_cte} LIMIT {n_value}'
            elif step.type == 'deduplicate':
                subset = config.get('subset')
                keep = str(config.get('keep', 'first'))
                if isinstance(subset, list) and subset and keep == 'first':
                    cols = ', '.join(_sql_quote(col) for col in subset if isinstance(col, str))
                    body = f'SELECT DISTINCT ON ({cols}) * FROM {current_cte} ORDER BY {cols}'
                else:
                    comments.append(
                        f'-- WARNING: step "{step.type}" in tab "{tab.name}" cannot be represented exactly in SQL',
                    )
                    comments.append(f'-- Original config: {_safe_json(config)}')
            elif step.type in {'view', 'download', 'export'}:
                pass
            else:
                comments.append(f'-- WARNING: step "{step.type}" in tab "{tab.name}" is not directly translatable to SQL')
                comments.append(f'-- Original config: {_safe_json(config)}')
                warn(
                    f'Step "{step.type}" in tab "{tab.name}" is not fully exportable to SQL. Original config: {_safe_json(config)}',
                )

            step_cte_block = ''
            if comments:
                step_cte_block += '\n'.join(comments) + '\n'
            step_cte_block += f'{step_cte} AS (\n    {body}\n)'
            ctes.append(step_cte_block)
            current_cte = step_cte

        tab_final_cte[tab.id] = current_cte

    final_cte = tab_final_cte.get(selection.target_tab.id)
    if final_cte is None:
        warn(f"Could not resolve target tab '{selection.target_tab.name}' for final SELECT")
        query = 'SELECT 1 WHERE FALSE'
    else:
        query = f'SELECT * FROM {final_cte}'

    sql = '\n'.join(header_lines) + 'WITH\n' + ',\n'.join(ctes) + '\n' + query + ';\n'
    return sql, warnings
