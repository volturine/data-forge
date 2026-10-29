from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PASSWORD = 'ChangeMe123'
REQUIRED_IMAGES = ('api', 'runtime', 'scheduler', 'worker')
REQUIRED_ENVIRONMENT = (
    ('api', 'DATABASE_URL'),
    ('api', 'INTERNAL_API_TOKEN'),
    ('api', 'SETTINGS_ENCRYPTION_KEY'),
    ('api', 'DEFAULT_USER_PASSWORD'),
    ('api', 'OBJECT_STORE_ACCESS_KEY'),
    ('api', 'OBJECT_STORE_SECRET_KEY'),
    ('postgres', 'POSTGRES_PASSWORD'),
    ('worker', 'COMPUTE_WORKER_IMAGE'),
)
COMPOSE_ENV_KEYS = (
    'DF_API_IMAGE',
    'DF_RUNTIME_IMAGE',
    'DF_SCHEDULER_IMAGE',
    'DF_WORKER_IMAGE',
    'DF_COMPUTE_WORKER_IMAGE',
    'DF_DATABASE_URL',
    'DF_INTERNAL_API_TOKEN',
    'DF_SETTINGS_ENCRYPTION_KEY',
    'DF_OBJECT_STORE_ACCESS_KEY',
    'DF_OBJECT_STORE_SECRET_KEY',
    'DF_POSTGRES_PASSWORD',
)


# Compose only warns for an unset `${VAR}` and substitutes an empty string,
# which the services then reject at startup. The warning names the variable
# but never its value.
_UNSET_VARIABLE = re.compile(r'The \\?"(\w+)\\?" variable is not set')
# v0.5.0 renamed the ENGINE_* deployment keys; the aliases have been removed, so
# an old key would be ignored and its service would fall back to defaults.
_REMOVED_ENGINE_KEY = re.compile(r'^\s*(?:export\s+)?((?:DF_)?ENGINE_\w+)\s*=', re.MULTILINE)


def _renamed_engine_key(name: str) -> str:
    suffix = name.removeprefix('DF_').removeprefix('ENGINE_')
    compose = (REPOSITORY_ROOT / 'docker' / 'compose.yaml').read_text(encoding='utf-8')
    prefixed = f'DF_COMPUTE_WORKER_{suffix}'
    return prefixed if '${' + prefixed in compose else f'COMPUTE_WORKER_{suffix}'


def _admin_password() -> str:
    # AuthSettings requires upper- and lowercase letters and a digit.
    while True:
        password = secrets.token_urlsafe(18)
        if any(c.isupper() for c in password) and any(c.islower() for c in password) and any(c.isdigit() for c in password):
            return password


def _initialize_env_file(target: Path) -> int:
    """Write ``target`` from the production template with generated secrets."""
    if target.exists():
        print(f'{target} already exists; refusing to overwrite it.', file=sys.stderr)
        return 2
    database_password = secrets.token_urlsafe(24)
    generated = {
        'DF_POSTGRES_PASSWORD': database_password,
        'DF_INTERNAL_API_TOKEN': secrets.token_urlsafe(32),
        # RustFS accepts S3-style keys: at most 20 characters for the access key.
        'DF_OBJECT_STORE_ACCESS_KEY': f'dataforge{secrets.token_hex(5)}',
        'DF_OBJECT_STORE_SECRET_KEY': secrets.token_hex(20),
        'DF_DEFAULT_USER_PASSWORD': _admin_password(),
        'DF_SETTINGS_ENCRYPTION_KEY': secrets.token_urlsafe(32),
    }
    template = (REPOSITORY_ROOT / 'docker' / 'env' / 'prod.env').read_text(encoding='utf-8')
    api_image = re.search(r'^DF_API_IMAGE=\S+:(\S+)$', template, re.MULTILINE)
    socket = re.search(r'^DF_DOCKER_SOCKET_PATH=(\S+)$', template, re.MULTILINE)
    # The worker manager joins the socket's group. Docker Desktop's socket lives
    # in its VM, so only a Linux host path reflects the group the container sees.
    if sys.platform.startswith('linux') and socket and Path(socket.group(1)).exists():
        generated['DF_DOCKER_GID'] = str(Path(socket.group(1)).stat().st_gid)
    lines: list[str] = []
    for line in template.splitlines():
        key, separator, value = line.partition('=')
        if separator and key in generated:
            line = f'{key}={generated[key]}'
        elif key == 'DF_DATABASE_URL':
            line = line.replace('replace-with-strong-password', database_password)
        elif key == 'DF_COMPUTE_WORKER_IMAGE' and '@sha256:replace-with-' in value and api_image:
            line = f'{key}={value.split("@", 1)[0]}:{api_image.group(1)}'
        lines.append(line)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(lines) + '\n')
    print(
        f'Wrote {target} with generated secrets (mode 600). Sign in as DF_DEFAULT_USER_EMAIL with the '
        'DF_DEFAULT_USER_PASSWORD stored there, and set DF_AUTH_FRONTEND_URL and DF_CORS_ORIGINS to your public origin. '
        f'Then run: just docker-up {target}'
    )
    return 0


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError('must be a positive integer') from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError('must be a positive integer')
    return parsed


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate or deploy the self-hosted Docker Compose stack.')
    parser.add_argument('--env-file', default='docker/env/prod.env', help='Compose environment file')
    parser.add_argument('--project', default='dataforge-prod', help='Compose project name')
    parser.add_argument('--check', action='store_true', help='resolve and validate without Docker mutations')
    parser.add_argument('--init', action='store_true', help='write --env-file from the production template with generated secrets')
    parser.add_argument(
        '--wait-timeout',
        type=_positive_int,
        default=180,
        help='seconds to wait for Compose services to become healthy (default: 180)',
    )
    arguments = parser.parse_args(argv)
    if not arguments.project.strip():
        parser.error('--project must not be empty')
    return arguments


def _resolve_env_file(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = REPOSITORY_ROOT / path
    return path.resolve()


def _configuration_errors(configuration: object) -> tuple[list[str], str | None]:
    errors: list[str] = []
    if not isinstance(configuration, dict):
        return ['resolved Compose configuration is not an object'], None
    services = configuration.get('services')
    if not isinstance(services, dict):
        return ['services is missing from resolved Compose configuration'], None

    def check_text(value: object, path: str) -> None:
        if not isinstance(value, str):
            return
        if 'replace-with-' in value.casefold():
            errors.append(f'{path} contains an unresolved replace-with- placeholder')
        if SAMPLE_PASSWORD in value:
            errors.append(f'{path} still uses the known sample password')

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue
        image = service_config.get('image')
        check_text(image, f'services.{service_name}.image')
        environment = service_config.get('environment')
        if not isinstance(environment, dict):
            continue
        for key, value in environment.items():
            check_text(value, f'services.{service_name}.environment.{key}')

    for service in REQUIRED_IMAGES:
        service_config = services.get(service)
        image = service_config.get('image') if isinstance(service_config, dict) else None
        if not isinstance(image, str) or not image.strip():
            errors.append(f'services.{service}.image is missing or empty')

    for service, key in REQUIRED_ENVIRONMENT:
        service_config = services.get(service)
        environment = service_config.get('environment') if isinstance(service_config, dict) else None
        value = environment.get(key) if isinstance(environment, dict) else None
        if not isinstance(value, str) or not value.strip():
            errors.append(f'services.{service}.environment.{key} is missing or empty')

    # Mirror AuthSettings' startup checks without importing the application's
    # dependencies or initializing its environment on the deployment host.
    api_config = services.get('api')
    api_environment = api_config.get('environment') if isinstance(api_config, dict) else None
    if isinstance(api_environment, dict):
        password = api_environment.get('DEFAULT_USER_PASSWORD')
        if isinstance(password, str) and password:
            if len(password) < 8 or not all((any(c.isupper() for c in password), any(c.islower() for c in password), any(c.isdigit() for c in password))):
                errors.append('services.api.environment.DEFAULT_USER_PASSWORD must have at least 8 characters, uppercase and lowercase letters, and a digit')
            if password.strip().lower() in {'changeme123', 'changeme123!', 'replaceme123', 'replace-with-strong-password'}:
                errors.append('services.api.environment.DEFAULT_USER_PASSWORD still uses a production placeholder')
        encryption_key = api_environment.get('SETTINGS_ENCRYPTION_KEY')
        if isinstance(encryption_key, str) and encryption_key.strip() == 'your-encryption-key-here':
            errors.append('services.api.environment.SETTINGS_ENCRYPTION_KEY still uses a production placeholder')

    worker_config = services.get('worker')
    worker_environment = worker_config.get('environment') if isinstance(worker_config, dict) else None
    worker_image = worker_environment.get('COMPUTE_WORKER_IMAGE') if isinstance(worker_environment, dict) else None
    return errors, worker_image if isinstance(worker_image, str) and worker_image.strip() else None


def _invoke(command: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=capture_output,
        )
    except FileNotFoundError:
        print("Required tool 'docker' was not found in PATH.", file=sys.stderr)
        return None
    except OSError:
        print('Could not run Docker; check the Docker CLI and daemon access.', file=sys.stderr)
        return None


def _compose_base(env_file: Path, project: str) -> list[str]:
    return [
        'docker',
        'compose',
        '--env-file',
        str(env_file),
        '-p',
        project,
        '-f',
        str(REPOSITORY_ROOT / 'docker' / 'compose.yaml'),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _arguments(argv)
    env_file = _resolve_env_file(arguments.env_file)
    if arguments.init:
        return _initialize_env_file(env_file)
    if not env_file.is_file():
        print(f'Environment file not found: {env_file}. Run `just docker-init` to create one.', file=sys.stderr)
        return 2

    compose = _compose_base(env_file, arguments.project)
    resolved = _invoke([*compose, 'config', '--format', 'json'], capture_output=True)
    if resolved is None:
        return 127
    if resolved.returncode:
        failure_details = (resolved.stderr or '').casefold()
        if "'compose' is not a docker command" in failure_details or 'unknown command: compose' in failure_details:
            print('Docker Compose v2 is unavailable; install the Docker Compose plugin.', file=sys.stderr)
            return resolved.returncode

        failed_keys = [key for key in COMPOSE_ENV_KEYS if key.casefold() in failure_details]
        key_names = ', '.join(failed_keys or COMPOSE_ENV_KEYS)
        print(
            'Docker Compose could not resolve the deployment configuration. '
            f'Check the Compose file and required environment keys: {key_names}. '
            'Command output was suppressed because it can contain credentials.',
            file=sys.stderr,
        )
        return resolved.returncode

    try:
        configuration = json.loads(resolved.stdout)
    except json.JSONDecodeError:
        print('Docker Compose returned invalid configuration JSON.', file=sys.stderr)
        return 2

    errors, compute_worker_image = _configuration_errors(configuration)
    unset = sorted(set(_UNSET_VARIABLE.findall(resolved.stderr or '')))
    errors = [f'{name} is not set in {env_file.name}' for name in unset] + errors
    errors = [
        f'{name} in {env_file.name} was renamed to {_renamed_engine_key(name)}'
        for name in sorted(set(_REMOVED_ENGINE_KEY.findall(env_file.read_text(encoding='utf-8'))))
    ] + errors
    if errors:
        print('Deployment configuration needs attention:', file=sys.stderr)
        for error in errors:
            print(f'  - {error}', file=sys.stderr)
        return 2

    if arguments.check:
        print('Docker Compose configuration is valid.')
        return 0

    if compute_worker_image is None:
        print('services.worker.environment.COMPUTE_WORKER_IMAGE is missing or empty', file=sys.stderr)
        return 2

    commands: list[list[str]] = [
        ['docker', 'pull', compute_worker_image],
        [*compose, 'pull'],
        [
            *compose,
            'up',
            '-d',
            '--wait',
            '--wait-timeout',
            str(arguments.wait_timeout),
        ],
    ]
    for command in commands:
        result = _invoke(command)
        if result is None:
            return 127
        if result.returncode:
            return result.returncode

    services = configuration.get('services') if isinstance(configuration, dict) else None
    api = services.get('api') if isinstance(services, dict) else None
    environment = api.get('environment') if isinstance(api, dict) else None
    url = environment.get('AUTH_FRONTEND_URL') if isinstance(environment, dict) else None
    print(f'Deployment is healthy. Open {url}' if isinstance(url, str) and url.strip() else 'Deployment is healthy.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
