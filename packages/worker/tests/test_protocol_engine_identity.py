from __future__ import annotations

import pytest
from pydantic import ValidationError

from dataforge_protocol import compute_pb2, enums_pb2
from runtime.domain.compute.schemas import StepPreviewRequest


def _preview_payload(engine_identity: object) -> dict[str, object]:
    return {
        "analysis_id": "analysis-1",
        "engine_identity": engine_identity,
        "target_step_id": "step-1",
        "analysis_pipeline": {
            "analysis_id": "analysis-1",
            "tabs": [
                {
                    "id": "tab-1",
                    "datasource": {
                        "id": "datasource-1",
                        "analysis_tab_id": "tab-1",
                        "source_type": "csv",
                        "config": {"branch": "main"},
                    },
                    "output": {"result_id": "result-1", "filename": "result.csv", "format": "csv"},
                    "steps": [{"id": "step-1", "type": "select", "config": {"columns": []}}],
                }
            ],
        },
    }


def test_step_preview_request_uses_generated_engine_identity() -> None:
    identity = compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        datasource_id="datasource-1",
    )
    request = StepPreviewRequest.model_validate(_preview_payload(identity))

    assert isinstance(request.engine_identity, compute_pb2.EngineIdentity)
    assert request.engine_identity.scope == enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW
    assert request.engine_identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_SHARED
    assert request.engine_identity.datasource_id == "datasource-1"


def test_step_preview_request_rejects_invalid_engine_identity_payload() -> None:
    with pytest.raises(ValidationError, match="Input should be an instance of EngineIdentity"):
        StepPreviewRequest.model_validate(
            _preview_payload(
                {
                    "scope": "datasource_preview",
                    "reuse_policy": "shared",
                    "resource_id": "datasource-1",
                }
            )
        )
