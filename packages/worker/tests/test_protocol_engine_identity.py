from __future__ import annotations

import pytest
from protovalidate import ValidationError, Validator

from dataforge_protocol import compute_pb2, enums_pb2


def test_step_preview_request_uses_generated_engine_identity() -> None:
    identity = compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        datasource_id="datasource-1",
        resource_id="datasource-1",
    )
    request = compute_pb2.StepPreviewCommand(engine_identity=identity)

    assert isinstance(request.engine_identity, compute_pb2.EngineIdentity)
    assert request.engine_identity.scope == enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW
    assert request.engine_identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_SHARED
    assert request.engine_identity.datasource_id == "datasource-1"
    assert request.engine_identity.resource_id == "datasource-1"


def test_step_preview_request_rejects_invalid_engine_identity_payload() -> None:
    identity = compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        datasource_id="datasource-1",
        resource_id="",
    )

    with pytest.raises(ValidationError):
        Validator().validate(identity)
