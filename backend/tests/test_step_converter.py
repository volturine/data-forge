from modules.compute.step_converter import convert_filter_config, convert_groupby_config, convert_rename_config


def test_convert_groupby_config_prefers_group_by() -> None:
    result = convert_groupby_config(
        {
            'group_by': ['team'],
            'groupBy': ['legacy_team'],
            'aggregations': [{'column': 'score', 'function': 'sum', 'alias': 'total'}],
        }
    )
    assert result['group_by'] == ['team']
    assert result['aggregations'] == [{'column': 'score', 'function': 'sum', 'alias': 'total'}]


def test_convert_groupby_config_falls_back_to_legacy_groupby() -> None:
    result = convert_groupby_config(
        {
            'groupBy': ['team'],
            'aggregations': [{'column': 'score', 'function': 'sum'}],
        }
    )
    assert result['group_by'] == ['team']
    assert result['aggregations'] == [{'column': 'score', 'function': 'sum', 'alias': None}]


def test_convert_rename_config_accepts_column_mapping_and_mapping() -> None:
    by_column_mapping = convert_rename_config({'column_mapping': {'old': 'new'}})
    by_mapping = convert_rename_config({'mapping': {'old': 'new'}})

    assert by_column_mapping == {'mapping': {'old': 'new'}}
    assert by_mapping == {'mapping': {'old': 'new'}}


def test_convert_filter_config_ignores_blank_placeholder_conditions() -> None:
    result = convert_filter_config(
        {
            'conditions': [
                {
                    'column': '',
                    'operator': '=',
                    'value': '',
                    'value_type': 'string',
                }
            ],
            'logic': 'AND',
        }
    )

    assert result == {'conditions': [], 'logic': 'AND'}


def test_convert_filter_config_keeps_valid_conditions_when_placeholders_present() -> None:
    result = convert_filter_config(
        {
            'conditions': [
                {
                    'column': '',
                    'operator': '=',
                    'value': '',
                    'value_type': 'string',
                },
                {
                    'column': 'age',
                    'operator': '>',
                    'value': 30,
                    'value_type': 'number',
                },
            ],
            'logic': 'AND',
        }
    )

    assert result == {
        'conditions': [
            {
                'column': 'age',
                'operator': '>',
                'value': 30,
                'value_type': 'number',
            }
        ],
        'logic': 'AND',
    }
