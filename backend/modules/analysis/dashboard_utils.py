from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime
from typing import Any

VariableValue = str | int | float | bool

SUPPORTED_VARIABLE_TYPES = frozenset(
    {
        'string',
        'number',
        'boolean',
        'single_select',
        'multi_select',
        'date',
        'date_range',
    },
)

SUPPORTED_WIDGET_TYPES = frozenset({'dataset_preview', 'chart', 'metric_kpi', 'text_header'})
SUPPORTED_LAYOUT_WIDTHS = range(1, 13)
SUPPORTED_LAYOUT_HEIGHTS = range(1, 9)
SUPPORTED_METRIC_AGGREGATIONS = frozenset({'sum', 'mean', 'min', 'max', 'count', 'median', 'n_unique'})
SUPPORTED_CHART_TYPES = frozenset(
    {'bar', 'horizontal_bar', 'area', 'heatgrid', 'histogram', 'scatter', 'line', 'pie', 'boxplot'},
)
SUPPORTED_LEGEND_POSITIONS = frozenset({'top', 'right', 'bottom', 'left'})


def is_variable_ref(value: Any) -> bool:
    return isinstance(value, dict) and value.get('kind') == 'variable_ref'


def has_variable_refs(value: Any) -> bool:
    if is_variable_ref(value):
        return True
    if isinstance(value, list):
        return any(has_variable_refs(item) for item in value)
    if isinstance(value, dict):
        return any(has_variable_refs(item) for item in value.values())
    return False


def _normalize_date_value(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        trimmed = value.strip()
        if len(trimmed) != 10:
            raise ValueError(f'Expected YYYY-MM-DD date string, got {value!r}')
        date.fromisoformat(trimmed)
        return trimmed
    raise ValueError(f'Expected date value, got {type(value).__name__}')


def _normalize_date_range(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError('Date range variables require an object with start and end')
    start = _normalize_date_value(value.get('start'))
    end = _normalize_date_value(value.get('end'))
    if start > end:
        raise ValueError('Date range start must be before or equal to end')
    return {'start': start, 'end': end}


def _normalize_option_value(value: Any) -> VariableValue:
    if isinstance(value, bool):
        return value
    if isinstance(value, (str, int, float)):
        return value
    raise ValueError(f'Unsupported option value type: {type(value).__name__}')


def _normalize_variable_value(definition: dict[str, Any], value: Any) -> Any:
    variable_type = str(definition.get('type'))
    if variable_type == 'string':
        if not isinstance(value, str):
            raise ValueError(f"Variable '{definition.get('id')}' requires a string value")
        return value
    if variable_type == 'number':
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Variable '{definition.get('id')}' requires a numeric value")
        return value
    if variable_type == 'boolean':
        if not isinstance(value, bool):
            raise ValueError(f"Variable '{definition.get('id')}' requires a boolean value")
        return value
    if variable_type == 'single_select':
        normalized = _normalize_option_value(value)
        return normalized
    if variable_type == 'multi_select':
        if not isinstance(value, list):
            raise ValueError(f"Variable '{definition.get('id')}' requires a list value")
        return [_normalize_option_value(item) for item in value]
    if variable_type == 'date':
        return _normalize_date_value(value)
    if variable_type == 'date_range':
        return _normalize_date_range(value)
    raise ValueError(f"Unsupported variable type '{variable_type}'")


def _validate_allowed_values(definition: dict[str, Any], value: Any) -> None:
    options = definition.get('options') or []
    if not options:
        return
    allowed = {_normalize_option_value(option.get('value')) for option in options if isinstance(option, dict)}
    variable_type = str(definition.get('type'))
    if variable_type == 'multi_select':
        invalid = [item for item in value if item not in allowed]
        if invalid:
            raise ValueError(f"Variable '{definition.get('id')}' contains unsupported values: {invalid!r}")
        return
    if value not in allowed:
        raise ValueError(f"Variable '{definition.get('id')}' has unsupported value: {value!r}")


def validate_variable_definitions(variables: list[dict[str, Any]], tabs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    seen: set[str] = set()
    tab_ids = {str(tab.get('id')) for tab in tabs if isinstance(tab, dict) and tab.get('id')}
    variable_map: dict[str, dict[str, Any]] = {}
    for definition in variables:
        variable_id = str(definition.get('id') or '').strip()
        if not variable_id:
            raise ValueError('Dashboard variables require an id')
        if variable_id in seen:
            raise ValueError(f"Duplicate dashboard variable id '{variable_id}'")
        seen.add(variable_id)
        label = str(definition.get('label') or '').strip()
        if not label:
            raise ValueError(f"Dashboard variable '{variable_id}' requires a label")
        variable_type = str(definition.get('type') or '').strip()
        if variable_type not in SUPPORTED_VARIABLE_TYPES:
            raise ValueError(f"Dashboard variable '{variable_id}' has unsupported type '{variable_type}'")

        if 'default_value' not in definition:
            raise ValueError(f"Dashboard variable '{variable_id}' requires default_value")
        default_value = _normalize_variable_value(definition, definition.get('default_value'))

        options = definition.get('options') or []
        option_source = definition.get('option_source')
        if options and option_source:
            raise ValueError(f"Dashboard variable '{variable_id}' cannot define both options and option_source")
        if options:
            normalized_values: set[VariableValue] = set()
            for option in options:
                if not isinstance(option, dict):
                    raise ValueError(f"Dashboard variable '{variable_id}' options must be objects")
                option_label = str(option.get('label') or '').strip()
                if not option_label:
                    raise ValueError(f"Dashboard variable '{variable_id}' has an option without a label")
                option_value = _normalize_option_value(option.get('value'))
                if option_value in normalized_values:
                    raise ValueError(f"Dashboard variable '{variable_id}' contains duplicate option values")
                normalized_values.add(option_value)
        if option_source:
            if not isinstance(option_source, dict):
                raise ValueError(f"Dashboard variable '{variable_id}' option_source must be an object")
            tab_id = str(option_source.get('tab_id') or '').strip()
            column = str(option_source.get('column') or '').strip()
            if not tab_id or tab_id not in tab_ids:
                raise ValueError(f"Dashboard variable '{variable_id}' option_source.tab_id must reference an analysis tab")
            if not column:
                raise ValueError(f"Dashboard variable '{variable_id}' option_source.column is required")
        _validate_allowed_values(definition, default_value)
        variable_map[variable_id] = {**definition, 'default_value': default_value}
    return variable_map


def merge_variable_values(
    variables: list[dict[str, Any]],
    tabs: list[dict[str, Any]] | None = None,
    variable_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    variable_map = validate_variable_definitions(variables, tabs or [])
    raw_values = variable_values or {}
    merged: dict[str, Any] = {}
    for variable_id, definition in variable_map.items():
        raw_value = raw_values.get(variable_id, definition.get('default_value'))
        normalized = _normalize_variable_value(definition, raw_value)
        _validate_allowed_values(definition, normalized)
        merged[variable_id] = normalized
    for variable_id in raw_values:
        if variable_id not in variable_map:
            raise ValueError(f"Unknown dashboard variable '{variable_id}'")
    return merged


def _path_is_allowed(step_type: str, path: tuple[Any, ...]) -> bool:
    if step_type == 'filter':
        return len(path) == 3 and path[0] == 'conditions' and isinstance(path[1], int) and path[2] == 'value'
    if step_type == 'limit':
        return path == ('n',)
    if step_type == 'topk':
        return path == ('k',)
    return False


def _resolve_variable_ref(
    step_type: str,
    config: dict[str, Any],
    path: tuple[Any, ...],
    value: dict[str, Any],
    variable_map: dict[str, dict[str, Any]],
    state: dict[str, Any],
) -> Any:
    variable_id = str(value.get('variable_id') or '').strip()
    if not variable_id:
        raise ValueError(f"Step '{step_type}' contains a variable ref without variable_id")
    definition = variable_map.get(variable_id)
    if definition is None:
        raise ValueError(f"Step '{step_type}' references unknown variable '{variable_id}'")
    if not _path_is_allowed(step_type, path):
        raise ValueError(f"Variable refs are not supported for step '{step_type}' field '{'.'.join(map(str, path))}'")

    resolved = state[variable_id]
    if step_type == 'limit' or step_type == 'topk':
        if definition.get('type') != 'number':
            raise ValueError(f"Step '{step_type}' requires a numeric variable for '{variable_id}'")
        return resolved

    if step_type != 'filter':
        return resolved

    if len(path) != 3 or not isinstance(path[1], int):
        raise ValueError('Unexpected filter variable ref path')
    condition = config.get('conditions', [])[path[1]]
    if not isinstance(condition, dict):
        raise ValueError('Filter condition is invalid')
    operator = str(condition.get('operator') or '=')
    value_type = str(condition.get('value_type') or 'string')
    variable_type = str(definition.get('type') or '')
    if variable_type == 'date_range':
        value_key = value.get('value_key')
        if value_key not in {'start', 'end'}:
            raise ValueError(f"Date range variable '{variable_id}' requires value_key=start or end")
        resolved = resolved[value_key]
    if operator in {'in', 'not_in'}:
        if variable_type == 'multi_select':
            return resolved
        if variable_type in {'single_select', 'string'}:
            return [resolved]
        raise ValueError(f"Filter operator '{operator}' requires a select/string variable, got '{variable_type}'")
    if value_type == 'number' and variable_type != 'number':
        raise ValueError(f"Filter value_type=number requires numeric variable '{variable_id}'")
    if value_type == 'boolean' and variable_type != 'boolean':
        raise ValueError(f"Filter value_type=boolean requires boolean variable '{variable_id}'")
    if value_type in {'date', 'datetime'} and variable_type not in {'date', 'date_range'}:
        raise ValueError(f"Filter value_type={value_type} requires date/date_range variable '{variable_id}'")
    if value_type == 'string' and variable_type not in {'string', 'single_select'}:
        raise ValueError(f"Filter value_type=string requires string/single_select variable '{variable_id}'")
    return resolved


def _resolve_config_value(
    step_type: str,
    root: dict[str, Any],
    value: Any,
    path: tuple[Any, ...],
    variable_map: dict[str, dict[str, Any]],
    state: dict[str, Any],
) -> Any:
    if is_variable_ref(value):
        return _resolve_variable_ref(step_type, root, path, value, variable_map, state)
    if isinstance(value, list):
        return [_resolve_config_value(step_type, root, item, (*path, index), variable_map, state) for index, item in enumerate(value)]
    if isinstance(value, dict):
        return {key: _resolve_config_value(step_type, root, item, (*path, key), variable_map, state) for key, item in value.items()}
    return value


def resolve_pipeline_variables(
    pipeline: dict[str, Any],
    variable_values: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from modules.analysis.step_schemas import validate_step

    resolved = deepcopy(pipeline)
    tabs = resolved.get('tabs', [])
    variables = resolved.get('variables', [])
    if not isinstance(tabs, list):
        raise ValueError('Analysis pipeline tabs must be a list')
    if not isinstance(variables, list):
        raise ValueError('Analysis pipeline variables must be a list')
    variable_map = validate_variable_definitions(
        [definition for definition in variables if isinstance(definition, dict)],
        [tab for tab in tabs if isinstance(tab, dict)],
    )
    state = merge_variable_values(list(variable_map.values()), [tab for tab in tabs if isinstance(tab, dict)], variable_values)
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        steps = tab.get('steps', [])
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_type = str(step.get('type') or '')
            config = step.get('config') or {}
            if not isinstance(config, dict):
                continue
            next_config = _resolve_config_value(step_type, config, config, (), variable_map, state)
            if not isinstance(next_config, dict):
                raise ValueError(f"Resolved config for step '{step_type}' is invalid")
            step['config'] = next_config
            validate_step(step_type, next_config)
    resolved['variable_values'] = state
    return resolved, state


def _collect_refs(value: Any, bucket: set[str]) -> None:
    if is_variable_ref(value):
        variable_id = str(value.get('variable_id') or '').strip()
        if variable_id:
            bucket.add(variable_id)
        return
    if isinstance(value, list):
        for item in value:
            _collect_refs(item, bucket)
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_refs(item, bucket)


def _collect_tab_dependencies(tab: dict[str, Any], tab_map: dict[str, dict[str, Any]], cache: dict[str, set[str]]) -> set[str]:
    tab_id = str(tab.get('id') or '')
    if tab_id in cache:
        return cache[tab_id]
    deps: set[str] = set()
    datasource = tab.get('datasource')
    if isinstance(datasource, dict):
        upstream_id = str(datasource.get('analysis_tab_id') or '').strip()
        if upstream_id:
            upstream = tab_map.get(upstream_id)
            if upstream:
                deps.update(_collect_tab_dependencies(upstream, tab_map, cache))
    steps = tab.get('steps', [])
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            config = step.get('config')
            if isinstance(config, dict):
                _collect_refs(config, deps)
    cache[tab_id] = deps
    return deps


def collect_dashboard_dependencies(pipeline: dict[str, Any], dashboard: dict[str, Any]) -> dict[str, list[str]]:
    tabs = pipeline.get('tabs', [])
    widgets = dashboard.get('widgets', [])
    if not isinstance(tabs, list) or not isinstance(widgets, list):
        return {}
    tab_map = {
        str(tab.get('id')): tab for tab in tabs if isinstance(tab, dict) and isinstance(tab.get('id'), str) and str(tab.get('id')).strip()
    }
    cache: dict[str, set[str]] = {}
    result: dict[str, list[str]] = {}
    for widget in widgets:
        if not isinstance(widget, dict):
            continue
        widget_id = str(widget.get('id') or '').strip()
        source_tab_id = str(widget.get('source_tab_id') or '').strip()
        if not widget_id:
            continue
        if not source_tab_id:
            result[widget_id] = []
            continue
        tab = tab_map.get(source_tab_id)
        if not tab:
            result[widget_id] = []
            continue
        result[widget_id] = sorted(_collect_tab_dependencies(tab, tab_map, cache))
    return result


def validate_dashboards(pipeline: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tabs = pipeline.get('tabs', [])
    dashboards = pipeline.get('dashboards', [])
    if not isinstance(tabs, list):
        raise ValueError('Analysis pipeline tabs must be a list')
    if not isinstance(dashboards, list):
        raise ValueError('Analysis dashboards must be a list')
    tab_ids = {str(tab.get('id')) for tab in tabs if isinstance(tab, dict) and tab.get('id')}
    seen_dashboards: set[str] = set()
    result: dict[str, dict[str, Any]] = {}
    for dashboard in dashboards:
        if not isinstance(dashboard, dict):
            raise ValueError('Dashboard definitions must be objects')
        dashboard_id = str(dashboard.get('id') or '').strip()
        if not dashboard_id:
            raise ValueError('Dashboard requires an id')
        if dashboard_id in seen_dashboards:
            raise ValueError(f"Duplicate dashboard id '{dashboard_id}'")
        seen_dashboards.add(dashboard_id)
        name = str(dashboard.get('name') or '').strip()
        if not name:
            raise ValueError(f"Dashboard '{dashboard_id}' requires a name")
        widgets = dashboard.get('widgets', [])
        layout = dashboard.get('layout', [])
        if not isinstance(widgets, list):
            raise ValueError(f"Dashboard '{dashboard_id}' widgets must be a list")
        if not isinstance(layout, list):
            raise ValueError(f"Dashboard '{dashboard_id}' layout must be a list")
        seen_widgets: set[str] = set()
        widget_ids: list[str] = []
        for widget in widgets:
            if not isinstance(widget, dict):
                raise ValueError(f"Dashboard '{dashboard_id}' widgets must be objects")
            widget_id = str(widget.get('id') or '').strip()
            if not widget_id:
                raise ValueError(f"Dashboard '{dashboard_id}' contains a widget without id")
            if widget_id in seen_widgets:
                raise ValueError(f"Dashboard '{dashboard_id}' contains duplicate widget id '{widget_id}'")
            seen_widgets.add(widget_id)
            widget_ids.append(widget_id)
            widget_type = str(widget.get('type') or '').strip()
            if widget_type not in SUPPORTED_WIDGET_TYPES:
                raise ValueError(f"Dashboard widget '{widget_id}' has unsupported type '{widget_type}'")
            title = str(widget.get('title') or '').strip()
            if widget_type != 'text_header' and not title:
                raise ValueError(f"Dashboard widget '{widget_id}' requires a title")
            source_tab_id = str(widget.get('source_tab_id') or '').strip()
            if widget_type != 'text_header' and source_tab_id not in tab_ids:
                raise ValueError(f"Dashboard widget '{widget_id}' must reference an analysis tab output")
            config = widget.get('config') or {}
            if not isinstance(config, dict):
                raise ValueError(f"Dashboard widget '{widget_id}' config must be an object")
            if widget_type == 'dataset_preview':
                page_size = int(config.get('page_size') or 25)
                if page_size < 1 or page_size > 200:
                    raise ValueError(f"Dashboard dataset widget '{widget_id}' page_size must be between 1 and 200")
            if widget_type == 'chart':
                chart_type = str(config.get('chart_type') or '').strip()
                if chart_type not in SUPPORTED_CHART_TYPES:
                    raise ValueError(f"Dashboard chart widget '{widget_id}' requires a supported chart_type")
                x_column = str(config.get('x_column') or '').strip()
                if not x_column:
                    raise ValueError(f"Dashboard chart widget '{widget_id}' requires x_column")
                if chart_type != 'histogram':
                    y_column = str(config.get('y_column') or '').strip()
                    if not y_column:
                        raise ValueError(f"Dashboard chart widget '{widget_id}' requires y_column")
                legend_position = str(config.get('legend_position') or 'right').strip()
                if legend_position not in SUPPORTED_LEGEND_POSITIONS:
                    allowed_positions = ', '.join(sorted(SUPPORTED_LEGEND_POSITIONS))
                    raise ValueError(
                        f"Dashboard chart widget '{widget_id}' legend_position must be one of: {allowed_positions}",
                    )
                for flag in ('pan_zoom_enabled', 'selection_enabled', 'area_selection_enabled'):
                    if flag in config and not isinstance(config.get(flag), bool):
                        raise ValueError(f"Dashboard chart widget '{widget_id}' field '{flag}' must be a boolean")
                if 'selection_filters_widgets' in config and not isinstance(config.get('selection_filters_widgets'), bool):
                    raise ValueError(
                        f"Dashboard chart widget '{widget_id}' field 'selection_filters_widgets' must be a boolean",
                    )
            if widget_type == 'metric_kpi':
                label = str(config.get('label') or '').strip()
                aggregation = str(config.get('aggregation') or '').strip()
                column = str(config.get('column') or '').strip()
                if not label:
                    raise ValueError(f"Dashboard metric widget '{widget_id}' requires label")
                if aggregation not in SUPPORTED_METRIC_AGGREGATIONS:
                    raise ValueError(f"Dashboard metric widget '{widget_id}' has unsupported aggregation")
                if aggregation != 'count' and not column:
                    raise ValueError(f"Dashboard metric widget '{widget_id}' requires column for aggregation '{aggregation}'")
            if widget_type == 'text_header':
                text = str(config.get('text') or '').strip()
                level = int(config.get('level') or 2)
                if not text:
                    raise ValueError(f"Dashboard text widget '{widget_id}' requires text")
                if level < 1 or level > 6:
                    raise ValueError(f"Dashboard text widget '{widget_id}' level must be between 1 and 6")

        layout_ids: set[str] = set()
        for item in layout:
            if not isinstance(item, dict):
                raise ValueError(f"Dashboard '{dashboard_id}' layout items must be objects")
            widget_id = str(item.get('widget_id') or '').strip()
            if widget_id not in seen_widgets:
                raise ValueError(f"Dashboard '{dashboard_id}' layout references unknown widget '{widget_id}'")
            layout_ids.add(widget_id)
            width = int(item.get('w') or 0)
            height = int(item.get('h') or 0)
            if width not in SUPPORTED_LAYOUT_WIDTHS:
                raise ValueError(f"Dashboard widget '{widget_id}' width must be between 1 and 12")
            if height not in SUPPORTED_LAYOUT_HEIGHTS:
                raise ValueError(f"Dashboard widget '{widget_id}' height must be between 1 and 8")
        missing_layout = [widget_id for widget_id in widget_ids if widget_id not in layout_ids]
        if missing_layout:
            raise ValueError(f"Dashboard '{dashboard_id}' layout is missing widgets: {', '.join(missing_layout)}")
        result[dashboard_id] = dashboard
    return result


def validate_analysis_pipeline_extensions(pipeline: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tabs = pipeline.get('tabs', [])
    variables = pipeline.get('variables', [])
    if not isinstance(tabs, list):
        raise ValueError('Analysis pipeline tabs must be a list')
    if not isinstance(variables, list):
        raise ValueError('Analysis pipeline variables must be a list')
    validate_variable_definitions(
        [definition for definition in variables if isinstance(definition, dict)],
        [tab for tab in tabs if isinstance(tab, dict)],
    )
    resolved, _ = resolve_pipeline_variables(pipeline)
    dashboards = validate_dashboards(resolved)
    for dashboard in dashboards.values():
        collect_dashboard_dependencies(resolved, dashboard)
    return dashboards


def stable_variable_state_key(state: dict[str, Any]) -> str:
    return json.dumps(state, sort_keys=True, separators=(',', ':'))
