import pytest
from pydantic import ValidationError

from backend_core.domain.compute.schemas import StepPreviewRequest
from dataforge_protocol import compute_pb2, enums_pb2
from modules.compute import executor_client, routes as compute_routes


def _preview_payload(engine_identity: dict[str, object]) -> dict[str, object]:
    return {
        'analysis_id': 'analysis-1',
        'engine_identity': engine_identity,
        'target_step_id': 'step-1',
        'analysis_pipeline': {
            'analysis_id': 'analysis-1',
            'tabs': [
                {
                    'id': 'tab-1',
                    'datasource': {
                        'id': 'datasource-1',
                        'analysis_tab_id': 'tab-1',
                        'source_type': 'csv',
                        'config': {'branch': 'main'},
                    },
                    'output': {'result_id': 'result-1', 'filename': 'result.csv', 'format': 'csv'},
                    'steps': [{'id': 'step-1', 'type': 'select', 'config': {'columns': []}}],
                }
            ],
        },
    }


def test_analysis_interactive_engine_identity_uses_generated_proto() -> None:
    identity = compute_routes._analysis_interactive_engine_identity('analysis-1')

    assert isinstance(identity, compute_pb2.EngineIdentity)
    assert identity.scope == enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE
    assert identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_SHARED
    assert identity.analysis_id == 'analysis-1'
    assert not identity.HasField('datasource_id')
    assert not identity.HasField('build_id')


def test_datasource_preview_engine_identity_uses_generated_proto() -> None:
    identity = compute_routes._datasource_preview_engine_identity('ds-1')

    assert isinstance(identity, compute_pb2.EngineIdentity)
    assert identity.scope == enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW
    assert identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_SHARED
    assert not identity.HasField('analysis_id')
    assert identity.datasource_id == 'ds-1'
    assert not identity.HasField('build_id')


def test_build_engine_identity_uses_generated_proto() -> None:
    identity = compute_routes._build_engine_identity('build-1')

    assert isinstance(identity, compute_pb2.EngineIdentity)
    assert identity.scope == enums_pb2.ENGINE_SCOPE_BUILD
    assert identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_EXCLUSIVE
    assert not identity.HasField('analysis_id')
    assert not identity.HasField('datasource_id')
    assert identity.build_id == 'build-1'


def test_engine_identity_payload_is_boundary_conversion() -> None:
    identity = compute_routes._datasource_preview_engine_identity('ds-1')

    assert executor_client._engine_identity_payload(identity) == {
        'scope': 'datasource_preview',
        'reuse_policy': 'shared',
        'resource_id': 'ds-1',
        'datasource_id': 'ds-1',
    }


def test_step_preview_request_uses_generated_engine_identity() -> None:
    request = StepPreviewRequest.model_validate(
        _preview_payload(
            {
                'scope': 'datasource_preview',
                'reuse_policy': 'shared',
                'resource_id': 'datasource-1',
                'datasource_id': 'datasource-1',
            }
        )
    )

    assert isinstance(request.engine_identity, compute_pb2.EngineIdentity)
    assert request.engine_identity.scope == enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW
    assert request.engine_identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_SHARED
    assert request.engine_identity.datasource_id == 'datasource-1'
    assert request.model_dump(mode='json')['engine_identity'] == {
        'scope': 'datasource_preview',
        'reuse_policy': 'shared',
        'resource_id': 'datasource-1',
        'datasource_id': 'datasource-1',
    }


def test_step_preview_request_rejects_invalid_engine_identity_payload() -> None:
    with pytest.raises(ValidationError, match='engine identity datasource_id is required'):
        StepPreviewRequest.model_validate(
            _preview_payload(
                {
                    'scope': 'datasource_preview',
                    'reuse_policy': 'shared',
                    'resource_id': 'datasource-1',
                }
            )
        )
