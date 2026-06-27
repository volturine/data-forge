from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / 'packages'

EXCLUDED_DIRS = {
    '.git',
    '.artifacts',
    '.mypy_cache',
    '.pytest_cache',
    '.ruff_cache',
    '.svelte-kit',
    '.venv',
    'node_modules',
    '__pycache__',
    'buf',
    'tests-e2e',
    'test-results',
    'playwright-report',
    'dataforge_protocol',
}

EXPECTED_PACKAGES = {'backend', 'frontend', 'protocol', 'scheduler', 'worker'}

ROOT_TEST_RESIDUE = [
    ROOT / 'tests',
    ROOT / 'test_harness',
    ROOT / 'test_support',
    ROOT / 'pytest_fixtures.py',
    ROOT / 'postgres_harness.py',
]
ROOT_TEST_ARTIFACT_PREFIXES = ('test-results', 'playwright-report')

FORBIDDEN_OWNER_DUPLICATES = [
    Path('packages/backend/backend_core/contracts'),
    Path('packages/backend/backend_core/engine_identity.py'),
    Path('packages/backend/modules/analysis/models.py'),
    Path('packages/backend/modules/datasource/models.py'),
    Path('packages/backend/modules/health/models.py'),
    Path('packages/backend/modules/healthcheck/models.py'),
    Path('packages/backend/modules/settings/models.py'),
    Path('packages/backend/modules/telegram/models.py'),
    Path('packages/backend/modules/udf/models.py'),
    Path('packages/worker/runtime/engine_identity.py'),
    Path('packages/worker/runtime/domain/compute_requests/models.py'),
    Path('packages/worker/runtime/models'),
]

PACKAGE_FORBIDDEN_IMPORT_ROOTS = {
    'backend': {
        'backend_contracts',
        'builds',
        'data_plane_iceberg',
        'data_plane_object_store',
        'datasources',
        'operations',
        'runtime',
        'scheduler_service',
        'worker_models',
    },
    'scheduler': {'api', 'backend_contracts', 'backend_core', 'builds', 'datasources', 'modules', 'operations', 'runtime', 'shared', 'worker_models'},
    'worker': {'api', 'backend_contracts', 'backend_core', 'modules', 'scheduler_service', 'shared', 'sqlmodel', 'worker_models'},
}

LEGACY_IMPORT_ROOTS = {'backend_contracts', 'worker_models'}
FORBIDDEN_SOURCE_TOKENS = {
    'backend_contracts': 'deleted legacy backend contract package',
    'backend_core.contracts': 'renamed backend-owned domain package',
    'runtime.models': 'renamed worker-owned domain package',
    'worker_models': 'deleted legacy worker model package',
    '_grpc.generated': 'deleted generated gRPC compatibility import path',
    'JsonPayload': 'generic JSON-string protocol payload',
    '__preview__': 'engine identity prefix parsing',
    'engine_key': 'engine-key string identity',
    'storage_key': 'engine storage-key string identity',
    'EngineIdentityInput': 'engine identity aliases hide generated dataforge_protocol.compute_pb2.EngineIdentity',
    'def _resolve_identity(self, identity': 'string-derived engine identity resolver; use dataforge_protocol.compute_pb2.EngineIdentity',
    'data_plane_object_store': 'deleted backend data-plane object-store facade',
    'data_plane_iceberg': 'deleted backend data-plane Iceberg facade',
    'generate_ts_step_types.py': 'deleted backend-derived frontend type generator',
    'generate_ts_build_stream_types.py': 'deleted backend-derived frontend type generator',
    'step-schemas.generated': 'deleted backend-derived frontend step schema import',
    'build-stream.generated': 'deleted backend-derived frontend build stream import',
    'Generated from backend/': 'backend-derived generated frontend contract banner',
    'class AIProvider(DataForgeStrEnum)': 'hand-written AI provider enum; use dataforge_protocol.enums_pb2',
    'class ComputeRequestKind(': 'hand-written compute request kind enum; use dataforge_protocol.enums_pb2',
    'class ComputeRequestStatus(': 'hand-written compute request status enum; use dataforge_protocol.enums_pb2',
}
SOURCE_SUFFIXES = {'.py', '.ts', '.svelte', '.proto'}
WORKER_PROTOCOL_ADAPTER_FORBIDDEN_TOKENS = {
    'from runtime.domain.enums import DataForgeStrEnum': 'worker operation config enums must be generated-protocol-backed',
    '(DataForgeStrEnum)': 'worker operation config enums must not reintroduce copied StrEnum contracts',
}
FRONTEND_OPERATION_CONFIG_FORBIDDEN_TOKENS = {
    "export type CastMapType = 'Int64'": 'frontend cast-map type must be generated-protocol-backed',
}
FRONTEND_OPERATION_COMPONENT_FORBIDDEN_PATTERNS = {
    re.compile(r'\binterface\s+\w+ConfigData\b'): 'operation components must import protocol-anchored config types from $lib/types/operation-config',
    re.compile(r'\btype\s+WithColumnsConfigShape\b'): 'pipeline config binding must use protocol-anchored WithColumnsConfigData',
    re.compile(r'\btype\s+DownloadConfigData\b'): 'pipeline config binding must use protocol-anchored DownloadConfigData',
    re.compile(r'\bconst\s+CAST_TYPES\s*=\s*\['): 'select cast options must come from generated protocol enum tokens',
}
FRONTEND_BUILD_STREAM_ADAPTER_FORBIDDEN_PATTERNS = {
    re.compile(r'\bconst\s+ENGINE_RUN_KIND_TOKENS\s*:'): 'build-stream generated JSON enum tokens must live in protocol-enum-tokens.ts',
    re.compile(r'\bconst\s+BUILD_TAB_STATUS_TOKENS\s*:'): 'build-stream generated JSON enum tokens must live in protocol-enum-tokens.ts',
    re.compile(r'\bconst\s+BUILD_LOG_LEVEL_TOKENS\s*:'): 'build-stream generated JSON enum tokens must live in protocol-enum-tokens.ts',
}
WORKER_COMPUTE_SCHEMA_FORBIDDEN_TOKENS = {
    'class EngineIdentityPayload(BaseModel)': 'worker compute schemas must use dataforge_protocol.compute_pb2.EngineIdentity directly',
}
WORKER_STEP_CONVERTER_REQUIRED_TOKENS = {
    'analysis_pb2.AnalysisPipelineStep': 'worker step conversion must parse generated protocol step contracts',
    'analysis_pb2.StepConfig.DESCRIPTOR': 'worker step conversion must unwrap generated StepConfig oneof contracts',
    'json_format.ParseDict': 'worker step conversion must reject shapes that do not parse as generated protocol messages',
}
BACKEND_COMPUTE_SCHEMA_FORBIDDEN_TOKENS = {
    'class EngineIdentityPayload(BaseModel)': 'backend compute schemas must use dataforge_protocol.compute_pb2.EngineIdentity directly',
}
COMPUTE_ENVELOPE_FORBIDDEN_TOKENS = {
    'return struct_to_dict(envelope.payload)': 'compute envelopes must reject deprecated payload-only messages',
    'response.dynamic_response.CopyFrom': 'compute responses must use typed protocol oneof variants',
    'envelope.response.dynamic_response.CopyFrom': 'compute responses must use typed protocol oneof variants',
}
COMPUTE_ENVELOPE_REQUIRED_TOKENS = {
    'compute_pb2.ComputeErrorResult': 'compute failures must use typed protocol error responses',
    'compute_pb2.EngineStatusResult': 'engine lifecycle responses must use typed protocol engine status responses',
    'compute_pb2.ComputeAckResult': 'acknowledgement responses must use typed protocol ack responses',
}
BACKEND_PROTOCOL_ADAPTER_FORBIDDEN_TOKENS = {
    'from backend_core.domain.enums import DataForgeStrEnum': 'backend operation config enums must be generated-protocol-backed',
    '(DataForgeStrEnum)': 'backend operation config enums must not reintroduce copied StrEnum contracts',
}
PROTOCOL_BACKED_ENUM_FILES = [
    Path('packages/backend/backend_core/domain/analysis/models.py'),
    Path('packages/backend/backend_core/domain/analysis/step_types.py'),
    Path('packages/backend/backend_core/domain/build_jobs/models.py'),
    Path('packages/backend/backend_core/domain/build_runs/models.py'),
    Path('packages/backend/backend_core/domain/compute/schemas.py'),
    Path('packages/backend/backend_core/domain/datasource/models.py'),
    Path('packages/backend/backend_core/domain/datasource/source_types.py'),
    Path('packages/backend/backend_core/domain/engine_instances/models.py'),
    Path('packages/backend/backend_core/domain/engine_runs/schemas.py'),
    Path('packages/backend/backend_core/domain/healthcheck_models.py'),
    Path('packages/backend/backend_core/domain/runtime/events.py'),
    Path('packages/backend/backend_core/domain/runtime_workers/models.py'),
    Path('packages/backend/modules/datasource/runtime_loading.py'),
    Path('packages/backend/modules/datasource/schemas.py'),
    Path('packages/worker/datasources/datasource_loading.py'),
    Path('packages/worker/datasources/datasource_schemas.py'),
    Path('packages/worker/operations/datasource.py'),
    Path('packages/worker/runtime/domain/analysis/models.py'),
    Path('packages/worker/runtime/domain/analysis/step_types.py'),
    Path('packages/worker/runtime/domain/build_jobs/models.py'),
    Path('packages/worker/runtime/domain/build_runs/models.py'),
    Path('packages/worker/runtime/domain/compute/schemas.py'),
    Path('packages/worker/runtime/domain/datasource/models.py'),
    Path('packages/worker/runtime/domain/datasource/source_types.py'),
    Path('packages/worker/runtime/domain/engine_instances/models.py'),
    Path('packages/worker/runtime/domain/engine_runs/schemas.py'),
    Path('packages/worker/runtime/domain/healthcheck_models.py'),
    Path('packages/worker/runtime/domain/runtime/events.py'),
    Path('packages/worker/runtime/domain/runtime_workers/models.py'),
]
PROTOCOL_BACKED_ENUM_FORBIDDEN_TOKENS = {
    'DataForgeStrEnum': 'protocol-backed domain enums must use generated protocol descriptors',
}


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS or part.startswith('test-results') for part in path.parts)


def iter_python_files(package: str):
    package_root = PACKAGES / package
    for path in package_root.rglob('*.py'):
        rel = path.relative_to(package_root)
        if is_excluded(rel):
            continue
        yield path


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split('.')[0])
    return roots


def iter_source_files():
    for package_root in PACKAGES.iterdir():
        if not package_root.is_dir() or package_root.name.startswith('.'):
            continue
        for path in package_root.rglob('*'):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            rel = path.relative_to(package_root)
            if is_excluded(rel):
                continue
            yield path


def main() -> int:
    errors: list[str] = []

    actual_packages = {path.name for path in PACKAGES.iterdir() if path.is_dir() and not path.name.startswith('.')}
    unexpected = sorted((actual_packages - EXPECTED_PACKAGES) - {'__pycache__'})
    if unexpected:
        errors.append(f'unexpected package directories under packages/: {", ".join(unexpected)}')

    for path in ROOT_TEST_RESIDUE:
        if path.exists():
            errors.append(f'root test/support residue is not allowed: {path.relative_to(ROOT)}')

    for child in ROOT.iterdir():
        if child.name.startswith(ROOT_TEST_ARTIFACT_PREFIXES):
            errors.append(f'root test artifact is not allowed: {child.relative_to(ROOT)}')

    for rel_path in FORBIDDEN_OWNER_DUPLICATES:
        path = ROOT / rel_path
        if path.exists():
            errors.append(f'neutral shared model duplicated in backend owner package: {rel_path}')

    worker_step_config_enums = ROOT / 'packages/worker/runtime/domain/step_config_enums.py'
    if worker_step_config_enums.exists():
        content = worker_step_config_enums.read_text()
        for token, reason in WORKER_PROTOCOL_ADAPTER_FORBIDDEN_TOKENS.items():
            if token in content:
                errors.append(f'{worker_step_config_enums.relative_to(ROOT)} contains {reason}: {token}')

    worker_operations = ROOT / 'packages/worker/operations'
    if worker_operations.exists():
        for operation_file in worker_operations.glob('*.py'):
            content = operation_file.read_text()
            for token, reason in WORKER_PROTOCOL_ADAPTER_FORBIDDEN_TOKENS.items():
                if token in content:
                    errors.append(f'{operation_file.relative_to(ROOT)} contains {reason}: {token}')

    frontend_operation_config = ROOT / 'packages/frontend/src/lib/types/operation-config.ts'
    if frontend_operation_config.exists():
        content = frontend_operation_config.read_text()
        for token, reason in FRONTEND_OPERATION_CONFIG_FORBIDDEN_TOKENS.items():
            if token in content:
                errors.append(f'{frontend_operation_config.relative_to(ROOT)} contains {reason}: {token}')

    frontend_operation_components = ROOT / 'packages/frontend/src/lib/components/operations'
    if frontend_operation_components.exists():
        component_paths = list(frontend_operation_components.glob('*.svelte'))
        component_paths.append(ROOT / 'packages/frontend/src/lib/components/pipeline/StepConfig.svelte')
        for component_path in component_paths:
            if not component_path.exists():
                continue
            content = component_path.read_text()
            for pattern, reason in FRONTEND_OPERATION_COMPONENT_FORBIDDEN_PATTERNS.items():
                if pattern.search(content):
                    errors.append(f'{component_path.relative_to(ROOT)} contains {reason}: {pattern.pattern}')

    frontend_build_stream_adapter = ROOT / 'packages/frontend/src/lib/types/protocol-build-stream.ts'
    if frontend_build_stream_adapter.exists():
        content = frontend_build_stream_adapter.read_text()
        for pattern, reason in FRONTEND_BUILD_STREAM_ADAPTER_FORBIDDEN_PATTERNS.items():
            if pattern.search(content):
                errors.append(f'{frontend_build_stream_adapter.relative_to(ROOT)} contains {reason}: {pattern.pattern}')

    worker_compute_schemas = ROOT / 'packages/worker/runtime/domain/compute/schemas.py'
    if worker_compute_schemas.exists():
        content = worker_compute_schemas.read_text()
        for token, reason in WORKER_COMPUTE_SCHEMA_FORBIDDEN_TOKENS.items():
            if token in content:
                errors.append(f'{worker_compute_schemas.relative_to(ROOT)} contains {reason}: {token}')

    worker_step_converter = ROOT / 'packages/worker/operations/step_converter.py'
    if worker_step_converter.exists():
        content = worker_step_converter.read_text()
        for token, reason in WORKER_STEP_CONVERTER_REQUIRED_TOKENS.items():
            if token not in content:
                errors.append(f'{worker_step_converter.relative_to(ROOT)} is missing {reason}: {token}')

    backend_step_config_enums = ROOT / 'packages/backend/backend_core/domain/step_config_enums.py'
    if backend_step_config_enums.exists():
        content = backend_step_config_enums.read_text()
        for token, reason in BACKEND_PROTOCOL_ADAPTER_FORBIDDEN_TOKENS.items():
            if token in content:
                errors.append(f'{backend_step_config_enums.relative_to(ROOT)} contains {reason}: {token}')

    backend_compute_schemas = ROOT / 'packages/backend/backend_core/domain/compute/schemas.py'
    if backend_compute_schemas.exists():
        content = backend_compute_schemas.read_text()
        for token, reason in BACKEND_COMPUTE_SCHEMA_FORBIDDEN_TOKENS.items():
            if token in content:
                errors.append(f'{backend_compute_schemas.relative_to(ROOT)} contains {reason}: {token}')

    for rel_path in (
        Path('packages/backend/backend_core/domain/compute_requests/models.py'),
        Path('packages/worker/runtime/internal_api.py'),
    ):
        path = ROOT / rel_path
        if not path.exists():
            errors.append(f'compute envelope adapter is missing: {rel_path}')
            continue
        content = path.read_text()
        for token, reason in COMPUTE_ENVELOPE_FORBIDDEN_TOKENS.items():
            if token in content:
                errors.append(f'{rel_path} contains {reason}: {token}')
        for token, reason in COMPUTE_ENVELOPE_REQUIRED_TOKENS.items():
            if token not in content:
                errors.append(f'{rel_path} is missing {reason}: {token}')

    for rel_path in PROTOCOL_BACKED_ENUM_FILES:
        path = ROOT / rel_path
        if not path.exists():
            errors.append(f'protocol-backed enum file is missing: {rel_path}')
            continue
        content = path.read_text()
        for token, reason in PROTOCOL_BACKED_ENUM_FORBIDDEN_TOKENS.items():
            if token in content:
                errors.append(f'{rel_path} contains {reason}: {token}')

    for package, forbidden_roots in PACKAGE_FORBIDDEN_IMPORT_ROOTS.items():
        for path in iter_python_files(package):
            roots = imported_roots(path)
            violations = sorted(roots & forbidden_roots)
            if violations:
                rel = path.relative_to(ROOT)
                errors.append(f'{rel} imports cross-owner private modules: {", ".join(violations)}')
            legacy = sorted(roots & LEGACY_IMPORT_ROOTS)
            if legacy:
                rel = path.relative_to(ROOT)
                errors.append(f'{rel} imports deleted legacy contract roots: {", ".join(legacy)}')

    for path in iter_source_files():
        content = path.read_text()
        for token, reason in FORBIDDEN_SOURCE_TOKENS.items():
            if token in content:
                rel = path.relative_to(ROOT)
                errors.append(f'{rel} contains {reason}: {token}')

    if errors:
        print('Package boundary violations:')
        for error in errors:
            print(f'  - {error}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
