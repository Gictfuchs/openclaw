"""Tests for shared CLI helpers."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openclaw.cli._helpers import (
    TIMEOUT_GIT_FETCH,
    TIMEOUT_GIT_PULL,
    TIMEOUT_SERVICE_CMD,
    TIMEOUT_STATUS_CMD,
    TIMEOUT_UV_SYNC,
    find_project_dir,
    run_uv_sync,
)

# ---------------------------------------------------------------------------
# Timeout constants
# ---------------------------------------------------------------------------


class TestTimeoutConstants:
    def test_uv_sync_timeout(self) -> None:
        assert TIMEOUT_UV_SYNC == 300

    def test_git_fetch_timeout(self) -> None:
        assert TIMEOUT_GIT_FETCH == 30

    def test_git_pull_timeout(self) -> None:
        assert TIMEOUT_GIT_PULL == 120

    def test_service_cmd_timeout(self) -> None:
        assert TIMEOUT_SERVICE_CMD == 15

    def test_status_cmd_timeout(self) -> None:
        assert TIMEOUT_STATUS_CMD == 5


# ---------------------------------------------------------------------------
# find_project_dir
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

    def test_returns_cwd_when_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = find_project_dir()
        assert result == tmp_path


# ---------------------------------------------------------------------------
# run_uv_sync
# ---------------------------------------------------------------------------


class TestRunUvSync:
    def test_success(self, tmp_path: Path) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        with (
            patch("openclaw.cli._helpers.shutil.which", return_value="/usr/bin/uv"),
            patch("openclaw.cli._helpers.subprocess.run", return_value=mock_result),
        ):
            assert run_uv_sync(tmp_path) is True

    def test_failure(self, tmp_path: Path) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error: something went wrong"
        with (
            patch("openclaw.cli._helpers.shutil.which", return_value="/usr/bin/uv"),
            patch("openclaw.cli._helpers.subprocess.run", return_value=mock_result),
        ):
            assert run_uv_sync(tmp_path) is False

    def test_timeout(self, tmp_path: Path) -> None:
        with (
            patch("openclaw.cli._helpers.shutil.which", return_value="/usr/bin/uv"),
            patch(
                "openclaw.cli._helpers.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="uv sync", timeout=300),
            ),
        ):
            assert run_uv_sync(tmp_path) is False

    def test_uv_not_found(self, tmp_path: Path) -> None:
        with patch("openclaw.cli._helpers.shutil.which", return_value=None):
            assert run_uv_sync(tmp_path) is False

    def test_file_not_found(self, tmp_path: Path) -> None:
        with (
            patch("openclaw.cli._helpers.shutil.which", return_value="/usr/bin/uv"),
            patch("openclaw.cli._helpers.subprocess.run", side_effect=FileNotFoundError),
        ):
            assert run_uv_sync(tmp_path) is False

    def test_quiet_mode(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        with (
            patch("openclaw.cli._helpers.shutil.which", return_value="/usr/bin/uv"),
            patch("openclaw.cli._helpers.subprocess.run", return_value=mock_result),
        ):
            run_uv_sync(tmp_path, quiet=True)
        captured = capsys.readouterr()
        assert "Running uv sync" not in captured.out
