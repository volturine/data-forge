from dataforge_protocol import compute_pb2, enums_pb2
from modules.compute import executor_client, routes as compute_routes


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


def test_engine_identity_from_payload_is_boundary_conversion() -> None:
    identity = compute_routes._engine_identity_from_payload(
        {
            'scope': 'build',
            'reuse_policy': 'exclusive',
            'resource_id': 'build-1',
            'build_id': 'build-1',
        }
    )

    assert isinstance(identity, compute_pb2.EngineIdentity)
    assert identity.scope == enums_pb2.ENGINE_SCOPE_BUILD
    assert identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_EXCLUSIVE
    assert identity.build_id == 'build-1'
