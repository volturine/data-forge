"""Step Converter Module
Converts frontend pipeline step format to backend engine format.

Frontend format:
{
    "id": "uuid",
    "type": "filter",
    "config": {...},
    "depends_on": []
}

Backend format:
{
    "name": "Step Name",
    "operation": "filter",
    "params": {...}
}
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from modules.analysis.step_types import ChartType, chart_type_for_step, get_step_type_label, normalize_step_type
from modules.compute.operations.filter import normalize_filter_conditions

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FrontendStep:
    id: str
    type: str
    config: dict[str, object] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    is_applied: bool | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> 'FrontendStep':
        step_type = payload.get('type')
        if not isinstance(step_type, str) or not step_type:
            raise ValueError('Step must have a type field')

        step_id = payload.get('id')
        raw_config = payload.get('config')
        raw_deps = payload.get('depends_on')
        raw_applied = payload.get('is_applied')

        config = raw_config if isinstance(raw_config, dict) else {}
        depends_on = tuple(dep for dep in raw_deps if isinstance(dep, str)) if isinstance(raw_deps, list) else ()
        is_applied = raw_applied if isinstance(raw_applied, bool) else None

        return cls(
            id=str(step_id) if step_id is not None else 'Unknown Step',
            type=step_type,
            config=config,
            depends_on=depends_on,
            is_applied=is_applied,
        )


@dataclass(frozen=True, slots=True)
class BackendStep:
    name: str
    operation: str
    params: dict[str, object]


def step_display_name(step_type: str, config: Mapping[str, object]) -> str:
    if step_type == 'chart':
        chart_type = config.get('chart_type')
        if isinstance(chart_type, str) and chart_type:
            return get_step_type_label(f'plot_{chart_type}')
    return get_step_type_label(step_type)


def get_chart_type_for_step(step_type: str) -> ChartType | None:
    return chart_type_for_step(step_type)


def convert_step_format(frontend_step: Mapping[str, object] | FrontendStep) -> BackendStep:
    """Convert frontend step format to backend engine format."""
    parsed = frontend_step if isinstance(frontend_step, FrontendStep) else FrontendStep.from_mapping(frontend_step)
    step_type = parsed.type
    config = parsed.config
    chart_type = get_chart_type_for_step(step_type)
    if chart_type:
        config = {**config, 'chart_type': chart_type}
    normalized_type = normalize_step_type(step_type)

    return BackendStep(
        name=step_display_name(step_type, config),
        operation=normalized_type,
        params=convert_config_to_params(normalized_type, config),
    )


def convert_filter_config(config: dict) -> dict:
    """Convert filter config from frontend format to backend format.

    Frontend: {conditions: [{column, operator, value, value_type?, compare_column?}], logic: "AND"}
    Backend: {conditions: [{column, operator, value, value_type, compare_column?}], logic: "AND"}

    Supports multiple conditions with AND/OR logic.
    Supports typed values (string, number, date, datetime, column) and NULL checks.
    """
    return {
        'conditions': normalize_filter_conditions(config.get('conditions')),
        'logic': config.get('logic', 'AND'),
    }


def convert_groupby_config(config: dict) -> dict:
    """Convert groupby config from frontend to backend format.

    Canonical: {group_by: [...], aggregations: [{column, function, alias}]}
    Legacy fallback: {groupBy: [...], aggregations: [{column, function, alias}]}
    Backend: {group_by: [...], aggregations: [{column, function, alias}]}
    """
    return {
        'group_by': config.get('group_by', []),
        'aggregations': [
            {
                'column': agg.get('column'),
                'function': agg.get('function'),
                'alias': agg.get('alias'),
            }
            for agg in config.get('aggregations', [])
        ],
    }


def convert_join_config(config: dict) -> dict:
    """Convert join config from frontend to backend format.

    Frontend: {how, right_source, join_columns: [{left_column, right_column}], right_columns: [...], suffix}
    Backend: {right_source, join_columns, right_columns, how, suffix}
    """
    join_columns = config.get('join_columns', [])
    right_columns = config.get('right_columns', [])

    how = config.get('how', 'inner')
    return {
        'right_source': config.get('right_source'),
        'join_columns': join_columns,
        'right_columns': right_columns,
        'how': how,
        'suffix': config.get('suffix', '_right'),
    }


def convert_fillnull_config(config: dict) -> dict:
    """Convert fill_null config from frontend to backend format.

    Frontend: {strategy, value, value_type, columns}
    Backend: {strategy, value, value_type, columns}

    Normalizes frontend strategy "value" to backend strategy "literal".
    """
    strategy = config.get('strategy', 'literal')
    return {
        'strategy': strategy,
        'value': config.get('value'),
        'value_type': config.get('value_type'),
        'columns': config.get('columns', []),
    }


def convert_pivot_config(config: dict) -> dict:
    """Convert pivot config from frontend to backend format.

    Frontend: {index, columns, values, aggregate_function} or {index, columns, values, aggregateFunction}
    Backend: {index, columns, values, aggregate_function}
    """
    return {
        'index': config.get('index'),
        'columns': config.get('columns'),
        'values': config.get('values'),
        'aggregate_function': config.get('aggregate_function', 'first'),
    }


def convert_rename_config(config: dict) -> dict:
    """Convert rename config from frontend to backend format.

    Frontend: {column_mapping: {oldName: newName}}
    Backend: {mapping: {oldName: newName}}
    """
    mapping = config.get('column_mapping') or config.get('mapping', {})
    if isinstance(mapping, list):
        mapping = {item.get('from'): item.get('to') for item in mapping if item.get('from') and item.get('to')}
    return {'mapping': mapping}


def convert_sort_config(config: dict) -> dict:
    """Convert sort config from frontend to backend format.

    Frontend: [{column: 'col1', descending: false}, {column: 'col2', descending: true}]
    Backend: {columns: ['col1', 'col2'], descending: [false, true]}
    """
    if isinstance(config, list):
        columns = [rule.get('column') for rule in config if rule.get('column')]
        descending = [rule.get('descending', False) for rule in config if rule.get('column')]
        return {'columns': columns, 'descending': descending}

    if 'columns' in config:
        return config

    return {'columns': [], 'descending': []}


def convert_deduplicate_config(config: dict) -> dict:
    """Convert deduplicate config from frontend to backend format.

    Frontend: {columns: [...], keep: 'first'}
    Backend: {subset: [...], keep: 'first'}
    """
    return {
        'subset': config.get('columns') or config.get('subset'),
        'keep': config.get('keep', 'first'),
    }


def convert_timeseries_config(config: dict) -> dict:
    """Convert timeseries config from frontend to backend format.

    Frontend: {column, operationType, newColumn, component, value, unit, column2}
    Backend: {column, operation_type, new_column, component, value, unit, column2}
    """
    return {
        'column': config.get('column'),
        'operation_type': config.get('operation_type'),
        'new_column': config.get('new_column'),
        'component': config.get('component'),
        'value': config.get('value'),
        'unit': config.get('unit'),
        'column2': config.get('column2'),
    }


def convert_string_transform_config(config: dict) -> dict:
    """Convert string_transform config from frontend to backend format.

    Frontend: {column, method, newColumn, pattern, replacement, start, end, delimiter, index, groupIndex}
    Backend: {column, method, new_column, pattern, replacement, start, end, delimiter, index, group_index}
    """
    return {
        'column': config.get('column'),
        'method': config.get('method'),
        'new_column': config.get('new_column') or config.get('column'),
        'pattern': config.get('pattern'),
        'replacement': config.get('replacement'),
        'start': config.get('start'),
        'end': config.get('end'),
        'delimiter': config.get('delimiter'),
        'index': config.get('index'),
        'group_index': config.get('group_index'),
    }


def convert_export_config(config: dict) -> dict:
    """Convert export config from frontend to backend format.

    Frontend: {format, filename, destination, iceberg_options}
    Backend: {format, filename, destination, iceberg_options}
    """
    return {
        'format': config.get('format'),
        'filename': config.get('filename'),
        'destination': config.get('destination'),
        'iceberg_options': config.get('iceberg_options'),
    }


def convert_union_by_name_config(config: dict) -> dict:
    """Convert union_by_name config from frontend to backend format.

    Frontend: {sources: [...], allow_missing: bool} or {sources: [...], allowMissing: bool}
    Backend: {sources: [...], allow_missing: bool}
    """
    return {
        'sources': config.get('sources', []),
        'allow_missing': config.get('allow_missing', True),
    }


def convert_plot_config(config: dict) -> dict:
    return {
        'chart_type': config.get('chart_type', 'bar'),
        'x_column': config.get('x_column', ''),
        'y_column': config.get('y_column'),
        'bins': config.get('bins', 10),
        'aggregation': config.get('aggregation', 'sum'),
        'group_column': config.get('group_column'),
        'group_sort_by': config.get('group_sort_by'),
        'group_sort_order': config.get('group_sort_order', 'asc'),
        'group_sort_column': config.get('group_sort_column'),
        'stack_mode': config.get('stack_mode', 'grouped'),
        'area_opacity': config.get('area_opacity', 0.35),
        'date_bucket': config.get('date_bucket'),
        'date_ordinal': config.get('date_ordinal'),
        'sort_by': config.get('sort_by'),
        'sort_order': config.get('sort_order', 'asc'),
        'sort_column': config.get('sort_column'),
        'x_axis_label': config.get('x_axis_label'),
        'y_axis_label': config.get('y_axis_label'),
        'y_axis_scale': config.get('y_axis_scale', 'linear'),
        'y_axis_min': config.get('y_axis_min'),
        'y_axis_max': config.get('y_axis_max'),
        'display_units': config.get('display_units', ''),
        'decimal_places': config.get('decimal_places', 2),
        'legend_position': config.get('legend_position', 'right'),
        'title': config.get('title'),
        'series_colors': config.get('series_colors', []),
        'overlays': config.get('overlays', []),
        'reference_lines': config.get('reference_lines', []),
        'pan_zoom_enabled': config.get('pan_zoom_enabled', False),
        'selection_enabled': config.get('selection_enabled', False),
        'area_selection_enabled': config.get('area_selection_enabled', False),
    }


def convert_ai_config(config: dict) -> dict:
    raw_options = config.get('request_options')
    # Parse string JSON to dict if needed (frontend sends textarea value as string)
    if isinstance(raw_options, str):
        raw_options = raw_options.strip() or None

    input_columns: list[str] = config.get('input_columns') or []

    result: dict[str, object] = {
        'provider': config.get('provider', 'ollama'),
        'model': config.get('model', 'llama2'),
        'input_columns': input_columns,
        'output_column': config.get('output_column', 'ai_result'),
        'error_column': config.get('error_column', 'ai_error'),
        'prompt_template': config.get('prompt_template', 'Classify this text: {{text}}'),
        'batch_size': config.get('batch_size', 10),
        'max_retries': config.get('max_retries', 3),
        'rate_limit_rpm': config.get('rate_limit_rpm'),
        'endpoint_url': config.get('endpoint_url'),
        'api_key': config.get('api_key'),
        'temperature': config.get('temperature', 0.7),
        'max_tokens': config.get('max_tokens'),
        'request_options': raw_options,
    }
    return result


def convert_notification_config(config: dict) -> dict:
    """Convert notification config — per-row UDF with column inputs."""
    input_columns: list[str] = config.get('input_columns') or []

    selected = config.get('subscriber_ids')
    recipients = config.get('recipient', '') or (','.join(str(cid) for cid in selected) if isinstance(selected, list) else '')

    return {
        'method': config.get('method', 'email'),
        'recipient': recipients,
        'bot_token': config.get('bot_token', ''),
        'subscriber_ids': config.get('subscriber_ids') or [],
        'recipient_column': config.get('recipient_column', ''),
        'input_columns': input_columns,
        'output_column': config.get('output_column', 'notification_status'),
        'message_template': config.get('message_template', '{{message}}'),
        'subject_template': config.get('subject_template', 'Notification'),
        'batch_size': config.get('batch_size', 10),
        'timeout_seconds': config.get('timeout_seconds', 20),
    }


_CONVERTERS: dict[str, Callable[[dict], dict]] = {
    'filter': convert_filter_config,
    'groupby': convert_groupby_config,
    'sort': convert_sort_config,
    'rename': convert_rename_config,
    'join': convert_join_config,
    'deduplicate': convert_deduplicate_config,
    'fill_null': convert_fillnull_config,
    'pivot': convert_pivot_config,
    'timeseries': convert_timeseries_config,
    'string_transform': convert_string_transform_config,
    'export': convert_export_config,
    'union_by_name': convert_union_by_name_config,
    'chart': convert_plot_config,
    'ai': convert_ai_config,
    'notification': convert_notification_config,
}


def convert_config_to_params(operation: str, config: dict) -> dict:
    """Convert operation-specific config to params."""
    converter = _CONVERTERS.get(operation, lambda c: c)
    try:
        return converter(config)
    except Exception as e:
        logger.error(f'Error converting {operation} config: {e}', exc_info=True)
        raise
