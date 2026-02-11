"""Tests for the CLI preflight bootstrap command."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openclaw.cli.preflight import (
    _check_prereqs,
    _ensure_dirs,
    _ensure_env_file,
    _find_project_dir,
    _run_uv_sync,
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
# uv sync
# ---------------------------------------------------------------------------


class TestRunUvSync:
    def test_success(self, tmp_path: Path) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("openclaw.cli.preflight.subprocess.run", return_value=mock_result):
            assert _run_uv_sync(tmp_path) is True

    def test_failure(self, tmp_path: Path) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error: some problem"
        with patch("openclaw.cli.preflight.subprocess.run", return_value=mock_result):
            assert _run_uv_sync(tmp_path) is False

    def test_timeout(self, tmp_path: Path) -> None:
        import subprocess

        with patch(
            "openclaw.cli.preflight.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="uv sync", timeout=300),
        ):
            assert _run_uv_sync(tmp_path) is False


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


# ---------------------------------------------------------------------------
# Project root discovery
# ---------------------------------------------------------------------------


class TestFindProjectDir:
    def test_finds_pyproject_in_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        monkeypatch.chdir(tmp_path)
        assert _find_project_dir() == tmp_path

    def test_walks_up_parents(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        sub = tmp_path / "src" / "deep"
        sub.mkdir(parents=True)
        monkeypatch.chdir(sub)
        assert _find_project_dir() == tmp_path

    def test_returns_cwd_when_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = _find_project_dir()
        assert result == tmp_path
