"""Example usage of the Polars Compute Engine.

This demonstrates how to use the compute module to execute
data transformations in isolated subprocesses.
"""

# Example pipeline steps configuration
example_pipeline = [
    {'name': 'Filter high values', 'operation': 'filter', 'params': {'expression': {'column': 'value', 'value': 100}}},
    {'name': 'Select columns', 'operation': 'select', 'params': {'columns': ['id', 'name', 'value']}},
    {'name': 'Sort by value', 'operation': 'sort', 'params': {'columns': ['value'], 'descending': True}},
    {
        'name': 'Group by category',
        'operation': 'groupby',
        'params': {
            'group_by': ['category'],
            'aggregations': [
                {'column': 'value', 'function': 'sum'},
                {'column': 'value', 'function': 'mean'},
                {'column': 'id', 'function': 'count'},
            ],
        },
    },
]

# API Usage Examples:

# 1. Execute a full analysis pipeline
"""
POST /api/v1/compute/execute
{
    "datasource_id": "uuid-of-datasource",
    "pipeline_steps": [
        {
            "name": "Filter data",
            "operation": "filter",
            "params": {"expression": {"column": "age", "value": 18}}
        },
        {
            "name": "Select columns",
            "operation": "select",
            "params": {"columns": ["name", "age", "city"]}
        }
    ]
}

Response:
{
    "job_id": "uuid-of-job",
    "status": "pending",
    "progress": 0.0,
    "current_step": null,
    "error_message": null,
    "process_id": 12345
}
"""

# 2. Check job status
"""
GET /api/v1/compute/status/{job_id}

Response:
{
    "job_id": "uuid-of-job",
    "status": "running",
    "progress": 0.5,
    "current_step": "Select columns",
    "error_message": null,
    "process_id": 12345
}
"""

# 3. Get job result (when completed)
"""
GET /api/v1/compute/result/{job_id}

Response:
{
    "job_id": "uuid-of-job",
    "status": "completed",
    "data": {
        "schema": {
            "name": "String",
            "age": "Int64",
            "city": "String"
        },
        "row_count": 1500,
        "sample_data": [
            {"name": "Alice", "age": 25, "city": "NYC"},
            {"name": "Bob", "age": 30, "city": "LA"}
        ]
    },
    "error": null
}
"""

# 4. Preview a specific step
"""
POST /api/v1/compute/preview
{
    "datasource_id": "uuid-of-datasource",
    "pipeline_steps": [...],
    "step_index": 0
}

Response:
{
    "schema": {"column": "String", ...},
    "row_count": 500,
    "sample_data": [...]
}
"""

# 5. Cancel a running job
"""
DELETE /api/v1/compute/{job_id}

Response:
{
    "message": "Job {job_id} cancelled successfully"
}
"""

# Supported Operations:

operations_reference = {
    'filter': {
        'description': 'Filter rows based on column condition',
        'params': {'expression': {'column': 'column_name', 'value': 'comparison_value'}},
    },
    'select': {'description': 'Select specific columns', 'params': {'columns': ['col1', 'col2', 'col3']}},
    'groupby': {
        'description': 'Group by columns and aggregate',
        'params': {
            'group_by': ['category'],
            'aggregations': [
                {'column': 'value', 'function': 'sum'},
                {'column': 'value', 'function': 'mean'},
                {'column': 'value', 'function': 'count'},
                {'column': 'value', 'function': 'min'},
                {'column': 'value', 'function': 'max'},
            ],
        },
    },
    'sort': {'description': 'Sort by columns', 'params': {'columns': ['col1', 'col2'], 'descending': False}},
    'rename': {'description': 'Rename columns', 'params': {'mapping': {'old_name': 'new_name', 'another_old': 'another_new'}}},
    'with_columns': {
        'description': 'Add new columns',
        'params': {
            'expressions': [
                {'name': 'new_col', 'type': 'literal', 'value': 100},
                {'name': 'copy_col', 'type': 'column', 'column': 'existing_col'},
            ]
        },
    },
    'drop': {'description': 'Drop columns', 'params': {'columns': ['col1', 'col2']}},
}
