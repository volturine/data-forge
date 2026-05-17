from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES_DIR = ROOT / 'packages'

LEGACY_TEST_DIR_PREFIXES = ('playwright-report', 'test-results')
LEGACY_TEST_DIR_NAMES = {'.auth', 'screenshots', '.pytest_cache'}


def _iter_package_test_dirs() -> list[Path]:
    dirs: list[Path] = []
    for package_dir in PACKAGES_DIR.iterdir():
        if not package_dir.is_dir():
            continue
        test_dir = package_dir / 'tests'
        if test_dir.exists() and test_dir.is_dir():
            dirs.append(test_dir)
    return sorted(dirs)


def main() -> int:
    errors: list[str] = []

    for test_dir in _iter_package_test_dirs():
        for path in test_dir.rglob('*'):
            if not path.is_dir():
                continue
            rel = path.relative_to(test_dir)
            if '.artifacts' in rel.parts:
                continue
            name = path.name
            if name in LEGACY_TEST_DIR_NAMES or name.startswith(LEGACY_TEST_DIR_PREFIXES):
                errors.append(f'{path.relative_to(ROOT)} is a legacy test artifact location; use {test_dir.relative_to(ROOT)}/.artifacts/')

    for package_dir in sorted(PACKAGES_DIR.iterdir()):
        if not package_dir.is_dir():
            continue
        root_pytest_cache = package_dir / '.pytest_cache'
        if root_pytest_cache.exists():
            errors.append(
                f'{root_pytest_cache.relative_to(ROOT)} is not allowed; keep test artifacts under '
                f'{(package_dir / "tests/.artifacts").relative_to(ROOT)}'
            )

    if errors:
        print('Test layout violations:')
        for error in errors:
            print(f'  - {error}')
        return 1

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
