import importlib
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[1] / 'main.py'


@pytest.mark.parametrize('module_name', ['main', '__mp_main__'])
def test_entrypoint_defers_application_import(module_name: str) -> None:
    subprocess.run(
        [
            sys.executable,
            '-c',
            'import runpy, sys; '
            'namespace = runpy.run_path(sys.argv[1], run_name=sys.argv[2]); '
            'assert "backend_core.application" not in sys.modules; '
            'assert "app" not in namespace',
            str(ENTRYPOINT),
            module_name,
        ],
        check=True,
        timeout=10,
    )


def test_entrypoint_preserves_and_caches_app_export() -> None:
    from backend_core.application import app

    entrypoint = importlib.import_module('main')

    assert entrypoint.app is app
    assert vars(entrypoint)['app'] is app
    assert entrypoint.__all__ == ['app']
    with pytest.raises(AttributeError, match='no attribute.*missing'):
        _ = entrypoint.missing


def test_entrypoint_dispatches_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend_core import application

    calls: list[None] = []

    def run_api_server() -> None:
        calls.append(None)

    monkeypatch.setattr(application, '_run_api_server', run_api_server)

    runpy.run_path(str(ENTRYPOINT), run_name='__main__')

    assert calls == [None]
