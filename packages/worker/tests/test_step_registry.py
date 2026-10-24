from __future__ import annotations

from operations import OPERATIONS, PARAM_MODELS, OperationParams
from runtime.domain.analysis.step_types import STEP_TYPES


def test_worker_operation_and_parameter_registries_cover_step_types() -> None:
    operations = {STEP_TYPES.normalized(step_type) for step_type in STEP_TYPES.all()}
    assert set(OPERATIONS) == operations
    assert set(PARAM_MODELS) == operations
    for params_model in PARAM_MODELS.values():
        assert issubclass(params_model, OperationParams)
