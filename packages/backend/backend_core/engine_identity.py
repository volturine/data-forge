from __future__ import annotations

from dataclasses import dataclass

from dataforge_protocol import compute_pb2, enums_pb2


@dataclass(frozen=True, slots=True)
class EngineIdentity:
    protocol: compute_pb2.EngineIdentity

    @property
    def resource_id(self) -> str:
        return engine_identity_resource_id(self)

    @property
    def scope(self) -> int:
        return self.protocol.scope

    @property
    def reuse_policy(self) -> int:
        return self.protocol.reuse_policy

    @property
    def analysis_id(self) -> str | None:
        return self.protocol.analysis_id if self.protocol.HasField('analysis_id') else None

    @property
    def datasource_id(self) -> str | None:
        return self.protocol.datasource_id if self.protocol.HasField('datasource_id') else None

    @property
    def build_id(self) -> str | None:
        return self.protocol.build_id if self.protocol.HasField('build_id') else None


def _required_id(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f'{field_name} is required')
    return normalized


def analysis_interactive_engine_identity(analysis_id: str) -> EngineIdentity:
    return EngineIdentity(
        compute_pb2.EngineIdentity(
            scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
            reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
            analysis_id=_required_id(analysis_id, 'analysis_id'),
        )
    )


def datasource_preview_engine_identity(datasource_id: str) -> EngineIdentity:
    return EngineIdentity(
        compute_pb2.EngineIdentity(
            scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW,
            reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
            datasource_id=_required_id(datasource_id, 'datasource_id'),
        )
    )


def build_engine_identity(build_id: str) -> EngineIdentity:
    return EngineIdentity(
        compute_pb2.EngineIdentity(
            scope=enums_pb2.ENGINE_SCOPE_BUILD,
            reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_EXCLUSIVE,
            build_id=_required_id(build_id, 'build_id'),
        )
    )


def engine_identity_resource_id(identity: EngineIdentity) -> str:
    if identity.scope == enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE and identity.analysis_id:
        return identity.analysis_id
    if identity.scope == enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW and identity.datasource_id:
        return identity.datasource_id
    if identity.scope == enums_pb2.ENGINE_SCOPE_BUILD and identity.build_id:
        return identity.build_id
    raise ValueError('engine identity is missing the resource id required by its scope')


def engine_identity_payload(identity: EngineIdentity) -> dict[str, str]:
    payload = {
        'scope': engine_scope_value(identity),
        'reuse_policy': engine_reuse_policy_value(identity),
        'resource_id': identity.resource_id,
    }
    if identity.analysis_id is not None:
        payload['analysis_id'] = identity.analysis_id
    if identity.datasource_id is not None:
        payload['datasource_id'] = identity.datasource_id
    if identity.build_id is not None:
        payload['build_id'] = identity.build_id
    return payload


def engine_identity_from_payload(payload: dict[str, object]) -> EngineIdentity:
    scope = payload.get('scope')
    if scope == 'analysis_interactive':
        return analysis_interactive_engine_identity(_required_payload_id(payload, 'analysis_id'))
    if scope == 'datasource_preview':
        return datasource_preview_engine_identity(_required_payload_id(payload, 'datasource_id'))
    if scope == 'build':
        return build_engine_identity(_required_payload_id(payload, 'build_id'))
    raise ValueError('engine identity scope is invalid')


def _required_payload_id(payload: dict[str, object], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str):
        raise ValueError(f'engine identity {field_name} is required')
    return _required_id(value, field_name)


def engine_scope_value(identity: EngineIdentity) -> str:
    if identity.scope == enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW:
        return 'datasource_preview'
    if identity.scope == enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE:
        return 'analysis_interactive'
    if identity.scope == enums_pb2.ENGINE_SCOPE_BUILD:
        return 'build'
    raise ValueError('engine identity scope is unspecified')


def engine_reuse_policy_value(identity: EngineIdentity) -> str:
    if identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_SHARED:
        return 'shared'
    if identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_EXCLUSIVE:
        return 'exclusive'
    raise ValueError('engine identity reuse policy is unspecified')


__all__ = [
    'EngineIdentity',
    'analysis_interactive_engine_identity',
    'build_engine_identity',
    'datasource_preview_engine_identity',
    'engine_identity_from_payload',
    'engine_identity_payload',
    'engine_identity_resource_id',
    'engine_reuse_policy_value',
    'engine_scope_value',
]
