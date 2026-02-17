from unittest.mock import MagicMock, patch

from modules.compute.engine import PolarsComputeEngine
from modules.compute.utils import apply_pipeline_steps, resolve_applied_target


def test_apply_pipeline_steps_skips_disabled_and_relinks():
    steps = [
        {
            'id': 's1',
            'type': 'filter',
            'config': {'conditions': [{'column': 'col', 'operator': '>', 'value': 1}]},
            'depends_on': [],
        },
        {'id': 's2', 'type': 'notification', 'config': {}, 'depends_on': ['s1'], 'is_applied': False},
        {'id': 's3', 'type': 'select', 'config': {'columns': ['col']}, 'depends_on': ['s2']},
    ]

    applied = apply_pipeline_steps(steps)
    assert [step['id'] for step in applied] == ['s1', 's3']
    assert applied[1].get('depends_on') == ['s1']


def test_resolve_applied_target_returns_parent_when_disabled():
    steps = [
        {'id': 's1', 'type': 'filter', 'config': {}, 'depends_on': []},
        {'id': 's2', 'type': 'select', 'config': {}, 'depends_on': ['s1'], 'is_applied': False},
        {'id': 's3', 'type': 'sort', 'config': {}, 'depends_on': ['s2']},
    ]

    target = resolve_applied_target(steps, 's2')
    assert target == 's1'


@patch('modules.compute.engine.load_datasource')
@patch('modules.compute.engine.PolarsComputeEngine._apply_step')
def test_build_pipeline_skips_disabled_step(mock_apply_step: MagicMock, mock_load: MagicMock):
    fake_lf = MagicMock()
    mock_load.return_value = fake_lf
    mock_apply_step.return_value = fake_lf

    steps: list[dict] = [
        {
            'id': 's1',
            'type': 'filter',
            'config': {'conditions': [{'column': 'col', 'operator': '>', 'value': 1}]},
            'depends_on': [],
        },
        {'id': 's2', 'type': 'notification', 'config': {}, 'depends_on': ['s1'], 'is_applied': False},
        {'id': 's3', 'type': 'select', 'config': {'columns': ['col']}, 'depends_on': ['s2']},
    ]

    result = PolarsComputeEngine.build_pipeline({}, steps, 'job-1')
    assert result == fake_lf
    assert mock_apply_step.call_count == 2
    called_ops = [call.args[1].get('operation') for call in mock_apply_step.call_args_list]
    assert called_ops == ['filter', 'select']
