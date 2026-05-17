from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RUNTIME_ENV_FILES = [
    ROOT / 'packages/shared/dev.env',
    ROOT / 'packages/shared/prod.env',
    ROOT / 'packages/shared/e2e.env',
]

DOCKER_ENV_TO_COMPOSE: dict[Path, tuple[Path, ...]] = {
    ROOT / 'docker/env/dev.env': (
        ROOT / 'docker/docker-compose.yml',
        ROOT / 'docker/docker-compose.dev.yml',
    ),
    ROOT / 'docker/env/prod.env': (ROOT / 'docker/docker-compose.yml',),
}

EXTRA_RUNTIME_KEYS = {
    'ENV_FILE',
    'FRONTEND_PORT',
    'BACKEND_HOST',
    'BACKEND_PORT',
    'VITE_BACKEND_PORT',
    'E2E_PYTHON_VERSION',
    'E2E_TIMEOUT_SECONDS',
    'E2E_TIMEOUT_GRACE_SECONDS',
    'E2E_HEARTBEAT_SECONDS',
    'E2E_LOG_DIR',
    'DB_USERNAME',
    'DB_PASSWORD',
}

ENV_KEY_RE = re.compile(r'^[A-Z][A-Z0-9_]*$')
COMPOSE_REF_RE = re.compile(r'\$\{([^}]+)\}')


@dataclass(frozen=True)
class EnvKey:
    key: str
    line: int


def _collect_class_env_keys(path: Path, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    keys: set[str] = set()

    class_node = next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name),
        None,
    )
    if class_node is None:
        raise ValueError(f'Class {class_name} not found in {path}')

    for node in class_node.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        field_name = node.target.id.upper()
        keys.add(field_name)

        call = node.value
        if not isinstance(call, ast.Call):
            continue
        if not isinstance(call.func, ast.Name) or call.func.id != 'Field':
            continue

        for keyword in call.keywords:
            if keyword.arg != 'alias':
                continue
            if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                keys.add(keyword.value.value)

    return keys


def _parse_env_keys(path: Path) -> tuple[list[EnvKey], list[str]]:
    keys: list[EnvKey] = []
    errors: list[str] = []
    seen: set[str] = set()

    for line_number, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[len('export ') :].strip()
        if '=' not in line:
            errors.append(f'{path.relative_to(ROOT)}:{line_number}: invalid env assignment (missing =): {raw}')
            continue
        key = line.split('=', 1)[0].strip()
        if not ENV_KEY_RE.match(key):
            errors.append(f'{path.relative_to(ROOT)}:{line_number}: invalid env key format: {key}')
            continue
        if key in seen:
            errors.append(f'{path.relative_to(ROOT)}:{line_number}: duplicate env key: {key}')
            continue
        seen.add(key)
        keys.append(EnvKey(key=key, line=line_number))

    return keys, errors


def _compose_vars(paths: tuple[Path, ...]) -> tuple[set[str], set[str]]:
    referenced: set[str] = set()
    required: set[str] = set()

    for path in paths:
        content = path.read_text()
        for expr in COMPOSE_REF_RE.findall(content):
            inner = expr.strip()
            match = re.match(r'([A-Z0-9_]+)', inner)
            if match is None:
                continue
            var = match.group(1)
            referenced.add(var)
            remainder = inner[len(var) :]
            if remainder.startswith(':-') or remainder.startswith('-'):
                continue
            required.add(var)

    return referenced, required


def main() -> int:
    errors: list[str] = []

    shared_config_path = ROOT / 'packages/shared/core/config.py'
    auth_config_path = ROOT / 'packages/backend/backend_core/auth_config.py'

    runtime_allowed = _collect_class_env_keys(shared_config_path, 'Settings')
    runtime_allowed.update(_collect_class_env_keys(auth_config_path, 'AuthSettings'))
    runtime_allowed.update(EXTRA_RUNTIME_KEYS)

    for env_path in RUNTIME_ENV_FILES:
        parsed, parse_errors = _parse_env_keys(env_path)
        errors.extend(parse_errors)
        unknown = sorted(item for item in parsed if item.key not in runtime_allowed)
        for item in unknown:
            errors.append(
                f'{env_path.relative_to(ROOT)}:{item.line}: unknown runtime env key: {item.key} '
                f'(not defined by Settings/AuthSettings or approved extras)'
            )

    for env_path, compose_paths in DOCKER_ENV_TO_COMPOSE.items():
        parsed, parse_errors = _parse_env_keys(env_path)
        errors.extend(parse_errors)
        referenced, required = _compose_vars(compose_paths)
        keys = {item.key for item in parsed}

        for item in parsed:
            if not item.key.startswith('DF_'):
                errors.append(f'{env_path.relative_to(ROOT)}:{item.line}: docker env key must start with DF_: {item.key}')
            if item.key not in referenced:
                errors.append(f'{env_path.relative_to(ROOT)}:{item.line}: docker env key is not referenced by compose files: {item.key}')

        missing = sorted(required - keys)
        for key in missing:
            errors.append(f'{env_path.relative_to(ROOT)}: missing required compose variable: {key}')

    if errors:
        print('Environment contract violations:')
        for error in errors:
            print(f'  - {error}')
        return 1

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
