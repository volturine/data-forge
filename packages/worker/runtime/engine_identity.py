from __future__ import annotations

from dataclasses import dataclass

from dataforge_protocol import compute_pb2, enums_pb2

PREVIEW_PREFIX = "__preview__"
BUILD_PREFIX = "build:"


@dataclass(frozen=True, slots=True)
class EngineIdentity:
    protocol: compute_pb2.EngineIdentity

    @property
    def storage_key(self) -> str:
        return engine_identity_storage_key(self)

    @property
    def scope(self) -> int:
        return self.protocol.scope

    @property
    def reuse_policy(self) -> int:
        return self.protocol.reuse_policy

    @property
    def analysis_id(self) -> str | None:
        return self.protocol.analysis_id if self.protocol.HasField("analysis_id") else None

    @property
    def datasource_id(self) -> str | None:
        return self.protocol.datasource_id if self.protocol.HasField("datasource_id") else None

    @property
    def build_id(self) -> str | None:
        return self.protocol.build_id if self.protocol.HasField("build_id") else None


def _required_id(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def analysis_interactive_engine_identity(analysis_id: str) -> EngineIdentity:
    return EngineIdentity(
        compute_pb2.EngineIdentity(
            scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
            reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
            analysis_id=_required_id(analysis_id, "analysis_id"),
        )
    )


def datasource_preview_engine_identity(datasource_id: str) -> EngineIdentity:
    return EngineIdentity(
        compute_pb2.EngineIdentity(
            scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW,
            reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
            datasource_id=_required_id(datasource_id, "datasource_id"),
        )
    )


def build_engine_identity(build_id: str) -> EngineIdentity:
    return EngineIdentity(
        compute_pb2.EngineIdentity(
            scope=enums_pb2.ENGINE_SCOPE_BUILD,
            reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_EXCLUSIVE,
            build_id=_required_id(build_id, "build_id"),
        )
    )


def engine_identity_storage_key(identity: EngineIdentity) -> str:
    if identity.scope == enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE and identity.analysis_id:
        return identity.analysis_id
    if identity.scope == enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW and identity.datasource_id:
        return f"{PREVIEW_PREFIX}{identity.datasource_id}"
    if identity.scope == enums_pb2.ENGINE_SCOPE_BUILD and identity.build_id:
        return f"{BUILD_PREFIX}{identity.build_id}"
    raise ValueError("engine identity is missing the resource id required by its scope")


def engine_scope_value(identity: EngineIdentity) -> str:
    if identity.scope == enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW:
        return "datasource_preview"
    if identity.scope == enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE:
        return "analysis_interactive"
    if identity.scope == enums_pb2.ENGINE_SCOPE_BUILD:
        return "build"
    raise ValueError("engine identity scope is unspecified")


def engine_reuse_policy_value(identity: EngineIdentity) -> str:
    if identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_SHARED:
        return "shared"
    if identity.reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_EXCLUSIVE:
        return "exclusive"
    raise ValueError("engine identity reuse policy is unspecified")


def analysis_interactive_engine_key(analysis_id: str) -> str:
    return analysis_interactive_engine_identity(analysis_id).storage_key


def datasource_preview_engine_key(datasource_id: str) -> str:
    return datasource_preview_engine_identity(datasource_id).storage_key


def build_engine_key(build_id: str) -> str:
    return build_engine_identity(build_id).storage_key
