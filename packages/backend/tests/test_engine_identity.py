from backend_core.engine_identity import (
    EngineReusePolicy,
    EngineScope,
    analysis_interactive_engine_key,
    build_engine_key,
    datasource_preview_engine_key,
    parse_engine_identity,
)


def test_parse_analysis_interactive_engine_identity() -> None:
    identity = parse_engine_identity(analysis_interactive_engine_key('analysis-1'))

    assert identity.engine_key == 'analysis-1'
    assert identity.scope == EngineScope.ANALYSIS_INTERACTIVE
    assert identity.reuse_policy == EngineReusePolicy.SHARED
    assert identity.analysis_id == 'analysis-1'
    assert identity.datasource_id is None
    assert identity.build_id is None


def test_parse_datasource_preview_engine_identity() -> None:
    identity = parse_engine_identity(datasource_preview_engine_key('ds-1'))

    assert identity.engine_key == '__preview__ds-1'
    assert identity.scope == EngineScope.DATASOURCE_PREVIEW
    assert identity.reuse_policy == EngineReusePolicy.SHARED
    assert identity.analysis_id is None
    assert identity.datasource_id == 'ds-1'
    assert identity.build_id is None


def test_parse_build_engine_identity() -> None:
    identity = parse_engine_identity(build_engine_key('build-1'))

    assert identity.engine_key == 'build:build-1'
    assert identity.scope == EngineScope.BUILD
    assert identity.reuse_policy == EngineReusePolicy.EXCLUSIVE
    assert identity.analysis_id is None
    assert identity.datasource_id is None
    assert identity.build_id == 'build-1'
