"""Tests for the CLI doctor health check."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openclaw.cli.doctor import (
    DoctorReport,
    _check_budget_state,
    _check_directories,
    _check_system,
)

# ---------------------------------------------------------------------------
# DoctorReport
# ---------------------------------------------------------------------------


class TestDoctorReport:
    def test_initial_state(self) -> None:
        report = DoctorReport()
        assert report.passed == 0
        assert report.warnings == 0
        assert report.errors == 0
        assert report.total == 0

    def test_ok_increments(self) -> None:
        report = DoctorReport()
        report.ok("test")
        assert report.passed == 1
        assert report.total == 1

    def test_warn_increments(self) -> None:
        report = DoctorReport()
        report.warn("test")
        assert report.warnings == 1
        assert report.total == 1

    def test_err_increments(self) -> None:
        report = DoctorReport()
        report.err("test")
        assert report.errors == 1
        assert report.total == 1

    def test_mixed_counts(self) -> None:
        report = DoctorReport()
        report.ok("a")
        report.ok("b")
        report.warn("c")
        report.err("d")
        assert report.passed == 2
        assert report.warnings == 1
        assert report.errors == 1
        assert report.total == 4


# ---------------------------------------------------------------------------
# System checks
# ---------------------------------------------------------------------------


class TestCheckSystem:
    def test_detects_python_version(self) -> None:
        report = DoctorReport()
        _check_system(report)
        # Should at least detect Python (we're running it!)
        assert report.passed >= 1

    def test_reports_old_python(self) -> None:
        """Simulate old Python by mocking version_info with named attributes."""
        mock_version = MagicMock()
        mock_version.major = 3
        mock_version.minor = 11
        mock_version.micro = 0
        mock_version.__ge__ = lambda self, other: (self.major, self.minor, self.micro) >= other
        mock_version.__lt__ = lambda self, other: (self.major, self.minor, self.micro) < other

        with patch("openclaw.cli.doctor.sys") as mock_sys:
            mock_sys.version_info = mock_version
            report = DoctorReport()
            _check_system(report)
            assert report.errors >= 1


# ---------------------------------------------------------------------------
# Directory checks
# ---------------------------------------------------------------------------


class TestCheckDirectories:
    def test_existing_data_dir(self, tmp_path: Path) -> None:
        settings = MagicMock()
        settings.data_dir = str(tmp_path)
        settings.chroma_path = str(tmp_path / "chroma")
        settings.plugins_dir = str(tmp_path / "plugins")
        (tmp_path / "chroma").mkdir()
        (tmp_path / "plugins").mkdir()

        report = DoctorReport()
        _check_directories(report, settings)
        assert report.passed >= 2

    def test_missing_data_dir(self, tmp_path: Path) -> None:
        settings = MagicMock()
        settings.data_dir = str(tmp_path / "nonexistent")
        settings.chroma_path = str(tmp_path / "nonexistent" / "chroma")
        settings.plugins_dir = str(tmp_path / "nonexistent" / "plugins")

        report = DoctorReport()
        _check_directories(report, settings)
        assert report.warnings >= 1

    def test_plugins_with_files(self, tmp_path: Path) -> None:
        settings = MagicMock()
        settings.data_dir = str(tmp_path)
        settings.chroma_path = str(tmp_path / "chroma")
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "my_tool.py").write_text("# plugin")
        (plugins_dir / "__init__.py").write_text("# init")
        settings.plugins_dir = str(plugins_dir)

        report = DoctorReport()
        _check_directories(report, settings)
        # Should report 1 plugin file (not counting __init__.py)
        assert report.passed >= 1


# ---------------------------------------------------------------------------
# Budget state checks
# ---------------------------------------------------------------------------


class TestCheckBudgetState:
    def test_no_budget_file(self, tmp_path: Path) -> None:
        settings = MagicMock()
        settings.data_dir = str(tmp_path)
        settings.daily_token_budget = 500_000
        settings.monthly_token_budget = 10_000_000

        report = DoctorReport()
        _check_budget_state(report, settings)
        # No file — just an info, no error or warning
        assert report.errors == 0

    def test_valid_budget_file(self, tmp_path: Path) -> None:
        settings = MagicMock()
        settings.data_dir = str(tmp_path)
        settings.daily_token_budget = 500_000
        settings.monthly_token_budget = 10_000_000

        budget_file = tmp_path / "budget_state.json"
        budget_file.write_text(
            json.dumps(
                {
                    "daily_usage": 10_000,
                    "monthly_usage": 50_000,
                    "date": "2025-01-15",
                }
            )
        )

        report = DoctorReport()
        _check_budget_state(report, settings)
        assert report.passed >= 1
        assert report.errors == 0

    def test_budget_near_limit(self, tmp_path: Path) -> None:
        settings = MagicMock()
        settings.data_dir = str(tmp_path)
        settings.daily_token_budget = 500_000
        settings.monthly_token_budget = 10_000_000

        budget_file = tmp_path / "budget_state.json"
        budget_file.write_text(
            json.dumps(
                {
                    "daily_usage": 450_000,  # >80%
                    "monthly_usage": 50_000,
                    "date": "2025-01-15",
                }
            )
        )

        report = DoctorReport()
        _check_budget_state(report, settings)
        assert report.warnings >= 1


# ---------------------------------------------------------------------------
# Optional integrations
# ---------------------------------------------------------------------------


class TestCheckOptionalIntegrations:
    def test_all_configured(self) -> None:
        from openclaw.cli.doctor import _check_optional_integrations

        settings = MagicMock()
        settings.composio_api_key.get_secret_value.return_value = "comp-key"
        settings.clawhub_api_key.get_secret_value.return_value = "ch-key"
        settings.virustotal_api_key.get_secret_value.return_value = "vt-key"
        settings.honcho_api_key.get_secret_value.return_value = "hn-key"
        settings.agentmail_api_key.get_secret_value.return_value = "am-key"
        settings.email_address = "test@example.com"
        settings.email_imap_host = "imap.example.com"
        settings.clawhub_auto_scan = True

        report = DoctorReport()
        _check_optional_integrations(report, settings)
        assert report.passed >= 5

    def test_none_configured(self) -> None:
        from openclaw.cli.doctor import _check_optional_integrations

        settings = MagicMock()
        settings.composio_api_key.get_secret_value.return_value = ""
        settings.clawhub_api_key.get_secret_value.return_value = ""
        settings.virustotal_api_key.get_secret_value.return_value = ""
        settings.honcho_api_key.get_secret_value.return_value = ""
        settings.agentmail_api_key.get_secret_value.return_value = ""
        settings.email_address = ""
        settings.email_imap_host = ""
        settings.clawhub_auto_scan = True

        report = DoctorReport()
        _check_optional_integrations(report, settings)
        assert report.passed == 0
        assert report.errors == 0  # No errors for missing optional integrations

    def test_clawhub_without_virustotal_warns(self) -> None:
        from openclaw.cli.doctor import _check_optional_integrations

        settings = MagicMock()
        settings.composio_api_key.get_secret_value.return_value = ""
        settings.clawhub_api_key.get_secret_value.return_value = "ch-key"
        settings.virustotal_api_key.get_secret_value.return_value = ""  # Missing!
        settings.honcho_api_key.get_secret_value.return_value = ""
        settings.agentmail_api_key.get_secret_value.return_value = ""
        settings.email_address = ""
        settings.email_imap_host = ""
        settings.clawhub_auto_scan = True

        report = DoctorReport()
        _check_optional_integrations(report, settings)
        assert report.warnings >= 1


# ---------------------------------------------------------------------------
# Full doctor run (integration-ish)
# ---------------------------------------------------------------------------


class TestRunDoctor:
    async def test_run_doctor_no_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Doctor should not crash even without .env."""
        from openclaw.cli.doctor import run_doctor

        monkeypatch.chdir(tmp_path)
        # Should complete without exceptions
        await run_doctor()
