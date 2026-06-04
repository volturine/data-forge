from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'packages/backend/backend_contracts'
TARGET = ROOT / 'packages/worker/worker_contracts'


def _copy_generated_contracts(destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(SOURCE, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for path in destination.rglob('*.py'):
        text = path.read_text()
        path.write_text(text.replace('backend_contracts', 'worker_contracts'))
    _format_generated_contracts(destination)


def _format_generated_contracts(destination: Path) -> None:
    worker_ruff_config = ROOT / 'packages/worker/pyproject.toml'
    worker_root = ROOT / 'packages/worker'
    subprocess.run(
        [sys.executable, '-m', 'ruff', 'check', '--config', str(worker_ruff_config), '--select', 'I', '--fix', str(destination)],
        cwd=worker_root,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        [sys.executable, '-m', 'ruff', 'format', '--config', str(worker_ruff_config), str(destination)],
        cwd=worker_root,
        check=True,
        stdout=subprocess.DEVNULL,
    )


def _relative_files(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob('*') if path.is_file() and '__pycache__' not in path.parts}


def _diff_generated(expected: Path, actual: Path) -> list[str]:
    errors: list[str] = []
    expected_files = _relative_files(expected)
    actual_files = _relative_files(actual)
    for path in sorted(expected_files - actual_files):
        errors.append(f'missing generated worker contract: {path}')
    for path in sorted(actual_files - expected_files):
        errors.append(f'unexpected worker contract file: {path}')
    for path in sorted(expected_files & actual_files):
        expected_text = (expected / path).read_text()
        actual_text = (actual / path).read_text()
        if expected_text != actual_text:
            errors.append(f'worker contract is out of date: {path}')
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate worker-local contracts from backend-owned contracts.')
    parser.add_argument('--check', action='store_true', help='fail if generated worker contracts are stale')
    args = parser.parse_args()

    if not SOURCE.exists():
        raise SystemExit(f'backend contract source does not exist: {SOURCE.relative_to(ROOT)}')

    if args.check:
        with tempfile.TemporaryDirectory() as temp_dir:
            expected = Path(temp_dir) / 'worker_contracts'
            _copy_generated_contracts(expected)
            errors = _diff_generated(expected, TARGET)
        if errors:
            print('Worker contract generation violations:')
            for error in errors:
                print(f'  - {error}')
            return 1
        return 0

    _copy_generated_contracts(TARGET)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
