from __future__ import annotations

import ast
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
    'EngineIdentityInput = EngineIdentity | str': 'string-derived engine identity input; use dataforge_protocol.compute_pb2.EngineIdentity',
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
BACKEND_PROTOCOL_ADAPTER_FORBIDDEN_TOKENS = {
    'from backend_core.domain.enums import DataForgeStrEnum': 'backend operation config enums must be generated-protocol-backed',
    '(DataForgeStrEnum)': 'backend operation config enums must not reintroduce copied StrEnum contracts',
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

    backend_step_config_enums = ROOT / 'packages/backend/backend_core/domain/step_config_enums.py'
    if backend_step_config_enums.exists():
        content = backend_step_config_enums.read_text()
        for token, reason in BACKEND_PROTOCOL_ADAPTER_FORBIDDEN_TOKENS.items():
            if token in content:
                errors.append(f'{backend_step_config_enums.relative_to(ROOT)} contains {reason}: {token}')

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
