import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / 'scripts' / 'e2e' / 'test_selection.sh'
BASH = shutil.which('bash') or '/bin/bash'


def make_frontend_tree(root: Path, files: tuple[str, ...]) -> None:
    for filename in files:
        test_file = root / filename
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.touch()


def run_selection(frontend_root: Path, *, path: str | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if path is not None:
        environment['PATH'] = path
    return subprocess.run(
        [
            BASH,
            '-euo',
            'pipefail',
            '-c',
            'source "$1"; select_default_playwright_tests "$2"; printf "__PLAYWRIGHT_STARTED__\\n"',
            'e2e-selection-test',
            str(HELPER),
            str(frontend_root),
        ],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )


def test_default_selection_excludes_architecture_and_concurrency_suites(tmp_path: Path) -> None:
    make_frontend_tree(
        tmp_path,
        (
            'tests/analysis.test.ts',
            'tests/concurrency.test.ts',
            'tests/datasource-compute-isolation.test.ts',
            'tests/runtime-architecture.test.ts',
            'tests/nested/chart.test.ts',
        ),
    )

    result = run_selection(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        'tests/analysis.test.ts',
        'tests/nested/chart.test.ts',
        '__PLAYWRIGHT_STARTED__',
    ]


def test_default_selection_rejects_empty_ordinary_suite(tmp_path: Path) -> None:
    make_frontend_tree(
        tmp_path,
        (
            'tests/concurrency.test.ts',
            'tests/datasource-compute-isolation.test.ts',
            'tests/runtime-architecture.test.ts',
        ),
    )

    result = run_selection(tmp_path)

    assert result.returncode != 0
    assert 'No ordinary E2E Playwright tests remain' in result.stderr
    assert '__PLAYWRIGHT_STARTED__' not in result.stdout


def test_missing_ripgrep_fails_before_playwright(tmp_path: Path) -> None:
    make_frontend_tree(tmp_path, ('tests/analysis.test.ts',))
    command_directory = tmp_path / 'bin'
    command_directory.mkdir()
    sort_path = shutil.which('sort')
    assert sort_path is not None
    (command_directory / 'sort').symlink_to(sort_path)

    result = run_selection(tmp_path, path=str(command_directory))

    assert result.returncode != 0
    assert 'Could not discover E2E Playwright tests' in result.stderr
    assert '__PLAYWRIGHT_STARTED__' not in result.stdout
