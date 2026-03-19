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

logger = logging.getLogger(__name__)


def convert_step_format(frontend_step: dict) -> dict:
    """Convert frontend step format to backend engine format."""
    step_type = frontend_step.get('type')
    if not step_type:
        raise ValueError('Step must have a type field')

    config = frontend_step.get('config', {})
    if step_type in _CHART_TYPES:
        config = {**config, 'chart_type': _CHART_TYPES[step_type]}
    normalized_type = 'chart' if step_type.startswith('plot_') else step_type

    return {
        'name': frontend_step.get('id', 'Unknown Step'),
        'operation': normalized_type,
        'params': convert_config_to_params(normalized_type, config),
    }


def convert_filter_config(config: dict) -> dict:
    """Convert filter config from frontend format to backend format.

    Frontend: {conditions: [{column, operator, value, value_type?, compare_column?}], logic: "AND"}
    Backend: {conditions: [{column, operator, value, value_type, compare_column?}], logic: "AND"}

    Supports multiple conditions with AND/OR logic.
    Supports typed values (string, number, date, datetime, column) and NULL checks.
    """
    conditions = config.get('conditions', [])
    if not conditions:
        raise ValueError('Filter requires at least one condition')

    converted = []
    for cond in conditions:
        item = {
            'column': cond.get('column', ''),
            'operator': cond.get('operator', '='),
            'value': cond.get('value'),
            'value_type': cond.get('value_type', 'string'),
        }
        if cond.get('compare_column'):
            item['compare_column'] = cond['compare_column']
        converted.append(item)

    return {'conditions': converted, 'logic': config.get('logic', 'AND')}


def convert_groupby_config(config: dict) -> dict:
    """Convert groupby config from frontend to backend format.

    Frontend: {groupBy: [...], aggregations: [{column, function, alias}]}
    Backend: {group_by: [...], aggregations: [{column, function}]}
    """
    return {
        'group_by': config.get('groupBy', []),
        'aggregations': [
            {
                'column': agg.get('column'),
                'function': agg.get('function') or agg.get('agg'),
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
    if how == 'outer':
        how = 'full'
    return {
        'right_source': config.get('right_source') or config.get('rightDataSource'),
        'join_columns': join_columns,
        'right_columns': right_columns,
        'how': how,
        'suffix': config.get('suffix', '_right'),
    }


def convert_fillnull_config(config: dict) -> dict:
    """Convert fill_null config from frontend to backend format.

    Frontend: {strategy, value, columns}
    Backend: {strategy, value, columns}
    """
    strategy = config.get('strategy', 'literal')
    if strategy == 'value':
        strategy = 'literal'
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
        # Support both camelCase and snake_case
        'aggregate_function': config.get('aggregate_function') or config.get('aggregateFunction', 'first'),
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
        'operation_type': config.get('operationType') or config.get('operation_type'),
        'new_column': config.get('newColumn') or config.get('new_column'),
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
        'new_column': config.get('newColumn') or config.get('new_column') or config.get('column'),
        'pattern': config.get('pattern'),
        'replacement': config.get('replacement'),
        'start': config.get('start'),
        'end': config.get('end'),
        'delimiter': config.get('delimiter'),
        'index': config.get('index'),
        'group_index': config.get('groupIndex') or config.get('group_index'),
    }


def convert_export_config(config: dict) -> dict:
    """Convert export config from frontend to backend format.

    Frontend: {format, filename, destination, iceberg_options}
    Backend: {format, filename, destination, iceberg_options}
    """
    return {
        'format': config.get('format', 'csv'),
        'filename': config.get('filename', 'export'),
        'destination': config.get('destination', 'download'),
        'iceberg_options': config.get('iceberg_options'),
    }


def convert_union_by_name_config(config: dict) -> dict:
    """Convert union_by_name config from frontend to backend format.

    Frontend: {sources: [...], allow_missing: bool} or {sources: [...], allowMissing: bool}
    Backend: {sources: [...], allow_missing: bool}
    """
    return {
        'sources': config.get('sources', []),
        'allow_missing': config.get('allow_missing', config.get('allowMissing', True)),
    }


def convert_plot_config(config: dict) -> dict:
    return {
        'chart_type': config.get('chart_type') or config.get('chartType') or 'bar',
        'x_column': config.get('x_column') or config.get('xColumn') or '',
        'y_column': config.get('y_column') or config.get('yColumn'),
        'bins': config.get('bins', 10),
        'aggregation': config.get('aggregation', 'sum'),
        'group_column': config.get('group_column') or config.get('groupColumn'),
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


_CHART_TYPES: dict[str, str] = {
    'plot_bar': 'bar',
    'plot_horizontal_bar': 'horizontal_bar',
    'plot_area': 'area',
    'plot_heatgrid': 'heatgrid',
    'plot_histogram': 'histogram',
    'plot_scatter': 'scatter',
    'plot_line': 'line',
    'plot_pie': 'pie',
    'plot_boxplot': 'boxplot',
}


def convert_ai_config(config: dict) -> dict:
    raw_options = config.get('request_options') or config.get('requestOptions')
    # Parse string JSON to dict if needed (frontend sends textarea value as string)
    if isinstance(raw_options, str):
        raw_options = raw_options.strip() or None

    # Support both legacy input_column (singular) and input_columns (plural)
    input_columns: list[str] = config.get('input_columns') or config.get('inputColumns') or []
    if (legacy_col := config.get('input_column') or config.get('inputColumn')) and legacy_col not in input_columns:
        input_columns = [legacy_col, *input_columns]

    result: dict[str, object] = {
        'provider': config.get('provider', 'ollama'),
        'model': config.get('model', 'llama2'),
        'input_columns': input_columns,
        'output_column': config.get('output_column') or config.get('outputColumn') or 'ai_result',
        'prompt_template': config.get('prompt_template') or config.get('promptTemplate') or 'Classify this text: {{text}}',
        'batch_size': config.get('batch_size', 10),
        'endpoint_url': config.get('endpoint_url') or config.get('endpointUrl'),
        'api_key': config.get('api_key') or config.get('apiKey'),
        'request_options': raw_options,
    }
    return result


def convert_notification_config(config: dict) -> dict:
    """Convert notification config — per-row UDF with column inputs."""
    input_columns: list[str] = config.get('input_columns') or config.get('inputColumns') or []

    selected = config.get('subscriber_ids')
    recipients = config.get('recipient', '') or (','.join(str(cid) for cid in selected) if isinstance(selected, list) else '')

    return {
        'method': config.get('method', 'email'),
        'recipient': recipients,
        'bot_token': config.get('bot_token', ''),
        'subscriber_ids': config.get('subscriber_ids') or [],
        'recipient_column': config.get('recipient_column') or config.get('recipientColumn') or '',
        'input_columns': input_columns,
        'output_column': config.get('output_column') or config.get('outputColumn') or 'notification_status',
        'message_template': config.get('message_template') or config.get('messageTemplate') or '{{message}}',
        'subject_template': config.get('subject_template') or config.get('subjectTemplate') or 'Notification',
        'batch_size': config.get('batch_size', 10),
        'timeout_seconds': config.get('timeout_seconds', 20),
    }


_CONVERTERS: dict = {
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
