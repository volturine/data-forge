from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

PREVIEW_PREFIX = '__preview__'
BUILD_PREFIX = 'build:'


class EngineScope(StrEnum):
    DATASOURCE_PREVIEW = 'datasource_preview'
    ANALYSIS_INTERACTIVE = 'analysis_interactive'
    BUILD = 'build'


class EngineReusePolicy(StrEnum):
    SHARED = 'shared'
    EXCLUSIVE = 'exclusive'


@dataclass(frozen=True, slots=True)
class EngineIdentity:
    engine_key: str
    scope: EngineScope
    reuse_policy: EngineReusePolicy
    analysis_id: str | None = None
    datasource_id: str | None = None
    build_id: str | None = None


def datasource_preview_engine_key(datasource_id: str) -> str:
    value = datasource_id.strip()
    if not value:
        raise ValueError('datasource_id is required')
    return f'{PREVIEW_PREFIX}{value}'


def analysis_interactive_engine_key(analysis_id: str) -> str:
    value = analysis_id.strip()
    if not value:
        raise ValueError('analysis_id is required')
    return value


def build_engine_key(build_id: str) -> str:
    value = build_id.strip()
    if not value:
        raise ValueError('build_id is required')
    return f'{BUILD_PREFIX}{value}'


def is_datasource_preview_engine_key(engine_key: str) -> bool:
    return engine_key.startswith(PREVIEW_PREFIX) and bool(engine_key[len(PREVIEW_PREFIX) :].strip())


def is_build_engine_key(engine_key: str) -> bool:
    return engine_key.startswith(BUILD_PREFIX) and bool(engine_key[len(BUILD_PREFIX) :].strip())


def parse_engine_identity(engine_key: str) -> EngineIdentity:
    value = engine_key.strip()
    if not value:
        raise ValueError('engine_key is required')
    if is_datasource_preview_engine_key(value):
        return EngineIdentity(
            engine_key=value,
            scope=EngineScope.DATASOURCE_PREVIEW,
            reuse_policy=EngineReusePolicy.SHARED,
            datasource_id=value[len(PREVIEW_PREFIX) :],
        )
    if is_build_engine_key(value):
        return EngineIdentity(
            engine_key=value,
            scope=EngineScope.BUILD,
            reuse_policy=EngineReusePolicy.EXCLUSIVE,
            build_id=value[len(BUILD_PREFIX) :],
        )
    return EngineIdentity(
        engine_key=value,
        scope=EngineScope.ANALYSIS_INTERACTIVE,
        reuse_policy=EngineReusePolicy.SHARED,
        analysis_id=value,
    )


__all__ = [
    'BUILD_PREFIX',
    'EngineIdentity',
    'EngineReusePolicy',
    'EngineScope',
    'PREVIEW_PREFIX',
    'analysis_interactive_engine_key',
    'build_engine_key',
    'datasource_preview_engine_key',
    'is_build_engine_key',
    'is_datasource_preview_engine_key',
    'parse_engine_identity',
]
