"""ClawHub skill marketplace tools for the agent.

Security: The install tool enforces mandatory VirusTotal scanning
before any skill installation (ClawHavoc mitigation).
"""

from typing import Any

import structlog

from openclaw.integrations.clawhub import ClawHubClient
from openclaw.tools.base import BaseTool

logger = structlog.get_logger()


class ClawHubSearchTool(BaseTool):
    """Search the ClawHub skill marketplace."""

    name = "clawhub_search"
    description = (
        "Search the ClawHub marketplace for OpenClaw skills. "
        "Returns skill names, descriptions, ratings, and verification status."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query for skills.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results (1-20, default 10).",
            },
        },
        "required": ["query"],
    }

    def __init__(self, client: ClawHubClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        query = kwargs["query"]
        limit = min(kwargs.get("limit", 10), 20)

        try:
            response = await self._client.search(query=query, limit=limit)
        except Exception as e:
            return f"ClawHub search failed: {e}"

        if not response.skills:
            return f"No skills found for '{query}'."

        parts = [f"ClawHub results for '{query}' ({response.total} total):\n"]
        for skill in response.skills:
            verified = " [verified]" if skill.verified else ""
            rating = f" ({skill.rating:.1f}*)" if skill.rating else ""
            downloads = f" [{skill.downloads} downloads]" if skill.downloads else ""
            parts.append(f"  - {skill.name} (id: {skill.id}){verified}{rating}{downloads}\n    {skill.description}")

        return "\n".join(parts)


class ClawHubInstallTool(BaseTool):
    """Install a skill from ClawHub (with mandatory security scan)."""

    name = "clawhub_install"
    description = (
        "Install a skill from the ClawHub marketplace. "
        "IMPORTANT: Every installation includes a mandatory VirusTotal security scan. "
        "Installation is automatically refused if malware is detected or the skill "
        "is on the ClawHavoc blocklist."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": "The ID of the skill to install (from clawhub_search results).",
            },
        },
        "required": ["skill_id"],
    }

    def __init__(self, client: ClawHubClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        skill_id = kwargs["skill_id"]

        if not skill_id.strip():
            return "Error: Skill ID cannot be empty."

        try:
            result = await self._client.install_skill(skill_id=skill_id)
        except Exception as e:
            return f"Installation failed: {e}"

        return result


class ClawHubSecurityTool(BaseTool):
    """Get a security report for a ClawHub skill."""

    name = "clawhub_security"
    description = (
        "Get a security report for a ClawHub skill before installing it. "
        "Checks VirusTotal scan results and the ClawHavoc blocklist. "
        "Use this to verify a skill is safe before installation."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": "The ID of the skill to check.",
            },
        },
        "required": ["skill_id"],
    }

    def __init__(self, client: ClawHubClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        skill_id = kwargs["skill_id"]

        if not skill_id.strip():
            return "Error: Skill ID cannot be empty."

        try:
            report = await self._client.get_security_report(skill_id=skill_id)
        except Exception as e:
            return f"Security check failed: {e}"

        parts = [f"Security Report for '{report.skill_name}' ({report.skill_id}):\n"]

        # Blocklist status
        if report.on_blocklist:
            parts.append(f"  BLOCKLIST: YES - {report.blocklist_reason}")
        else:
            parts.append("  Blocklist: Clean")

        # VirusTotal status
        if report.vt_scan:
            vt_status = "CLEAN" if report.vt_scan.is_safe else "FLAGGED"
            parts.append(f"  VirusTotal: {vt_status} ({report.vt_scan.positives}/{report.vt_scan.total} detections)")
            if report.vt_scan.permalink:
                parts.append(f"  Report: {report.vt_scan.permalink}")
        else:
            parts.append("  VirusTotal: Not scanned (no VT API key or no package URL)")

        # Overall verdict
        verdict = "SAFE" if report.safe_to_install else "UNSAFE - DO NOT INSTALL"
        parts.append(f"\n  Verdict: {verdict}")

        return "\n".join(parts)
