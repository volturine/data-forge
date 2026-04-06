import dataclasses

import pytest

from modules.compute.step_converter import (
    BackendStep,
    FrontendStep,
    convert_filter_config,
    convert_groupby_config,
    convert_rename_config,
    convert_step_format,
)


def test_convert_groupby_config_prefers_group_by() -> None:
    result = convert_groupby_config(
        {
            'group_by': ['team'],
            'groupBy': ['legacy_team'],
            'aggregations': [{'column': 'score', 'function': 'sum', 'alias': 'total'}],
        },
    )
    assert result['group_by'] == ['team']
    assert result['aggregations'] == [{'column': 'score', 'function': 'sum', 'alias': 'total'}]


def test_convert_groupby_config_falls_back_to_legacy_groupby() -> None:
    result = convert_groupby_config(
        {
            'groupBy': ['team'],
            'aggregations': [{'column': 'score', 'function': 'sum'}],
        },
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
                },
            ],
            'logic': 'AND',
        },
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
        },
    )

    assert result == {
        'conditions': [
            {
                'column': 'age',
                'operator': '>',
                'value': 30,
                'value_type': 'number',
            },
        ],
        'logic': 'AND',
    }


def test_convert_step_format_returns_frozen_backend_step_dataclass() -> None:
    step = convert_step_format(
        {
            'id': 'step-1',
            'type': 'plot_scatter',
            'config': {'x_column': 'age', 'y_column': 'score'},
            'depends_on': ['step-0'],
            'is_applied': True,
        },
    )

    assert isinstance(step, BackendStep)
    assert dataclasses.is_dataclass(step)
    assert step.name == 'step-1'
    assert step.operation == 'chart'
    assert step.params['chart_type'] == 'scatter'

    with pytest.raises(dataclasses.FrozenInstanceError):
        step.operation = 'filter'  # type: ignore[misc]


def test_frontend_step_from_mapping_rejects_missing_type() -> None:
    with pytest.raises(ValueError, match='Step must have a type field'):
        FrontendStep.from_mapping({'id': 'step-1'})
