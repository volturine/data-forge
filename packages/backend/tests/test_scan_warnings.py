import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def run_scan(command: list[str], *options: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / 'scan_warnings.py'), *options, '--', *command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_scan_warnings_fails_on_warning_output() -> None:
    result = run_scan([sys.executable, '-c', "print('DeprecationWarning: do not hide me')"])

    assert result.returncode == 1
    assert 'DeprecationWarning: do not hide me' in result.stderr


def test_scan_warnings_fails_on_standard_logger_warning() -> None:
    result = run_scan([sys.executable, '-c', "print('2026-08-09 - worker - WARNING - do not hide me')"])

    assert result.returncode == 1
    assert 'WARNING - do not hide me' in result.stderr


def test_scan_warnings_ignores_classified_warning() -> None:
    result = run_scan(
        [sys.executable, '-c', "print('2026-08-09 - backend - WARNING - InvalidCredentialsError: Invalid email or password')"],
        '--ignore-pattern',
        'InvalidCredentialsError: Invalid email or password',
    )

    assert result.returncode == 0


def test_scan_warnings_reports_nonzero_exit() -> None:
    result = run_scan([sys.executable, '-c', 'raise SystemExit(3)'])

    assert result.returncode == 3
    assert '[NONZERO_EXIT] command exited with code 3' in result.stderr
