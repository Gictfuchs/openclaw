"""Tests for the CLI setup wizard."""

from pathlib import Path
from unittest.mock import patch

import pytest

from openclaw.cli.setup import (
    _generate_plist,
    _load_existing_env,
    _validate_anthropic_key,
    _validate_telegram_token,
    _validate_telegram_user_id,
    _write_env,
)

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


class TestValidateAnthropicKey:
    def test_valid_key(self) -> None:
        assert _validate_anthropic_key("sk-ant-api03-abcdef1234567890abcdef") is True

    def test_too_short(self) -> None:
        assert _validate_anthropic_key("sk-ant-abc") is False

    def test_wrong_prefix(self) -> None:
        assert _validate_anthropic_key("key-1234567890abcdef1234567890") is False

    def test_empty(self) -> None:
        assert _validate_anthropic_key("") is False


class TestValidateTelegramToken:
    def test_valid_token(self) -> None:
        assert _validate_telegram_token("123456789:AABBccDDeeFFggHHiiJJkkLLmmNNoo") is True

    def test_missing_colon(self) -> None:
        assert _validate_telegram_token("123456789AABBccDDeeFF") is False

    def test_non_numeric_prefix(self) -> None:
        assert _validate_telegram_token("abc:AABBccDDeeFFggHH") is False

    def test_short_suffix(self) -> None:
        assert _validate_telegram_token("123456:abc") is False

    def test_empty(self) -> None:
        assert _validate_telegram_token("") is False


class TestValidateTelegramUserId:
    def test_valid_id(self) -> None:
        assert _validate_telegram_user_id("123456789") is True

    def test_zero(self) -> None:
        assert _validate_telegram_user_id("0") is False

    def test_negative(self) -> None:
        assert _validate_telegram_user_id("-1") is False

    def test_non_numeric(self) -> None:
        assert _validate_telegram_user_id("abc") is False

    def test_empty(self) -> None:
        assert _validate_telegram_user_id("") is False


# ---------------------------------------------------------------------------
# .env I/O
# ---------------------------------------------------------------------------


class TestLoadExistingEnv:
    def test_load_simple(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("KEY1=value1\nKEY2=value2\n")
        result = _load_existing_env(env_file)
        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_skip_comments(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\nKEY=val\n")
        result = _load_existing_env(env_file)
        assert result == {"KEY": "val"}

    def test_skip_empty_lines(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("\n\nKEY=val\n\n")
        result = _load_existing_env(env_file)
        assert result == {"KEY": "val"}

    def test_strip_quotes(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("KEY1=\"quoted\"\nKEY2='single'\n")
        result = _load_existing_env(env_file)
        assert result == {"KEY1": "quoted", "KEY2": "single"}

    def test_missing_file(self, tmp_path: Path) -> None:
        result = _load_existing_env(tmp_path / "nonexistent")
        assert result == {}

    def test_json_list_value(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("USERS=[123,456]\n")
        result = _load_existing_env(env_file)
        assert result == {"USERS": "[123,456]"}

    def test_value_with_equals(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value=with=equals\n")
        result = _load_existing_env(env_file)
        assert result == {"KEY": "value=with=equals"}


class TestWriteEnv:
    def test_writes_values(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        values = {
            "FOCHS_ANTHROPIC_API_KEY": "sk-ant-test",
            "FOCHS_TELEGRAM_BOT_TOKEN": "123:ABC",
        }
        _write_env(env_file, values)
        content = env_file.read_text()
        assert "FOCHS_ANTHROPIC_API_KEY=sk-ant-test" in content
        assert "FOCHS_TELEGRAM_BOT_TOKEN=123:ABC" in content

    def test_includes_section_headers(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        _write_env(env_file, {"FOCHS_ANTHROPIC_API_KEY": "test"})
        content = env_file.read_text()
        assert "# --- LLM (API) ---" in content

    def test_comments_out_empty_values(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        _write_env(env_file, {})
        content = env_file.read_text()
        # Empty values should be commented out
        assert "# FOCHS_ANTHROPIC_API_KEY=" in content

    def test_header_present(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        _write_env(env_file, {})
        content = env_file.read_text()
        assert "Generated by: fochs setup" in content

    def test_roundtrip(self, tmp_path: Path) -> None:
        """Values written and re-loaded should match."""
        env_file = tmp_path / ".env"
        values = {
            "FOCHS_ANTHROPIC_API_KEY": "sk-ant-test123",
            "FOCHS_DAILY_TOKEN_BUDGET": "500000",
            "FOCHS_TELEGRAM_ALLOWED_USERS": "[123,456]",
        }
        _write_env(env_file, values)
        loaded = _load_existing_env(env_file)
        for key, val in values.items():
            assert loaded.get(key) == val, f"{key}: {loaded.get(key)} != {val}"


# ---------------------------------------------------------------------------
# launchd plist generator
# ---------------------------------------------------------------------------


class TestGeneratePlist:
    @patch("openclaw.cli.setup.platform")
    def test_non_darwin(self, mock_platform: patch) -> None:
        mock_platform.system.return_value = "Linux"
        result = _generate_plist(Path("/tmp/test"))
        assert result is None

    @patch("openclaw.cli.setup.platform")
    @patch("openclaw.cli.setup.shutil.which")
    def test_darwin_creates_plist(self, mock_which: patch, mock_platform: patch, tmp_path: Path) -> None:
        mock_platform.system.return_value = "Darwin"
        mock_which.return_value = "/opt/homebrew/bin/uv"

        # Use tmp_path for LaunchAgents
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        with patch("openclaw.cli.setup.Path.home", return_value=tmp_path):
            result = _generate_plist(project_dir)

        assert result is not None
        assert result.is_file()
        content = result.read_text()
        assert "com.fochs.bot" in content
        assert "/opt/homebrew/bin/uv" in content
        assert str(project_dir) in content

    @patch("openclaw.cli.setup.platform")
    @patch("openclaw.cli.setup.shutil.which")
    def test_plist_creates_log_dir(self, mock_which: patch, mock_platform: patch, tmp_path: Path) -> None:
        mock_platform.system.return_value = "Darwin"
        mock_which.return_value = "/usr/local/bin/uv"

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        with patch("openclaw.cli.setup.Path.home", return_value=tmp_path):
            _generate_plist(project_dir)

        assert (project_dir / "logs").is_dir()


# ---------------------------------------------------------------------------
# Non-interactive validation
# ---------------------------------------------------------------------------


class TestValidateExistingConfig:
    def test_missing_env_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from openclaw.cli.setup import _validate_existing_config

        result = _validate_existing_config(tmp_path)
        assert result is False

    def test_valid_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from openclaw.cli.setup import _validate_existing_config

        env_file = tmp_path / ".env"
        env_file.write_text("FOCHS_ANTHROPIC_API_KEY=sk-ant-api03-valid1234567890abcdef\n")

        # Monkey-patch Settings to not require actual valid API keys
        with patch("openclaw.config.Settings"):
            result = _validate_existing_config(tmp_path)
            assert result is True

    def test_placeholder_api_key(self, tmp_path: Path) -> None:
        from openclaw.cli.setup import _validate_existing_config

        env_file = tmp_path / ".env"
        env_file.write_text("FOCHS_ANTHROPIC_API_KEY=sk-ant-...\n")

        with patch("openclaw.config.Settings"):
            result = _validate_existing_config(tmp_path)
            # Should fail because key is a placeholder
            assert result is False
