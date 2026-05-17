from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from contracts.analysis.step_types import iter_step_types, normalize_step_type

from modules.analysis.step_schemas import STEP_CATALOG

ROOT = Path(__file__).resolve().parents[3]
WORKER_ROOT = ROOT / "packages" / "worker-manager"
FRONTEND_STEP_TYPES = ROOT / "packages" / "frontend" / "src" / "lib" / "types" / "step-schemas.generated.ts"


def _load_worker_module(name: str, path: Path):
    sys.path.insert(0, str(WORKER_ROOT))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(WORKER_ROOT))


def test_step_catalog_matches_public_step_types() -> None:
    assert set(STEP_CATALOG) == set(iter_step_types(include_plot_aliases=True))


def test_worker_converter_and_handler_registries_cover_catalog() -> None:
    converter = _load_worker_module("step_converter_registry_test", WORKER_ROOT / "operations" / "step_converter.py")
    operations = {normalize_step_type(step_type) for step_type in STEP_CATALOG}
    assert set(converter._CONVERTERS) == operations

    compute_operations = _load_worker_module(
        "compute_operations_registry_test",
        WORKER_ROOT / "operations" / "__init__.py",
    )
    assert set(compute_operations.HANDLERS) == operations


def test_generated_frontend_step_schema_exports_catalog_configs() -> None:
    content = FRONTEND_STEP_TYPES.read_text()
    for step_type, entry in STEP_CATALOG.items():
        config_model = entry["config"]
        assert isinstance(config_model, type)
        model_name = config_model.__name__
        assert f"export interface {model_name}" in content or f"export type {model_name}" in content, step_type
