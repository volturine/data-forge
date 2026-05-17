from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / 'packages'

EXCLUDED_DIRS = {
    '.git',
    '.mypy_cache',
    '.pytest_cache',
    '.ruff_cache',
    '.svelte-kit',
    'node_modules',
    '__pycache__',
    'tests',
    'tests-e2e',
    'test-results',
    'playwright-report',
}

ROOT_TEST_RESIDUE = [
    ROOT / 'tests',
    ROOT / 'test_harness',
    ROOT / 'test_support',
    ROOT / 'pytest_fixtures.py',
    ROOT / 'postgres_harness.py',
]
ROOT_TEST_ARTIFACT_PREFIXES = ('test-results', 'playwright-report')

FORBIDDEN_OWNER_DUPLICATES = [
    Path('packages/backend/modules/analysis/models.py'),
    Path('packages/backend/modules/datasource/models.py'),
    Path('packages/backend/modules/health/models.py'),
    Path('packages/backend/modules/healthcheck/models.py'),
    Path('packages/backend/modules/settings/models.py'),
    Path('packages/backend/modules/telegram/models.py'),
    Path('packages/backend/modules/udf/models.py'),
]

OWNER_IMPORTS = {
    'backend': {'backend_core', 'modules', 'api'},
    'worker-manager': {
        'ai_service',
        'build_execution',
        'build_state',
        'compute_core',
        'compute_engine',
        'compute_live',
        'compute_manager',
        'compute_monitor',
        'compute_operations',
        'compute_request_runtime',
        'compute_service',
        'compute_utils',
        'datasource_schemas',
        'datasource_service',
        'engine_live',
        'engine_notifications',
        'healthcheck_service',
        'iceberg_reader',
        'notification_delivery',
        'notification_service',
        'runtime_notifications',
        'runtime_settings',
        'settings_service',
        'step_converter',
        'telegram_service',
        'telegram_targets',
        'worker_runtime',
    },
    'scheduler': {'scheduler_service'},
    'shared': {'config', 'contracts', 'core', 'database', 'runtime_compute'},
}

PUBLIC_CROSS_OWNER_IMPORTS = {
    # Neutral shared package APIs are the intended cross-owner boundary.
    'config',
    'contracts',
    'core',
    'database',
    'runtime_compute',
}

PACKAGE_RULES = {
    'backend': OWNER_IMPORTS['worker-manager'] | OWNER_IMPORTS['scheduler'],
    'worker-manager': OWNER_IMPORTS['backend'] | OWNER_IMPORTS['scheduler'],
    'scheduler': OWNER_IMPORTS['backend'] | OWNER_IMPORTS['worker-manager'],
    'shared': OWNER_IMPORTS['backend'] | OWNER_IMPORTS['worker-manager'] | OWNER_IMPORTS['scheduler'],
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
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split('.')[0])
    return roots


def main() -> int:
    errors: list[str] = []

    for path in ROOT_TEST_RESIDUE:
        if path.exists():
            errors.append(f'root test/support residue is not allowed: {path.relative_to(ROOT)}')

    for child in ROOT.iterdir():
        if not child.name.startswith(ROOT_TEST_ARTIFACT_PREFIXES):
            continue
        errors.append(f'root test artifact is not allowed: {child.relative_to(ROOT)}')

    for rel_path in FORBIDDEN_OWNER_DUPLICATES:
        path = ROOT / rel_path
        if path.exists():
            errors.append(f'neutral shared model duplicated in backend owner package: {rel_path}')

    for package, forbidden in PACKAGE_RULES.items():
        allowed_public = PUBLIC_CROSS_OWNER_IMPORTS | OWNER_IMPORTS[package]
        for path in iter_python_files(package):
            roots = imported_roots(path)
            violations = sorted((roots & forbidden) - allowed_public)
            if violations:
                rel = path.relative_to(ROOT)
                errors.append(f'{rel} imports cross-owner private modules: {", ".join(violations)}')

    if errors:
        print('Package boundary violations:')
        for error in errors:
            print(f'  - {error}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
