"""Tests for Settings configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from openclaw.config import Settings


class TestSettingsDefaults:
    """Test that default values are sensible for first deployment."""

    def test_loads_without_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Settings should load with all defaults when no .env exists."""
        monkeypatch.chdir(tmp_path)
        settings = Settings()
        assert settings.anthropic_api_key.get_secret_value() == ""
        assert settings.shell_mode == "restricted"
        assert settings.autonomy_level == "full"

    def test_default_shell_mode_is_restricted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        settings = Settings()
        assert settings.shell_mode == "restricted"

    def test_default_budget_values(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        settings = Settings()
        assert settings.daily_token_budget == 500_000
        assert settings.monthly_token_budget == 10_000_000
        assert settings.max_tokens_per_run == 50_000

    def test_default_web_port(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        settings = Settings()
        assert settings.web_port == 8080
        assert settings.web_host == "127.0.0.1"


class TestSettingsFromEnv:
    """Test loading settings from environment variables."""

    def test_anthropic_key_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FOCHS_ANTHROPIC_API_KEY", "sk-ant-test-key-12345")
        settings = Settings()
        assert settings.anthropic_api_key.get_secret_value() == "sk-ant-test-key-12345"

    def test_shell_mode_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FOCHS_SHELL_MODE", "standard")
        settings = Settings()
        assert settings.shell_mode == "standard"

    def test_invalid_shell_mode_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FOCHS_SHELL_MODE", "YOLO")
        with pytest.raises(ValidationError):
            Settings()

    def test_invalid_web_port_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FOCHS_WEB_PORT", "99999")
        with pytest.raises(ValidationError):
            Settings()

    def test_telegram_users_parsed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FOCHS_TELEGRAM_ALLOWED_USERS", "[123,456]")
        settings = Settings()
        assert settings.telegram_allowed_users == [123, 456]


class TestSettingsValidation:
    """Test field validators."""

    def test_empty_allowed_dirs_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FOCHS_SHELL_ALLOWED_DIRS", "[]")
        with pytest.raises(ValidationError, match="at least one directory"):
            Settings()


class TestSettingsProperties:
    """Test computed properties."""

    def test_db_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FOCHS_DATA_DIR", "/opt/fochs/data")
        settings = Settings()
        assert settings.db_path == "/opt/fochs/data/fochs.db"

    def test_chroma_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FOCHS_DATA_DIR", "/opt/fochs/data")
        settings = Settings()
        assert settings.chroma_path == "/opt/fochs/data/chroma"

    def test_log_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FOCHS_DATA_DIR", "/opt/fochs/data")
        settings = Settings()
        assert settings.log_dir == "/opt/fochs/data/logs"
