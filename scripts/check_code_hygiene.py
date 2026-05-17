from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FRONTEND_SOURCE_ROOT = ROOT / 'packages/frontend/src'
PYTHON_SOURCE_ROOTS = [
    ROOT / 'packages/backend',
    ROOT / 'packages/worker-manager',
    ROOT / 'packages/scheduler',
    ROOT / 'packages/shared/core',
    ROOT / 'packages/shared/contracts',
]

TODO_PATTERN = re.compile(r'\b(TODO|FIXME|HACK)\b')
CONSOLE_LOG_PATTERN = re.compile(r'\bconsole\.log\s*\(')
DEBUGGER_PATTERN = re.compile(r'\bdebugger\b')

EXCLUDED_DIR_NAMES = {
    '.artifacts',
    '.git',
    '.mypy_cache',
    '.pytest_cache',
    '.ruff_cache',
    '.svelte-kit',
    '.venv',
    '.venv311',
    'build',
    'node_modules',
    'styled-system',
    'tests',
    '__pycache__',
}


class _PrintCallVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.lines: list[int] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if isinstance(node.func, ast.Name) and node.func.id == 'print':
            self.lines.append(node.lineno)
        self.generic_visit(node)


def _iter_files(root: Path, suffixes: set[str]):
    for path in root.rglob('*'):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        yield path


def _check_frontend_sources(errors: list[str]) -> None:
    for path in _iter_files(FRONTEND_SOURCE_ROOT, {'.ts', '.js', '.svelte'}):
        content = path.read_text()
        for line_number, line in enumerate(content.splitlines(), start=1):
            if TODO_PATTERN.search(line):
                errors.append(f'{path.relative_to(ROOT)}:{line_number}: TODO/FIXME/HACK marker is not allowed in source files')
            if CONSOLE_LOG_PATTERN.search(line):
                errors.append(f'{path.relative_to(ROOT)}:{line_number}: console.log is not allowed in source files')
            if DEBUGGER_PATTERN.search(line):
                errors.append(f'{path.relative_to(ROOT)}:{line_number}: debugger statement is not allowed in source files')


def _check_python_sources(errors: list[str]) -> None:
    for root in PYTHON_SOURCE_ROOTS:
        for path in _iter_files(root, {'.py'}):
            content = path.read_text()
            for line_number, line in enumerate(content.splitlines(), start=1):
                if TODO_PATTERN.search(line):
                    errors.append(f'{path.relative_to(ROOT)}:{line_number}: TODO/FIXME/HACK marker is not allowed in source files')

            tree = ast.parse(content, filename=str(path))
            visitor = _PrintCallVisitor()
            visitor.visit(tree)
            for line_number in visitor.lines:
                errors.append(f'{path.relative_to(ROOT)}:{line_number}: print(...) is not allowed in source files')


def main() -> int:
    errors: list[str] = []

    _check_frontend_sources(errors)
    _check_python_sources(errors)

    if errors:
        print('Code hygiene violations:')
        for error in errors:
            print(f'  - {error}')
        return 1

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
