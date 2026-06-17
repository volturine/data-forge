from backend_core.engine_identity import (
    analysis_interactive_engine_identity,
    build_engine_identity,
    datasource_preview_engine_identity,
    engine_identity_payload,
)
from dataforge_protocol import enums_pb2


def test_analysis_interactive_engine_identity() -> None:
    identity = analysis_interactive_engine_identity('analysis-1')

    assert identity.resource_id == 'analysis-1'
    assert identity.scope == enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE
    assert identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_SHARED
    assert identity.analysis_id == 'analysis-1'
    assert identity.datasource_id is None
    assert identity.build_id is None


def test_datasource_preview_engine_identity() -> None:
    identity = datasource_preview_engine_identity('ds-1')

    assert identity.resource_id == 'ds-1'
    assert identity.scope == enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW
    assert identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_SHARED
    assert identity.analysis_id is None
    assert identity.datasource_id == 'ds-1'
    assert identity.build_id is None


def test_build_engine_identity() -> None:
    identity = build_engine_identity('build-1')

    assert identity.resource_id == 'build-1'
    assert identity.scope == enums_pb2.ENGINE_SCOPE_BUILD
    assert identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_EXCLUSIVE
    assert identity.analysis_id is None
    assert identity.datasource_id is None
    assert identity.build_id == 'build-1'


def test_engine_identity_payload_is_structured() -> None:
    assert engine_identity_payload(datasource_preview_engine_identity('ds-1')) == {
        'scope': 'datasource_preview',
        'reuse_policy': 'shared',
        'resource_id': 'ds-1',
        'datasource_id': 'ds-1',
    }
