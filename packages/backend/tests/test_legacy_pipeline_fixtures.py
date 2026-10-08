import json
import runpy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from modules.analysis.step_schemas import (
    get_step_catalog,
    normalize_step_config,
    normalize_step_config_for_protocol,
)

LEGACY_PIPELINE_FIXTURE_DIR = Path(__file__).parent / 'fixtures' / 'legacy_pipelines'
LEGACY_PIPELINE_FIXTURES = tuple(sorted(LEGACY_PIPELINE_FIXTURE_DIR.glob('*.json')))
PIVOT_VALUE_COLUMNS_MIGRATION = Path(__file__).parents[1] / 'database' / 'alembic' / 'versions' / '0024_pivot_value_columns.py'


def _load_pipeline_fixture(path: Path) -> dict[str, Any]:
    fixture = json.loads(path.read_text(encoding='utf-8'))
    assert isinstance(fixture, dict), f'{path.name} must contain a JSON object'
    assert isinstance(fixture.get('source_release'), str), f'{path.name} must identify its source release'
    pipeline_definition = fixture.get('pipeline_definition')
    assert isinstance(pipeline_definition, dict), f'{path.name} must contain pipeline_definition'
    return pipeline_definition


def _pipeline_steps(pipeline_definition: dict[str, Any], fixture_name: str) -> list[dict[str, Any]]:
    tabs = pipeline_definition.get('tabs')
    assert isinstance(tabs, list), f'{fixture_name} must contain a tabs list'
    steps: list[dict[str, Any]] = []
    for tab_index, tab in enumerate(tabs):
        assert isinstance(tab, dict), f'{fixture_name} tab[{tab_index}] must be an object'
        tab_steps = tab.get('steps')
        assert isinstance(tab_steps, list), f'{fixture_name} tab[{tab_index}] must contain a steps list'
        for step_index, step in enumerate(tab_steps):
            assert isinstance(step, dict), f'{fixture_name} tab[{tab_index}] step[{step_index}] must be an object'
            assert isinstance(step.get('type'), str), f'{fixture_name} tab[{tab_index}] step[{step_index}] needs a type'
            assert isinstance(step.get('config'), dict), f'{fixture_name} step type {step["type"]!r} needs a config object'
            steps.append(step)
    return steps


def test_legacy_pipeline_fixtures_cover_every_catalog_step_type() -> None:
    assert LEGACY_PIPELINE_FIXTURES, f'No legacy pipeline fixtures found in {LEGACY_PIPELINE_FIXTURE_DIR}'

    covered_types = {step['type'] for path in LEGACY_PIPELINE_FIXTURES for step in _pipeline_steps(_load_pipeline_fixture(path), path.name)}
    catalog_types: set[str] = set()
    for entry in get_step_catalog():
        step_type = entry['type']
        assert isinstance(step_type, str)
        catalog_types.add(step_type)
    missing_types = sorted(catalog_types - covered_types)

    assert not missing_types, (
        f'Legacy pipeline fixtures do not cover current catalog step types: {", ".join(missing_types)}. Add a fixture for the new release or schema epoch.'
    )


@pytest.mark.parametrize('fixture_path', LEGACY_PIPELINE_FIXTURES, ids=lambda path: path.stem)
def test_legacy_pipeline_configs_normalize_after_data_migrations(fixture_path: Path) -> None:
    pipeline_definition = _load_pipeline_fixture(fixture_path)
    steps_before_migration = _pipeline_steps(pipeline_definition, fixture_path.name)
    legacy_pivot_steps = [step for step in steps_before_migration if step['type'] == 'pivot' and 'values' in step['config']]

    for step in legacy_pivot_steps:
        with pytest.raises(ValidationError, match='values'):
            normalize_step_config('pivot', step['config'])

    migration_applied = False
    if PIVOT_VALUE_COLUMNS_MIGRATION.exists():
        migration = runpy.run_path(str(PIVOT_VALUE_COLUMNS_MIGRATION))
        rewrite_pipeline_definition = migration.get('_rewrite_pipeline_definition')
        if callable(rewrite_pipeline_definition):
            migration_applied = rewrite_pipeline_definition(pipeline_definition, downgrade=False)

    for step in legacy_pivot_steps:
        config = step['config']
        assert migration_applied and 'values' not in config and 'value_columns' in config, (
            f'{fixture_path.name}: step type "pivot" still has obsolete config key "values" after applying persisted-pipeline data migrations'
        )

    for step_index, step in enumerate(_pipeline_steps(pipeline_definition, fixture_path.name)):
        step_type = step['type']
        config = step['config']
        config_keys = sorted(config)

        try:
            normalized = normalize_step_config(step_type, config)
        except Exception as exc:
            pytest.fail(
                f'{fixture_path.name}: step[{step_index}] type={step_type!r} config keys={config_keys!r} failed normalize_step_config after migrations: {exc}',
                pytrace=False,
            )
        assert isinstance(normalized, dict)

        try:
            protocol_config = normalize_step_config_for_protocol(step_type, config)
        except Exception as exc:
            pytest.fail(
                f'{fixture_path.name}: step[{step_index}] type={step_type!r} config keys={config_keys!r} '
                f'failed normalize_step_config_for_protocol after migrations: {exc}',
                pytrace=False,
            )
        assert isinstance(protocol_config, dict)
