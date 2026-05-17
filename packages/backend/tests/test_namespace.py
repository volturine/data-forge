from pathlib import Path

import pytest
from core.config import settings
from core.namespace import (
    get_namespace,
    list_namespaces,
    namespace_paths,
    normalize_namespace,
    set_namespace_context,
)
from fastapi.testclient import TestClient


def test_normalize_namespace_default():
    assert normalize_namespace(None) == settings.default_namespace
    assert normalize_namespace("") == settings.default_namespace


def test_normalize_namespace_rejects_invalid():
    with pytest.raises(ValueError, match="Namespace must be alphanumeric"):
        normalize_namespace("bad name")


def test_namespace_paths_creates_dirs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ENV_FILE", "")
    from core.config import Settings

    Settings()
    paths = namespace_paths("alpha")

    assert paths.base_dir == tmp_path / "data" / "namespaces" / "alpha"
    assert paths.upload_dir.is_dir()
    assert paths.clean_dir.is_dir()
    assert paths.exports_dir.is_dir()
    assert paths.db_path == tmp_path / "data" / "namespaces" / "alpha" / "namespace.db"


def test_set_namespace_context():
    token = set_namespace_context("alpha")
    try:
        assert get_namespace() == "alpha"
    finally:
        from core.namespace import reset_namespace

        reset_namespace(token)


def test_list_namespaces(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ENV_FILE", "")
    from core.config import Settings

    Settings()
    base = tmp_path / "data" / "namespaces"
    (base / "alpha").mkdir(parents=True)
    (base / "beta").mkdir(parents=True)
    (base / "file.txt").write_text("x")

    assert list_namespaces() == ["alpha", "beta"]


def test_list_namespaces_endpoint(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ENV_FILE", "")
    from core.config import Settings

    Settings()
    base = tmp_path / "data" / "namespaces"
    (base / "alpha").mkdir(parents=True)
    (base / "beta").mkdir(parents=True)

    from main import app

    client = TestClient(app)
    response = client.get("/api/v1/namespaces")

    assert response.status_code == 200
    assert response.json() == {"namespaces": ["alpha", "beta"]}
