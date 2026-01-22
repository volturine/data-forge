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

    step_id = frontend_step.get('id', 'Unknown Step')
    config = frontend_step.get('config', {})

    return {
        'name': step_id,
        'operation': step_type,
        'params': convert_config_to_params(step_type, config),
    }


def convert_filter_config(config: dict) -> dict:
    """Convert filter config from frontend format to backend format.

    Frontend: {conditions: [{column, operator, value}], logic: "AND"}
    Backend: {conditions: [{column, operator, value}], logic: "AND"}

    Supports multiple conditions with AND/OR logic.
    """
    conditions = config.get('conditions', [])
    if not conditions:
        raise ValueError('Filter requires at least one condition')

    return {'conditions': conditions, 'logic': config.get('logic', 'AND')}


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

    return {
        'right_source': config.get('right_source') or config.get('rightDataSource'),
        'join_columns': join_columns,
        'right_columns': right_columns,
        'how': config.get('how', 'inner'),
        'suffix': config.get('suffix', '_right'),
    }


def convert_fillnull_config(config: dict) -> dict:
    """Convert fill_null config from frontend to backend format.

    Frontend: {strategy, value, columns}
    Backend: {strategy, value, columns}
    """
    return {
        'strategy': config.get('strategy', 'value'),
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
    # Support both column_mapping (frontend) and mapping (backend format)
    mapping = config.get('column_mapping') or config.get('mapping', {})
    normalized = mapping
    if isinstance(mapping, list):
        normalized = {item.get('from'): item.get('to') for item in mapping if item.get('from') and item.get('to')}
    return {'mapping': normalized}


def convert_sort_config(config: dict) -> dict:
    """Convert sort config from frontend to backend format.

    Frontend: [{column: 'col1', descending: false}, {column: 'col2', descending: true}]
    Backend: {columns: ['col1', 'col2'], descending: [false, true]}
    """
    # If config is already a list (frontend format)
    if isinstance(config, list):
        columns = [rule.get('column') for rule in config if rule.get('column')]
        descending = [rule.get('descending', False) for rule in config if rule.get('column')]
        return {'columns': columns, 'descending': descending}

    # If config is a dict, check if it has the 'columns' key (already backend format)
    if 'columns' in config:
        return config

    # Empty or invalid config
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


def convert_sample_config(config: dict) -> dict:
    """Convert sample config from frontend to backend format.

    Frontend: {mode, n, fraction, shuffle, seed}
    Backend: {n, fraction, shuffle, seed}
    """
    mode = config.get('mode')
    n = config.get('n') if mode != 'fraction' else None
    fraction = config.get('fraction') if mode != 'n' else None
    return {
        'n': n,
        'fraction': fraction,
        'shuffle': config.get('shuffle', False),
        'seed': config.get('seed'),
    }


def convert_limit_config(config: dict) -> dict:
    """Convert limit config from frontend to backend format.

    Frontend: {n}
    Backend: {n}
    """
    return {
        'n': config.get('n', 10),
    }


def convert_topk_config(config: dict) -> dict:
    """Convert topk config from frontend to backend format.

    Frontend: {column, k, descending}
    Backend: {column, k, descending}
    """
    return {
        'column': config.get('column'),
        'k': config.get('k', 10),
        'descending': config.get('descending', False),
    }


def convert_value_counts_config(config: dict) -> dict:
    """Convert value_counts config from frontend to backend format.

    Frontend: {column, normalize, sort}
    Backend: {column, normalize, sort}
    """
    return {
        'column': config.get('column'),
        'normalize': config.get('normalize', False),
        'sort': config.get('sort', True),
    }


def convert_export_config(config: dict) -> dict:
    """Convert export config from frontend to backend format.

    Frontend: {format, filename, destination}
    Backend: {format, filename, destination}
    """
    return {
        'format': config.get('format', 'csv'),
        'filename': config.get('filename', 'export'),
        'destination': config.get('destination', 'download'),
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


def get_converters() -> dict:
    """Return all converters dictionary."""
    return {
        'filter': convert_filter_config,
        'select': lambda c: c,
        'groupby': convert_groupby_config,
        'sort': convert_sort_config,
        'rename': convert_rename_config,
        'drop': lambda c: c,
        'join': convert_join_config,
        'with_columns': lambda c: c,
        'deduplicate': convert_deduplicate_config,
        'fill_null': convert_fillnull_config,
        'explode': lambda c: c,
        'pivot': convert_pivot_config,
        'unpivot': lambda c: c,
        'view': lambda c: c,
        'timeseries': convert_timeseries_config,
        'string_transform': convert_string_transform_config,
        'sample': convert_sample_config,
        'limit': convert_limit_config,
        'topk': convert_topk_config,
        'null_count': lambda c: c,
        'value_counts': convert_value_counts_config,
        'export': convert_export_config,
        'union_by_name': convert_union_by_name_config,
    }


def convert_config_to_params(operation: str, config: dict) -> dict:
    """Convert operation-specific config to params."""
    converters = get_converters()
    converter = converters.get(operation, lambda c: c)
    try:
        return converter(config)
    except Exception as e:
        logger.error(f'Error converting {operation} config: {e}')
        return config if isinstance(config, dict) else {}
