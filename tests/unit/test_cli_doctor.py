"""Tests for the CLI doctor health check."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openclaw.cli.doctor import (
    DoctorReport,
    _check_budget_state,
    _check_directories,
    _check_disk_space,
    _check_port,
    _check_system,
    _check_systemd,
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


# ---------------------------------------------------------------------------
# Disk space checks
# ---------------------------------------------------------------------------


class TestCheckDiskSpace:
    def test_sufficient_space(self, tmp_path: Path) -> None:
        settings = MagicMock()
        settings.data_dir = str(tmp_path)

        report = DoctorReport()
        _check_disk_space(report, settings)
        # Should always pass on a dev machine with space
        assert report.passed >= 1

    def test_low_space_warns(self, tmp_path: Path) -> None:
        settings = MagicMock()
        settings.data_dir = str(tmp_path)

        # Mock disk_usage to return low free space (3 GB)
        mock_usage = MagicMock()
        mock_usage.free = 3 * (1024**3)
        mock_usage.total = 500 * (1024**3)
        mock_usage.used = 497 * (1024**3)

        report = DoctorReport()
        with patch("openclaw.cli.doctor.shutil.disk_usage", return_value=mock_usage):
            _check_disk_space(report, settings)
        assert report.warnings >= 1

    def test_critical_space_errors(self, tmp_path: Path) -> None:
        settings = MagicMock()
        settings.data_dir = str(tmp_path)

        # Mock disk_usage to return critical free space (500 MB)
        mock_usage = MagicMock()
        mock_usage.free = 0.5 * (1024**3)
        mock_usage.total = 500 * (1024**3)
        mock_usage.used = 499.5 * (1024**3)

        report = DoctorReport()
        with patch("openclaw.cli.doctor.shutil.disk_usage", return_value=mock_usage):
            _check_disk_space(report, settings)
        assert report.errors >= 1

    def test_nonexistent_dir_uses_cwd(self, tmp_path: Path) -> None:
        """When data_dir doesn't exist, should fall back to cwd."""
        settings = MagicMock()
        settings.data_dir = str(tmp_path / "nonexistent")

        report = DoctorReport()
        _check_disk_space(report, settings)
        # Should still succeed (using cwd)
        assert report.passed >= 1


# ---------------------------------------------------------------------------
# Port checks
# ---------------------------------------------------------------------------


class TestCheckPort:
    def test_port_available(self) -> None:
        settings = MagicMock()
        settings.web_host = "127.0.0.1"
        settings.web_port = 59999  # Unlikely to be in use

        report = DoctorReport()
        _check_port(report, settings)
        assert report.passed >= 1

    def test_port_in_use(self) -> None:
        import socket as sock_mod

        settings = MagicMock()
        settings.web_host = "127.0.0.1"
        settings.web_port = 0  # Will be set after binding

        # Bind a socket to grab a port
        server = sock_mod.socket(sock_mod.AF_INET, sock_mod.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        _, port = server.getsockname()
        settings.web_port = port

        try:
            report = DoctorReport()
            _check_port(report, settings)
            assert report.warnings >= 1
        finally:
            server.close()

    def test_socket_error_warns(self) -> None:
        settings = MagicMock()
        settings.web_host = "127.0.0.1"
        settings.web_port = 8080

        report = DoctorReport()
        with patch("openclaw.cli.doctor.socket.socket", side_effect=OSError("mock error")):
            _check_port(report, settings)
        assert report.warnings >= 1


# ---------------------------------------------------------------------------
# Systemd checks
# ---------------------------------------------------------------------------


class TestCheckSystemd:
    def test_skips_on_non_linux(self) -> None:
        report = DoctorReport()
        with patch("openclaw.cli.doctor.platform.system", return_value="Darwin"):
            _check_systemd(report)
        assert report.total == 0

    def test_no_unit_file(self) -> None:
        report = DoctorReport()
        with (
            patch("openclaw.cli.doctor.platform.system", return_value="Linux"),
            patch("openclaw.cli.doctor.Path") as mock_path_cls,
        ):
            mock_path_cls.return_value.is_file.return_value = False
            # Use a fresh Path mock for the unit file check
            mock_unit_path = MagicMock()
            mock_unit_path.is_file.return_value = False
            mock_path_cls.return_value = mock_unit_path
            _check_systemd(report)
        # No unit file means no checks recorded (just info messages)
        assert report.errors == 0

    def test_enabled_and_active(self) -> None:
        report = DoctorReport()
        enabled_result = MagicMock()
        enabled_result.stdout = "enabled\n"
        active_result = MagicMock()
        active_result.stdout = "active\n"

        with (
            patch("openclaw.cli.doctor.platform.system", return_value="Linux"),
            patch("pathlib.Path.is_file", return_value=True),
            patch("openclaw.cli.doctor.subprocess.run", side_effect=[enabled_result, active_result]),
        ):
            _check_systemd(report)
        assert report.passed >= 2  # unit file + enabled + active

    def test_not_enabled(self) -> None:
        report = DoctorReport()
        enabled_result = MagicMock()
        enabled_result.stdout = "disabled\n"
        active_result = MagicMock()
        active_result.stdout = "inactive\n"

        with (
            patch("openclaw.cli.doctor.platform.system", return_value="Linux"),
            patch("pathlib.Path.is_file", return_value=True),
            patch("openclaw.cli.doctor.subprocess.run", side_effect=[enabled_result, active_result]),
        ):
            _check_systemd(report)
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
