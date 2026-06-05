from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTO_DIR = ROOT / 'packages/protocol/proto'
TARGETS = [
    ROOT / 'packages/backend/backend_grpc/generated',
    ROOT / 'packages/worker/worker_grpc/generated',
    ROOT / 'packages/scheduler/scheduler_grpc/generated',
]
PROTO_FILES = [
    PROTO_DIR / 'common.proto',
    PROTO_DIR / 'worker_runtime.proto',
    PROTO_DIR / 'scheduler_runtime.proto',
]
SUPPORT_INIT = """from __future__ import annotations

import sys
from pathlib import Path

_generated_dir = str(Path(__file__).resolve().parent)
if _generated_dir not in sys.path:
    sys.path.insert(0, _generated_dir)
"""


def _clean_generated(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def _write_support_files(path: Path) -> None:
    (path / '__init__.py').write_text(SUPPORT_INIT)


def _generate_into(path: Path) -> None:
    _clean_generated(path)
    command = [
        sys.executable,
        '-m',
        'grpc_tools.protoc',
        f'-I{PROTO_DIR}',
        f'--python_out={path}',
        f'--grpc_python_out={path}',
        f'--pyi_out={path}',
        *(str(proto_file) for proto_file in PROTO_FILES),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    _write_support_files(path)


def _relative_files(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob('*') if path.is_file() and '__pycache__' not in path.parts}


def _diff_generated(expected: Path, actual: Path) -> list[str]:
    errors: list[str] = []
    expected_files = _relative_files(expected)
    actual_files = _relative_files(actual)
    for path in sorted(expected_files - actual_files):
        errors.append(f'missing generated gRPC file in {actual.relative_to(ROOT)}: {path}')
    for path in sorted(actual_files - expected_files):
        errors.append(f'unexpected generated gRPC file in {actual.relative_to(ROOT)}: {path}')
    for path in sorted(expected_files & actual_files):
        if (expected / path).read_text() != (actual / path).read_text():
            errors.append(f'generated gRPC file is out of date in {actual.relative_to(ROOT)}: {path}')
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate package-local gRPC stubs from protocol proto files.')
    parser.add_argument('--check', action='store_true', help='fail if generated gRPC stubs are stale')
    args = parser.parse_args()

    if args.check:
        errors: list[str] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            expected = Path(temp_dir) / 'generated'
            _generate_into(expected)
            for target in TARGETS:
                errors.extend(_diff_generated(expected, target))
        if errors:
            print('gRPC generation violations:')
            for error in errors:
                print(f'  - {error}')
            return 1
        return 0

    for target in TARGETS:
        _generate_into(target)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
