"""Tests for the CLI preflight bootstrap command."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from openclaw.cli.preflight import (
    _check_prereqs,
    _ensure_dirs,
    _ensure_env_file,
)

# ---------------------------------------------------------------------------
# Prerequisites check
# ---------------------------------------------------------------------------


class TestCheckPrereqs:
    def test_passes_on_current_python(self, capsys: object) -> None:
        """Should pass when Python >= 3.12 and uv/git are present."""
        with patch("openclaw.cli.preflight.shutil.which", return_value="/usr/bin/fake"):
            result = _check_prereqs()
        assert result is True

    def test_fails_on_old_python(self) -> None:
        """Should fail when Python < 3.12."""
        mock_version = MagicMock()
        mock_version.major = 3
        mock_version.minor = 11
        mock_version.micro = 0
        mock_version.__ge__ = lambda self, other: (self.major, self.minor, self.micro) >= other
        mock_version.__lt__ = lambda self, other: (self.major, self.minor, self.micro) < other

        with (
            patch("openclaw.cli.preflight.sys") as mock_sys,
            patch("openclaw.cli.preflight.shutil.which", return_value="/usr/bin/fake"),
        ):
            mock_sys.version_info = mock_version
            result = _check_prereqs()
        assert result is False

    def test_fails_when_uv_missing(self) -> None:
        """Should fail when uv is not found."""

        def _which(cmd: str) -> str | None:
            return None if cmd == "uv" else "/usr/bin/fake"

        with patch("openclaw.cli.preflight.shutil.which", side_effect=_which):
            result = _check_prereqs()
        assert result is False

    def test_fails_when_git_missing(self) -> None:
        """Should fail when git is not found."""

        def _which(cmd: str) -> str | None:
            return None if cmd == "git" else "/usr/bin/fake"

        with patch("openclaw.cli.preflight.shutil.which", side_effect=_which):
            result = _check_prereqs()
        assert result is False


# ---------------------------------------------------------------------------
# Env file handling
# ---------------------------------------------------------------------------


class TestEnsureEnvFile:
    def test_copies_example_when_no_env(self, tmp_path: Path) -> None:
        (tmp_path / ".env.example").write_text("KEY=value\n")
        _ensure_env_file(tmp_path)
        assert (tmp_path / ".env").is_file()
        assert (tmp_path / ".env").read_text() == "KEY=value\n"

    def test_skips_when_env_exists(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("EXISTING=true\n")
        (tmp_path / ".env.example").write_text("KEY=value\n")
        _ensure_env_file(tmp_path)
        assert (tmp_path / ".env").read_text() == "EXISTING=true\n"

    def test_warns_when_neither_exists(self, tmp_path: Path, capsys: object) -> None:
        _ensure_env_file(tmp_path)
        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "No .env" in captured.out


# ---------------------------------------------------------------------------
# Directory creation
# ---------------------------------------------------------------------------


class TestEnsureDirs:
    def test_creates_all_dirs(self, tmp_path: Path) -> None:
        _ensure_dirs(tmp_path)
        assert (tmp_path / "data").is_dir()
        assert (tmp_path / "data" / "chroma").is_dir()
        assert (tmp_path / "data" / "logs").is_dir()
        assert (tmp_path / "plugins").is_dir()

    def test_idempotent(self, tmp_path: Path) -> None:
        """Running twice should not raise."""
        _ensure_dirs(tmp_path)
        _ensure_dirs(tmp_path)
        assert (tmp_path / "data").is_dir()

    def test_respects_data_dir_from_env(self, tmp_path: Path) -> None:
        """Should read FOCHS_DATA_DIR from .env when available."""
        env_content = "FOCHS_DATA_DIR=./custom_data\n"
        (tmp_path / ".env").write_text(env_content)
        _ensure_dirs(tmp_path)
        assert (tmp_path / "custom_data").is_dir()
        assert (tmp_path / "custom_data" / "chroma").is_dir()
        assert (tmp_path / "custom_data" / "logs").is_dir()

    def test_respects_plugins_dir_from_env(self, tmp_path: Path) -> None:
        """Should read FOCHS_PLUGINS_DIR from .env when available."""
        env_content = "FOCHS_PLUGINS_DIR=./my_plugins\n"
        (tmp_path / ".env").write_text(env_content)
        _ensure_dirs(tmp_path)
        assert (tmp_path / "my_plugins").is_dir()

    def test_handles_absolute_path_in_env(self, tmp_path: Path) -> None:
        """Should handle absolute paths in .env."""
        abs_data = tmp_path / "abs_data"
        env_content = f"FOCHS_DATA_DIR={abs_data}\n"
        (tmp_path / ".env").write_text(env_content)
        _ensure_dirs(tmp_path)
        assert abs_data.is_dir()
