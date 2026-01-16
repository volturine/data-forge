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


def convert_config_to_params(operation: str, config: dict) -> dict:
    """Convert operation-specific config to params."""
    converters = {
        'filter': convert_filter_config,
        'select': lambda c: c,  # Direct passthrough
        'groupby': convert_groupby_config,
        'sort': lambda c: c,  # Direct passthrough
        'rename': lambda c: c,  # Direct passthrough
        'drop': lambda c: c,  # Direct passthrough
        'join': convert_join_config,
        'with_columns': lambda c: c,  # Direct passthrough
        'deduplicate': lambda c: c,  # Direct passthrough
        'fill_null': convert_fillnull_config,
        'explode': lambda c: c,  # Direct passthrough
        'pivot': convert_pivot_config,
        'unpivot': lambda c: c,  # Direct passthrough
        'view': lambda c: c,  # Direct passthrough
    }

    converter = converters.get(operation, lambda c: c)
    try:
        return converter(config)
    except Exception as e:
        logger.error(f'Error converting {operation} config: {e}')
        return config  # Return original on error


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
        'aggregations': [{'column': agg.get('column'), 'function': agg.get('function')} for agg in config.get('aggregations', [])],
    }


def convert_join_config(config: dict) -> dict:
    """Convert join config from frontend to backend format.

    Frontend: {rightDataSource, leftOn, rightOn, how}
    Backend: {right_source, left_on, right_on, how}
    """
    return {
        'right_source': config.get('rightDataSource'),
        'left_on': config.get('leftOn'),
        'right_on': config.get('rightOn'),
        'how': config.get('how', 'inner'),
    }


def convert_fillnull_config(config: dict) -> dict:
    """Convert fill_null config from frontend to backend format.

    Frontend: {strategy, value, columns}
    Backend: {strategy, value, columns}
    """
    return {
        'strategy': config.get('strategy', 'value'),
        'value': config.get('value'),
        'columns': config.get('columns', []),
    }


def convert_pivot_config(config: dict) -> dict:
    """Convert pivot config from frontend to backend format.

    Frontend: {index, columns, values, aggregateFunction}
    Backend: {index, columns, values, aggregate_function}
    """
    return {
        'index': config.get('index'),
        'columns': config.get('columns'),
        'values': config.get('values'),
        'aggregate_function': config.get('aggregateFunction', 'sum'),
    }
