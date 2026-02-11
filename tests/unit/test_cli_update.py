"""Tests for the CLI update command."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openclaw.cli._helpers import find_project_dir
from openclaw.cli.update import (
    _detect_service_manager,
    _restart_service,
    _run,
)

# ---------------------------------------------------------------------------
# _run helper
# ---------------------------------------------------------------------------


class TestRunHelper:
    def test_returns_completed_process(self) -> None:
        result = _run(["echo", "hello"])
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_timeout_raises(self) -> None:
        import subprocess

        with pytest.raises(subprocess.TimeoutExpired):
            _run(["sleep", "10"], timeout=1)


# ---------------------------------------------------------------------------
# Service manager detection
# ---------------------------------------------------------------------------


class TestDetectServiceManager:
    def test_detects_systemd_on_linux(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        with (
            patch("openclaw.cli.update.platform.system", return_value="Linux"),
            patch("openclaw.cli.update._run", return_value=mock_result),
        ):
            assert _detect_service_manager() == "systemd"

    def test_no_systemd_on_linux(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        with (
            patch("openclaw.cli.update.platform.system", return_value="Linux"),
            patch("openclaw.cli.update._run", return_value=mock_result),
        ):
            assert _detect_service_manager() is None

    def test_detects_launchd_on_macos(self, tmp_path: Path) -> None:
        plist = tmp_path / "Library" / "LaunchAgents" / "com.fochs.bot.plist"
        plist.parent.mkdir(parents=True)
        plist.write_text("<plist/>")
        with (
            patch("openclaw.cli.update.platform.system", return_value="Darwin"),
            patch("openclaw.cli.update.Path.home", return_value=tmp_path),
        ):
            assert _detect_service_manager() == "launchd"

    def test_no_launchd_on_macos(self, tmp_path: Path) -> None:
        with (
            patch("openclaw.cli.update.platform.system", return_value="Darwin"),
            patch("openclaw.cli.update.Path.home", return_value=tmp_path),
        ):
            assert _detect_service_manager() is None

    def test_returns_none_on_windows(self) -> None:
        with patch("openclaw.cli.update.platform.system", return_value="Windows"):
            assert _detect_service_manager() is None


# ---------------------------------------------------------------------------
# Service restart
# ---------------------------------------------------------------------------


class TestRestartService:
    def test_systemd_restart_success(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("openclaw.cli.update._run", return_value=mock_result):
            assert _restart_service("systemd") is True

    def test_systemd_restart_failure(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("openclaw.cli.update._run", return_value=mock_result):
            assert _restart_service("systemd") is False

    def test_launchd_restart_success(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("openclaw.cli.update._run", return_value=mock_result):
            assert _restart_service("launchd") is True

    def test_unknown_manager_returns_false(self) -> None:
        assert _restart_service("unknown") is False

    def test_file_not_found_returns_false(self) -> None:
        with patch("openclaw.cli.update._run", side_effect=FileNotFoundError):
            assert _restart_service("systemd") is False


# ---------------------------------------------------------------------------
# Project root discovery
# ---------------------------------------------------------------------------


class TestFindProjectDir:
    def test_finds_pyproject_in_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        monkeypatch.chdir(tmp_path)
        assert find_project_dir() == tmp_path

    def test_walks_up_parents(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        sub = tmp_path / "src" / "deep"
        sub.mkdir(parents=True)
        monkeypatch.chdir(sub)
        assert find_project_dir() == tmp_path


# ---------------------------------------------------------------------------
# run_update flow (mocked end-to-end)
# ---------------------------------------------------------------------------


class TestRunUpdate:
    def test_dry_run_shows_updates(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Dry run should show pending updates but not apply them."""
        from openclaw.cli.update import run_update

        # Setup fake git repo
        (tmp_path / ".git").mkdir()
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        monkeypatch.chdir(tmp_path)

        fetch_result = MagicMock(returncode=0)
        log_result = MagicMock(returncode=0, stdout="abc1234 feat: new feature\n")
        diff_result = MagicMock(returncode=0, stdout=" 3 files changed, 10 insertions(+)\n")

        call_count = 0

        def _fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if "fetch" in cmd:
                return fetch_result
            if "log" in cmd:
                return log_result
            if "diff" in cmd:
                return diff_result
            return MagicMock(returncode=0)

        with patch("openclaw.cli.update._run", side_effect=_fake_run):
            run_update(dry_run=True)

    def test_exits_on_no_git_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should exit when .git directory is missing."""
        from openclaw.cli.update import run_update

        (tmp_path / "pyproject.toml").write_text("[project]\n")
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit):
            run_update(dry_run=False)

    def test_already_up_to_date(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return early when already up to date."""
        from openclaw.cli.update import run_update

        (tmp_path / ".git").mkdir()
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        monkeypatch.chdir(tmp_path)

        def _fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            if "fetch" in cmd:
                return MagicMock(returncode=0)
            if "log" in cmd:
                return MagicMock(returncode=0, stdout="")
            return MagicMock(returncode=0)

        with patch("openclaw.cli.update._run", side_effect=_fake_run):
            # Should complete without error
            run_update(dry_run=False)

    def test_exits_on_dirty_workdir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should exit when there are uncommitted changes."""
        from openclaw.cli.update import run_update

        (tmp_path / ".git").mkdir()
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        monkeypatch.chdir(tmp_path)

        def _fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            if "fetch" in cmd:
                return MagicMock(returncode=0)
            if "log" in cmd:
                return MagicMock(returncode=0, stdout="abc feat: stuff\n")
            if "status" in cmd:
                return MagicMock(returncode=0, stdout="M dirty_file.py\n")
            return MagicMock(returncode=0)

        with (
            patch("openclaw.cli.update._run", side_effect=_fake_run),
            pytest.raises(SystemExit),
        ):
            run_update(dry_run=False)
