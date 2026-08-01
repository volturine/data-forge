from __future__ import annotations

from operations import HANDLERS, PARAM_MODELS, OperationParams
from runtime.domain.analysis.step_types import iter_step_types, normalize_step_type


def test_worker_handler_and_parameter_registries_cover_step_types() -> None:
    operations = {normalize_step_type(step_type) for step_type in iter_step_types(include_plot_aliases=True)}
    assert set(HANDLERS) == operations
    assert set(PARAM_MODELS) == operations
    for _operation, params_model in PARAM_MODELS.items():
        assert issubclass(params_model, OperationParams)
