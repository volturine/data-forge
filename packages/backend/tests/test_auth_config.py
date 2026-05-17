import warnings
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend_core.auth_config import AuthSettings


def _set_isolated_auth_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env_file))
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@host:5432/db")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    return env_file


def test_default_auth_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_isolated_auth_env(monkeypatch, tmp_path)

    settings = AuthSettings()

    assert settings.auth_required is False
    assert settings.verify_email_address is True
    assert settings.default_user_email == "default@example.com"
    assert settings.default_user_name == "Default User"
    assert settings.session_max_age_days == 30


def test_verify_email_address_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_isolated_auth_env(monkeypatch, tmp_path)
    monkeypatch.setenv("VERIFY_EMAIL_ADDRESS", "false")

    settings = AuthSettings()

    assert settings.verify_email_address is False


def test_warns_when_auth_required_without_encryption_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_isolated_auth_env(monkeypatch, tmp_path)
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.delenv("SETTINGS_ENCRYPTION_KEY", raising=False)

    with pytest.warns(UserWarning, match="SETTINGS_ENCRYPTION_KEY is empty while AUTH_REQUIRED=True"):
        AuthSettings()


def test_no_warning_when_auth_disabled_without_encryption_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_isolated_auth_env(monkeypatch, tmp_path)
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    monkeypatch.delenv("SETTINGS_ENCRYPTION_KEY", raising=False)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        settings = AuthSettings()

    assert settings.auth_required is False
    assert not caught


def test_rejects_production_auth_without_encryption_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_isolated_auth_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PROD_MODE_ENABLED", "true")
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.delenv("SETTINGS_ENCRYPTION_KEY", raising=False)

    with pytest.raises(ValidationError, match="SETTINGS_ENCRYPTION_KEY must be set"):
        AuthSettings()


def test_rejects_production_placeholder_default_password(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_isolated_auth_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PROD_MODE_ENABLED", "true")
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "prod-key")
    monkeypatch.setenv("DEFAULT_USER_PASSWORD", "ChangeMe123!")

    with pytest.raises(ValidationError, match="DEFAULT_USER_PASSWORD must be changed"):
        AuthSettings()
