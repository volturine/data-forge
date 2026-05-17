from __future__ import annotations

import json
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python <3.11 fallback for local execution
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]

FRONTEND_PACKAGE_JSON = ROOT / 'packages/frontend/package.json'
PYPROJECT_FILES = {
    'shared': ROOT / 'packages/shared/pyproject.toml',
    'backend': ROOT / 'packages/backend/pyproject.toml',
    'worker-manager': ROOT / 'packages/worker-manager/pyproject.toml',
    'scheduler': ROOT / 'packages/scheduler/pyproject.toml',
}

LEGACY_TEST_ARTIFACT_PATH_TOKENS = (
    'tests/playwright-report',
    'tests/test-results',
    'test-results',
    'playwright-report',
)


def _is_sorted(items: list[str]) -> bool:
    return items == sorted(items, key=str.lower)


def _normalize_dependency_name(raw: str) -> str:
    head = raw.split(';', 1)[0].strip()
    head = head.split('[', 1)[0].strip()
    for marker in ('==', '>=', '<=', '~=', '!=', '>', '<'):
        if marker in head:
            head = head.split(marker, 1)[0].strip()
    return head.lower()


def main() -> int:
    errors: list[str] = []

    frontend = json.loads(FRONTEND_PACKAGE_JSON.read_text())
    deps = frontend.get('dependencies', {})
    dev_deps = frontend.get('devDependencies', {})
    scripts = frontend.get('scripts', {})

    dep_names = list(deps.keys())
    dev_dep_names = list(dev_deps.keys())

    if not _is_sorted(dep_names):
        errors.append('packages/frontend/package.json dependencies must be alphabetically sorted')
    if not _is_sorted(dev_dep_names):
        errors.append('packages/frontend/package.json devDependencies must be alphabetically sorted')

    overlap = sorted(set(dep_names) & set(dev_dep_names))
    if overlap:
        errors.append(
            'packages/frontend/package.json has dependency overlap between dependencies and devDependencies: ' + ', '.join(overlap)
        )

    for script_name, script_value in scripts.items():
        if script_name == 'test:e2e:report':
            continue
        if any(token in script_value for token in LEGACY_TEST_ARTIFACT_PATH_TOKENS):
            errors.append(f'packages/frontend/package.json script "{script_name}" uses legacy artifact path: {script_value}')

    for package_name, pyproject_path in PYPROJECT_FILES.items():
        data = tomllib.loads(pyproject_path.read_text())
        dependencies = data.get('project', {}).get('dependencies', [])
        normalized = [_normalize_dependency_name(item) for item in dependencies]

        duplicates = sorted({name for name in normalized if normalized.count(name) > 1})
        if duplicates:
            errors.append(f'{pyproject_path.relative_to(ROOT)} has duplicated dependencies: {", ".join(duplicates)}')

        if package_name in {'backend', 'worker-manager', 'scheduler'} and normalized != ['dataforge-shared']:
            errors.append(f'{pyproject_path.relative_to(ROOT)} must depend only on dataforge-shared; got: {dependencies}')

    if errors:
        print('Dependency hygiene violations:')
        for error in errors:
            print(f'  - {error}')
        return 1

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
