from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_SCRIPT = REPOSITORY_ROOT / 'scripts' / 'deploy.py'
SPEC = importlib.util.spec_from_file_location('dataforge_deploy', DEPLOY_SCRIPT)
assert SPEC is not None and SPEC.loader is not None
deploy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = deploy
SPEC.loader.exec_module(deploy)


def resolved_configuration() -> dict[str, object]:
    return {
        'services': {
            'postgres': {
                'image': 'postgres:18-alpine',
                'environment': {'POSTGRES_PASSWORD': 'database-password'},
            },
            'rustfs': {'image': 'rustfs/rustfs:1.0.0-rc.1'},
            'api': {
                'image': 'registry.example/data-forge-api@sha256:api-digest',
                'environment': {
                    'DATABASE_URL': 'postgresql+psycopg://app:db-pass@postgres:5432/app',
                    'INTERNAL_API_TOKEN': 'api-internal-secret',
                    'SETTINGS_ENCRYPTION_KEY': 'settings-encryption-secret',
                    'OBJECT_STORE_ACCESS_KEY': 'store-access-secret',
                    'OBJECT_STORE_SECRET_KEY': 'store-secret-secret',
                    'DEFAULT_USER_PASSWORD': 'ValidUserPassword123',
                },
            },
            'runtime': {'image': 'registry.example/data-forge-runtime:custom'},
            'scheduler': {'image': 'registry.example/data-forge-scheduler:custom'},
            'worker': {
                'image': 'registry.example/data-forge-worker:custom',
                'environment': {
                    'COMPUTE_WORKER_IMAGE': 'registry.example/compute-worker@sha256:compute-digest',
                },
            },
        }
    }


def completed(command: list[str], returncode: int = 0, stdout: str = '', stderr: str = '') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)


class DeployContractTests(unittest.TestCase):
    def test_wait_timeout_defaults_to_180_and_rejects_nonpositive_values(self) -> None:
        self.assertEqual(deploy._arguments([]).wait_timeout, 180)
        stderr = StringIO()

        with redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
            deploy._arguments(['--wait-timeout', '0'])

        self.assertEqual(error.exception.code, 2)
        self.assertIn('must be a positive integer', stderr.getvalue())

    def test_check_resolves_from_repository_root_and_never_prints_configuration(self) -> None:
        configuration = resolved_configuration()
        configuration['private_marker'] = 'never-print-this-secret'
        config_result = completed([], stdout=json.dumps(configuration))
        stdout = StringIO()
        stderr = StringIO()

        with tempfile.TemporaryDirectory() as temporary_directory:
            current_directory = os.getcwd()
            try:
                os.chdir(temporary_directory)
                with (
                    patch.object(deploy.subprocess, 'run', return_value=config_result) as run,
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                ):
                    exit_code = deploy.main(['--env-file', 'docker/env/prod.env', '--project', 'custom-prod', '--check'])
            finally:
                os.chdir(current_directory)

        self.assertEqual(exit_code, 0)
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(command[-3:], ['config', '--format', 'json'])
        self.assertEqual(command[3], str(REPOSITORY_ROOT / 'docker' / 'env' / 'prod.env'))
        self.assertEqual(command[5], 'custom-prod')
        self.assertTrue(run.call_args.kwargs['capture_output'])
        self.assertIn('configuration is valid', stdout.getvalue())
        self.assertNotIn('never-print-this-secret', stdout.getvalue() + stderr.getvalue())

    def test_deploy_pulls_compute_image_then_compose_images_then_waits(self) -> None:
        configuration = resolved_configuration()
        responses = [completed([], stdout=json.dumps(configuration)), completed([]), completed([]), completed([])]
        stdout = StringIO()

        with patch.object(deploy.subprocess, 'run', side_effect=responses) as run, redirect_stdout(stdout):
            exit_code = deploy.main(
                [
                    '--env-file',
                    'docker/env/prod.env',
                    '--project',
                    'dataforge-prod',
                    '--wait-timeout',
                    '240',
                ]
            )

        self.assertEqual(exit_code, 0)
        commands = [entry.args[0] for entry in run.call_args_list]
        compose = [
            'docker',
            'compose',
            '--env-file',
            str(REPOSITORY_ROOT / 'docker' / 'env' / 'prod.env'),
            '-p',
            'dataforge-prod',
            '-f',
            str(REPOSITORY_ROOT / 'docker' / 'compose.yaml'),
        ]
        self.assertEqual(
            commands,
            [
                [*compose, 'config', '--format', 'json'],
                ['docker', 'pull', 'registry.example/compute-worker@sha256:compute-digest'],
                [*compose, 'pull'],
                [*compose, 'up', '-d', '--wait', '--wait-timeout', '240'],
            ],
        )
        self.assertIn('Deployment is healthy', stdout.getvalue())

    def test_invalid_configuration_names_missing_values_without_echoing_them(self) -> None:
        configuration = resolved_configuration()
        services = configuration['services']
        assert isinstance(services, dict)
        api = services['api']
        worker = services['worker']
        assert isinstance(api, dict) and isinstance(api['environment'], dict)
        assert isinstance(worker, dict) and isinstance(worker['environment'], dict)
        postgres = services['postgres']
        assert isinstance(postgres, dict) and isinstance(postgres['environment'], dict)
        api['image'] = 'replace-with-private-image'
        api['environment']['DATABASE_URL'] = ''
        api['environment']['INTERNAL_API_TOKEN'] = ''
        api['environment']['SETTINGS_ENCRYPTION_KEY'] = ''
        api['environment']['OBJECT_STORE_ACCESS_KEY'] = ''
        api['environment']['OBJECT_STORE_SECRET_KEY'] = 'replace-with-do-not-print-secret'
        api['environment']['DEFAULT_USER_PASSWORD'] = 'ChangeMe123'
        postgres['environment']['POSTGRES_PASSWORD'] = ''
        worker['environment']['COMPUTE_WORKER_IMAGE'] = ''
        unset_warning = 'level=warning msg="The \\"DF_WORKERS\\" variable is not set. Defaulting to a blank string."\n'
        result = completed([], stdout=json.dumps(configuration), stderr=unset_warning * 2)
        stdout = StringIO()
        stderr = StringIO()

        with tempfile.TemporaryDirectory() as temporary_directory:
            env_file = Path(temporary_directory) / 'upgrade.env'
            env_file.write_text('DF_ENGINE_IMAGE=old-private-image\n', encoding='utf-8')
            with patch.object(deploy.subprocess, 'run', return_value=result) as run, redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = deploy.main(['--env-file', str(env_file)])

        self.assertEqual(exit_code, 2)
        run.assert_called_once()
        output = stdout.getvalue() + stderr.getvalue()
        self.assertIn('DF_ENGINE_IMAGE in upgrade.env was renamed to DF_COMPUTE_WORKER_IMAGE', output)
        self.assertIn('services.api.image', output)
        self.assertIn('services.api.environment.DATABASE_URL', output)
        self.assertIn('services.api.environment.INTERNAL_API_TOKEN', output)
        self.assertIn('services.api.environment.SETTINGS_ENCRYPTION_KEY', output)
        self.assertIn('services.api.environment.OBJECT_STORE_ACCESS_KEY', output)
        self.assertIn('services.api.environment.DEFAULT_USER_PASSWORD', output)
        self.assertIn('services.postgres.environment.POSTGRES_PASSWORD', output)
        self.assertIn('services.worker.environment.COMPUTE_WORKER_IMAGE', output)
        self.assertEqual(output.count('DF_WORKERS is not set in upgrade.env'), 1)
        self.assertNotIn('private-image', output)
        self.assertNotIn('do-not-print', output)
        self.assertNotIn('ChangeMe123', output)

    def test_auth_startup_requirements_fail_before_pulling_images_without_exposing_values(self) -> None:
        for key, value in (
            ('DEFAULT_USER_PASSWORD', ''),
            ('DEFAULT_USER_PASSWORD', 'Short1'),
            ('DEFAULT_USER_PASSWORD', 'nouppercase123'),
            ('DEFAULT_USER_PASSWORD', 'NOLOWERCASE123'),
            ('DEFAULT_USER_PASSWORD', 'MissingDigits'),
            ('DEFAULT_USER_PASSWORD', 'ChangeMe123!'),
            ('DEFAULT_USER_PASSWORD', 'Replaceme123'),
            ('SETTINGS_ENCRYPTION_KEY', 'your-encryption-key-here'),
        ):
            with self.subTest(key=key, value=value):
                configuration = resolved_configuration()
                services = configuration['services']
                assert isinstance(services, dict)
                environment = services['api']['environment']
                environment[key] = value
                result = completed([], stdout=json.dumps(configuration))
                stdout = StringIO()
                stderr = StringIO()
                with patch.object(deploy.subprocess, 'run', return_value=result) as run, redirect_stdout(stdout), redirect_stderr(stderr):
                    exit_code = deploy.main([])
                self.assertEqual(exit_code, 2)
                run.assert_called_once()
                output = stdout.getvalue() + stderr.getvalue()
                self.assertIn(f'services.api.environment.{key}', output)
                if value:
                    self.assertNotIn(value, output)

    def test_configuration_and_pull_failures_stop_before_startup(self) -> None:
        secret = 'never-echo-this-credential'
        valid_config = completed([], stdout=json.dumps(resolved_configuration()))
        cases = (
            ('compose config', [completed([], 17, stdout=secret, stderr=f'DF_API_IMAGE is missing: {secret}')], 17, 1),
            ('compute image pull', [valid_config, completed([], 23)], 23, 2),
            ('compose pull', [valid_config, completed([]), completed([], 24)], 24, 3),
        )

        for label, responses, expected_exit, expected_calls in cases:
            with self.subTest(stage=label):
                stdout = StringIO()
                stderr = StringIO()
                with patch.object(deploy.subprocess, 'run', side_effect=responses) as run, redirect_stdout(stdout), redirect_stderr(stderr):
                    exit_code = deploy.main(['--env-file', 'docker/env/prod.env'])

                self.assertEqual(exit_code, expected_exit)
                self.assertEqual(run.call_count, expected_calls)
                commands = [entry.args[0] for entry in run.call_args_list]
                self.assertFalse(any('up' in command for command in commands))
                if label == 'compose config':
                    self.assertIn('DF_API_IMAGE', stdout.getvalue() + stderr.getvalue())
                self.assertNotIn(secret, stdout.getvalue() + stderr.getvalue())

    def test_missing_docker_cli_fails_without_leaking_configuration(self) -> None:
        stderr = StringIO()

        with patch.object(deploy.subprocess, 'run', side_effect=FileNotFoundError) as run, redirect_stderr(stderr):
            exit_code = deploy.main(['--check'])

        self.assertEqual(exit_code, 127)
        run.assert_called_once()
        self.assertIn("Required tool 'docker' was not found", stderr.getvalue())

    def test_missing_compose_plugin_fails_without_echoing_stderr(self) -> None:
        secret = 'never-echo-this-credential'
        result = completed([], 1, stderr=f"docker: 'compose' is not a docker command. {secret}")
        stderr = StringIO()

        with patch.object(deploy.subprocess, 'run', return_value=result) as run, redirect_stderr(stderr):
            exit_code = deploy.main(['--check'])

        self.assertEqual(exit_code, 1)
        run.assert_called_once()
        self.assertIn('Docker Compose v2 is unavailable', stderr.getvalue())
        self.assertNotIn(secret, stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
