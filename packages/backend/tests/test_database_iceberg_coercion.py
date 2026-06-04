from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl

from modules.datasource.runtime_service import _coerce_database_iceberg_compatible_lazyframe


def test_database_iceberg_coercion_stringifies_null_nested_and_timezone_columns():
    lazy = pl.DataFrame(
        {
            'description': [None, None],
            'pipeline_definition': [
                {'tabs': [{'datasource': {'analysis_tab_id': None}}]},
                {'tabs': [{'datasource': {'analysis_tab_id': None}}]},
            ],
            'config': [
                {
                    'catalog_type': 'sql',
                    'source': {
                        'connection_string': 'postgresql://example',
                        'query': 'select 1',
                    },
                },
                {
                    'catalog_type': 'sql',
                    'source': {
                        'connection_string': 'postgresql://example',
                        'query': 'select 2',
                    },
                },
            ],
            'tags': [['one', 'two'], ['three']],
            'created_at': [
                datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo('Europe/Prague')),
                datetime(2024, 7, 1, 12, 0, tzinfo=ZoneInfo('Europe/Prague')),
            ],
            'value': [1, 2],
        },
    ).lazy()

    coerced = _coerce_database_iceberg_compatible_lazyframe(lazy).collect()
    schema = coerced.schema
    assert schema['description'] == pl.String
    assert schema['pipeline_definition'] == pl.String
    assert schema['config'] == pl.String
    assert schema['tags'] == pl.String
    assert schema['created_at'] == pl.Datetime(time_zone='UTC')
    assert schema['value'] == pl.Int64
    assert '"analysis_tab_id": null' in coerced['pipeline_definition'][0]
    assert '"catalog_type": "sql"' in coerced['config'][0]
    assert coerced['tags'][0] == '["one", "two"]'
    assert str(coerced['created_at'][0]) == '2024-01-01 11:00:00+00:00'
    assert str(coerced['created_at'][1]) == '2024-07-01 10:00:00+00:00'
