"""Tests for the ClawHub + VirusTotal tools."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openclaw.integrations.clawhub import (
    ClawHubClient,
    SkillInfo,
    SkillSearchResponse,
    SkillSecurityReport,
)
from openclaw.integrations.virustotal import ScanResult, VirusTotalClient
from openclaw.tools.clawhub_tools import (
    ClawHubInstallTool,
    ClawHubSearchTool,
    ClawHubSecurityTool,
)


@pytest.fixture
def mock_client() -> AsyncMock:
    return AsyncMock(spec=ClawHubClient)


@pytest.fixture
def mock_vt() -> AsyncMock:
    return AsyncMock(spec=VirusTotalClient)


# ---------------------------------------------------------------------------
# VirusTotal Client Tests
# ---------------------------------------------------------------------------


class TestVirusTotalClient:
    """Basic tests for the VT scan result dataclass."""

    def test_safe_result(self) -> None:
        result = ScanResult(resource_id="test", positives=0, total=70, is_safe=True)
        assert result.is_safe is True
        assert result.positives == 0

    def test_unsafe_result(self) -> None:
        result = ScanResult(resource_id="test", positives=5, total=70, is_safe=False)
        assert result.is_safe is False
        assert result.positives == 5


# ---------------------------------------------------------------------------
# ClawHub Search Tool
# ---------------------------------------------------------------------------


class TestClawHubSearchTool:
    async def test_execute_formats_results(self, mock_client: AsyncMock) -> None:
        mock_client.search.return_value = SkillSearchResponse(
            query="calendar",
            total=2,
            skills=[
                SkillInfo(
                    id="cal-sync",
                    name="Calendar Sync",
                    description="Sync Google Calendar",
                    verified=True,
                    rating=4.5,
                    downloads=1200,
                ),
                SkillInfo(
                    id="reminder-bot",
                    name="Reminder Bot",
                    description="Set reminders",
                ),
            ],
        )

        tool = ClawHubSearchTool(client=mock_client)
        result = await tool.execute(query="calendar")

        assert "Calendar Sync" in result
        assert "cal-sync" in result
        assert "[verified]" in result
        assert "4.5" in result
        assert "1200" in result
        assert "Reminder Bot" in result

    async def test_execute_no_results(self, mock_client: AsyncMock) -> None:
        mock_client.search.return_value = SkillSearchResponse(query="zzz")

        tool = ClawHubSearchTool(client=mock_client)
        result = await tool.execute(query="zzz")

        assert "No skills" in result

    async def test_execute_handles_error(self, mock_client: AsyncMock) -> None:
        mock_client.search.side_effect = Exception("API error")

        tool = ClawHubSearchTool(client=mock_client)
        result = await tool.execute(query="test")

        assert "failed" in result.lower()

    async def test_limit_capped(self, mock_client: AsyncMock) -> None:
        mock_client.search.return_value = SkillSearchResponse(query="test")

        tool = ClawHubSearchTool(client=mock_client)
        await tool.execute(query="test", limit=100)

        mock_client.search.assert_called_once_with(query="test", limit=20)

    def test_tool_definition(self, mock_client: AsyncMock) -> None:
        tool = ClawHubSearchTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "clawhub_search"
        assert "query" in defn["input_schema"]["properties"]


# ---------------------------------------------------------------------------
# ClawHub Install Tool (with security checks)
# ---------------------------------------------------------------------------


class TestClawHubInstallTool:
    async def test_execute_successful_install(self, mock_client: AsyncMock) -> None:
        mock_client.install_skill.return_value = "Skill 'cal-sync' installed successfully."

        tool = ClawHubInstallTool(client=mock_client)
        result = await tool.execute(skill_id="cal-sync")

        assert "installed successfully" in result

    async def test_execute_blocked_by_virustotal(self, mock_client: AsyncMock) -> None:
        mock_client.install_skill.return_value = (
            "BLOCKED: Skill 'evil-tool' flagged by VirusTotal (3/70 detections). Installation refused."
        )

        tool = ClawHubInstallTool(client=mock_client)
        result = await tool.execute(skill_id="evil-tool")

        assert "BLOCKED" in result
        assert "VirusTotal" in result

    async def test_execute_blocked_by_blocklist(self, mock_client: AsyncMock) -> None:
        mock_client.install_skill.return_value = (
            "BLOCKED: Skill 'claw-havoc' is on the ClawHavoc blocklist. "
            "Reason: Confirmed malware. Installation refused."
        )

        tool = ClawHubInstallTool(client=mock_client)
        result = await tool.execute(skill_id="claw-havoc")

        assert "BLOCKED" in result
        assert "ClawHavoc" in result

    async def test_execute_empty_skill_id(self, mock_client: AsyncMock) -> None:
        tool = ClawHubInstallTool(client=mock_client)
        result = await tool.execute(skill_id="  ")

        assert "empty" in result.lower()
        mock_client.install_skill.assert_not_called()

    async def test_execute_handles_error(self, mock_client: AsyncMock) -> None:
        mock_client.install_skill.side_effect = Exception("Network error")

        tool = ClawHubInstallTool(client=mock_client)
        result = await tool.execute(skill_id="test")

        assert "failed" in result.lower()

    def test_tool_definition(self, mock_client: AsyncMock) -> None:
        tool = ClawHubInstallTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "clawhub_install"
        assert "skill_id" in defn["input_schema"]["properties"]


# ---------------------------------------------------------------------------
# ClawHub Security Tool
# ---------------------------------------------------------------------------


class TestClawHubSecurityTool:
    async def test_execute_safe_skill(self, mock_client: AsyncMock) -> None:
        mock_client.get_security_report.return_value = SkillSecurityReport(
            skill_id="cal-sync",
            skill_name="Calendar Sync",
            vt_scan=ScanResult(
                resource_id="https://pkg.clawhub.ai/cal-sync",
                positives=0,
                total=70,
                is_safe=True,
                permalink="https://www.virustotal.com/gui/url/abc",
            ),
            on_blocklist=False,
            safe_to_install=True,
        )

        tool = ClawHubSecurityTool(client=mock_client)
        result = await tool.execute(skill_id="cal-sync")

        assert "CLEAN" in result
        assert "SAFE" in result
        assert "0/70" in result

    async def test_execute_unsafe_skill(self, mock_client: AsyncMock) -> None:
        mock_client.get_security_report.return_value = SkillSecurityReport(
            skill_id="evil-tool",
            skill_name="Evil Tool",
            vt_scan=ScanResult(
                resource_id="https://pkg.clawhub.ai/evil",
                positives=5,
                total=70,
                is_safe=False,
            ),
            on_blocklist=True,
            blocklist_reason="Part of ClawHavoc batch",
            safe_to_install=False,
        )

        tool = ClawHubSecurityTool(client=mock_client)
        result = await tool.execute(skill_id="evil-tool")

        assert "FLAGGED" in result
        assert "5/70" in result
        assert "BLOCKLIST: YES" in result
        assert "DO NOT INSTALL" in result

    async def test_execute_no_vt_scan(self, mock_client: AsyncMock) -> None:
        mock_client.get_security_report.return_value = SkillSecurityReport(
            skill_id="no-scan",
            skill_name="No Scan Skill",
            vt_scan=None,
            safe_to_install=True,
        )

        tool = ClawHubSecurityTool(client=mock_client)
        result = await tool.execute(skill_id="no-scan")

        assert "Not scanned" in result

    async def test_execute_empty_skill_id(self, mock_client: AsyncMock) -> None:
        tool = ClawHubSecurityTool(client=mock_client)
        result = await tool.execute(skill_id="  ")

        assert "empty" in result.lower()
        mock_client.get_security_report.assert_not_called()

    async def test_execute_handles_error(self, mock_client: AsyncMock) -> None:
        mock_client.get_security_report.side_effect = Exception("API error")

        tool = ClawHubSecurityTool(client=mock_client)
        result = await tool.execute(skill_id="test")

        assert "failed" in result.lower()

    def test_tool_definition(self, mock_client: AsyncMock) -> None:
        tool = ClawHubSecurityTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "clawhub_security"
        assert "skill_id" in defn["input_schema"]["properties"]


# ---------------------------------------------------------------------------
# ClawHub Client Integration Tests (with mocked HTTP)
# ---------------------------------------------------------------------------


class TestClawHubClientSecurity:
    """Test that the ClawHub client enforces security invariants."""

    def _make_client(self, mock_vt: AsyncMock) -> ClawHubClient:
        """Create a ClawHubClient with mocked HTTP transport."""
        client = ClawHubClient(
            api_key="test",
            virustotal=mock_vt,
            auto_scan=True,
        )
        # Replace the real httpx client with a mock
        client._client = AsyncMock()
        return client

    def _make_skill_resp(self, data: dict) -> MagicMock:
        """Create a mock httpx response with proper .content bytes."""
        import json

        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = data
        resp.content = json.dumps(data).encode()
        return resp

    def _make_blocklist_resp(self, data: dict) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = data
        resp.content = b"{}"
        return resp

    async def test_install_blocks_on_vt_detection(self, mock_vt: AsyncMock) -> None:
        """Installation must be refused when VT detects malware."""
        mock_vt.scan_url.return_value = ScanResult(
            resource_id="https://pkg.clawhub.ai/evil",
            positives=3,
            total=70,
            is_safe=False,
        )

        client = self._make_client(mock_vt)

        skill_resp = self._make_skill_resp(
            {
                "id": "evil-tool",
                "name": "Evil Tool",
                "package_url": "https://pkg.clawhub.ai/evil",
            }
        )
        blocklist_resp = self._make_blocklist_resp({"blocked": False})
        client._client.get = AsyncMock(side_effect=[skill_resp, blocklist_resp])

        result = await client.install_skill("evil-tool")
        assert "BLOCKED" in result
        assert "VirusTotal" in result

        # The install POST should never be called
        client._client.post.assert_not_called()

    async def test_install_blocks_on_blocklist(self, mock_vt: AsyncMock) -> None:
        """Installation must be refused when skill is on blocklist."""
        client = self._make_client(mock_vt)

        skill_resp = self._make_skill_resp(
            {
                "id": "havoc-tool",
                "name": "Havoc Tool",
                "package_url": "https://pkg.clawhub.ai/havoc",
            }
        )
        blocklist_resp = self._make_blocklist_resp({"blocked": True, "reason": "ClawHavoc confirmed malware"})
        client._client.get = AsyncMock(side_effect=[skill_resp, blocklist_resp])

        result = await client.install_skill("havoc-tool")
        assert "BLOCKED" in result
        assert "ClawHavoc" in result
        client._client.post.assert_not_called()

    async def test_install_scans_even_when_auto_scan_false(self, mock_vt: AsyncMock) -> None:
        """Security scan must run even when auto_scan=False (Runde-5 fix)."""
        mock_vt.scan_url.return_value = ScanResult(
            resource_id="https://pkg.clawhub.ai/evil",
            positives=5,
            total=70,
            is_safe=False,
        )

        client = ClawHubClient(
            api_key="test",
            virustotal=mock_vt,
            auto_scan=False,
        )
        client._client = AsyncMock()

        skill_resp = self._make_skill_resp(
            {
                "id": "evil-tool",
                "name": "Evil Tool",
                "package_url": "https://pkg.clawhub.ai/evil",
            }
        )
        blocklist_resp = self._make_blocklist_resp({"blocked": False})
        client._client.get = AsyncMock(side_effect=[skill_resp, blocklist_resp])

        result = await client.install_skill("evil-tool")
        assert "BLOCKED" in result
        client._client.post.assert_not_called()
