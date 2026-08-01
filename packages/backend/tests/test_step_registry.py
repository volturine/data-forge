from __future__ import annotations

from pathlib import Path

from backend_core.domain.analysis.step_types import iter_step_types
from modules.analysis.step_schemas import STEP_CATALOG

FRONTEND_PROTOCOL_ANALYSIS = (
    Path(__file__).resolve().parents[3] / 'packages' / 'frontend' / 'src' / 'lib' / 'protocol' / 'dataforge_protocol' / 'analysis_pb.ts'
)


def test_step_catalog_matches_public_step_types() -> None:
    assert set(STEP_CATALOG) == set(iter_step_types(include_plot_aliases=True))


def test_generated_frontend_protocol_exports_catalog_configs() -> None:
    content = FRONTEND_PROTOCOL_ANALYSIS.read_text()
    for step_type, entry in STEP_CATALOG.items():
        config_model = entry['config']
        assert isinstance(config_model, type)
        model_name = config_model.__name__
        assert f'export type {model_name}' in content, step_type
