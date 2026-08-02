from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FRONTEND_SOURCE_ROOT = ROOT / 'packages/frontend/src'
PYTHON_SOURCE_ROOTS = [
    ROOT / 'packages/backend',
    ROOT / 'packages/worker',
    ROOT / 'packages/scheduler',
]
TRANSPORT_PATHS = [
    ROOT / 'packages/backend/backend_grpc/server.py',
    *sorted((ROOT / 'packages/backend/modules').glob('*/routes.py')),
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
    'buf',
    'dataforge_protocol',
    'generated',
    'node_modules',
    'styled-system',
    'tests',
    '__pycache__',
}


def _print_call_lines(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == 'print':
            lines.append(node.lineno)
    return lines


def _private_all_exports(tree: ast.AST) -> list[tuple[int, str]]:
    exports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == '__all__' for target in node.targets):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
            continue
        for element in node.value.elts:
            if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
                continue
            if element.value.startswith('_'):
                exports.append((element.lineno, element.value))
    return exports


def _transaction_call_lines(tree: ast.AST) -> list[tuple[int, str]]:
    calls: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr in {'commit', 'rollback'}:
            calls.append((node.lineno, node.func.attr))
    return calls


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
            for line_number in _print_call_lines(tree):
                errors.append(f'{path.relative_to(ROOT)}:{line_number}: print(...) is not allowed in source files')
            for line_number, name in _private_all_exports(tree):
                errors.append(f'{path.relative_to(ROOT)}:{line_number}: __all__ must not export private name {name}')


def _check_transport_transactions(errors: list[str]) -> None:
    for path in TRANSPORT_PATHS:
        tree = ast.parse(path.read_text(), filename=str(path))
        for line_number, operation in _transaction_call_lines(tree):
            errors.append(f'{path.relative_to(ROOT)}:{line_number}: transport must call an application command instead of {operation}()')


def main() -> int:
    errors: list[str] = []

    _check_frontend_sources(errors)
    _check_python_sources(errors)
    _check_transport_transactions(errors)

    if errors:
        print('Code hygiene violations:')
        for error in errors:
            print(f'  - {error}')
        return 1

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
