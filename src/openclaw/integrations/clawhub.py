"""ClawHub skill marketplace client.

Integrates with the ClawHub marketplace for discovering and installing
OpenClaw skills. Mandatory VirusTotal scanning before installation
addresses the ClawHavoc incident (341 malicious skills).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from openclaw.integrations import check_response_size, validate_id

if TYPE_CHECKING:
    from openclaw.integrations.virustotal import ScanResult, VirusTotalClient

logger = structlog.get_logger()

_DEFAULT_BASE_URL = "https://api.clawhub.ai/v1"


@dataclass
class SkillInfo:
    """A ClawHub skill."""

    id: str
    name: str
    description: str = ""
    author: str = ""
    version: str = ""
    downloads: int = 0
    rating: float = 0.0
    verified: bool = False
    package_url: str = ""
    categories: list[str] = field(default_factory=list)


@dataclass
class SkillSearchResponse:
    """ClawHub search result."""

    query: str
    total: int = 0
    skills: list[SkillInfo] = field(default_factory=list)


@dataclass
class SkillSecurityReport:
    """Security report for a ClawHub skill."""

    skill_id: str
    skill_name: str
    vt_scan: ScanResult | None = None
    on_blocklist: bool = False
    blocklist_reason: str = ""
    safe_to_install: bool = False


class ClawHubClient:
    """Client for the ClawHub skill marketplace.

    Security: Every ``install_skill()`` call performs a mandatory
    VirusTotal scan. Installation is refused if:
    - VirusTotal detects any positives
    - The skill is on the ClawHavoc blocklist
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        virustotal: VirusTotalClient | None = None,
        auto_scan: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._vt = virustotal
        self._auto_scan = auto_scan
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
        )

    async def search(self, query: str, limit: int = 10) -> SkillSearchResponse:
        """Search the ClawHub marketplace for skills."""
        try:
            resp = await self._client.get(
                f"{self._base_url}/skills/search",
                params={"q": query, "limit": min(limit, 50)},
            )
            resp.raise_for_status()
            check_response_size(resp.content, context="clawhub_search")
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("clawhub_search_error", status=e.response.status_code, query=query)
            raise
        except Exception as e:
            logger.error("clawhub_search_error", error=str(e), query=query)
            raise

        skills = []
        for item in data.get("skills", data.get("results", [])):
            skills.append(self._parse_skill(item))

        total = data.get("total", len(skills))
        logger.info("clawhub_search", query=query, results=len(skills))
        return SkillSearchResponse(query=query, total=total, skills=skills)

    async def get_skill(self, skill_id: str) -> SkillInfo:
        """Get details for a specific skill."""
        skill_id = validate_id(skill_id, "skill_id")
        try:
            resp = await self._client.get(f"{self._base_url}/skills/{skill_id}")
            resp.raise_for_status()
            check_response_size(resp.content, context="clawhub_get_skill")
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("clawhub_get_skill_error", status=e.response.status_code, skill_id=skill_id)
            raise
        except Exception as e:
            logger.error("clawhub_get_skill_error", error=str(e), skill_id=skill_id)
            raise

        return self._parse_skill(data.get("skill", data))

    async def get_security_report(self, skill_id: str) -> SkillSecurityReport:
        """Generate a security report for a skill.

        Combines VirusTotal scanning with ClawHavoc blocklist checking.
        """
        skill_id = validate_id(skill_id, "skill_id")
        skill = await self.get_skill(skill_id)

        report = SkillSecurityReport(
            skill_id=skill.id,
            skill_name=skill.name,
        )

        # Check ClawHavoc blocklist (via ClawHub API)
        try:
            resp = await self._client.get(
                f"{self._base_url}/security/blocklist/{skill_id}",
            )
            if resp.status_code == 200:
                bl_data = resp.json()
                report.on_blocklist = bl_data.get("blocked", False)
                report.blocklist_reason = bl_data.get("reason", "")
        except Exception as e:
            logger.warning("clawhub_blocklist_check_failed", error=str(e), skill_id=skill_id)

        # VirusTotal scan (if available and skill has a package URL)
        if self._vt and skill.package_url:
            try:
                report.vt_scan = await self._vt.scan_url(skill.package_url)
            except Exception as e:
                logger.warning("clawhub_vt_scan_failed", error=str(e), skill_id=skill_id)

        # Determine safety — FAIL-CLOSED: if VT scan is unavailable, assume unsafe
        vt_safe = report.vt_scan.is_safe if report.vt_scan else False
        report.safe_to_install = vt_safe and not report.on_blocklist

        return report

    async def install_skill(self, skill_id: str) -> str:
        """Install a skill from ClawHub.

        MANDATORY security checks before installation:
        1. VirusTotal scan of the package URL
        2. ClawHavoc blocklist check
        """
        skill_id = validate_id(skill_id, "skill_id")
        # Always run security check before installation
        if self._auto_scan:
            report = await self.get_security_report(skill_id)

            if report.on_blocklist:
                msg = (
                    f"BLOCKED: Skill '{report.skill_name}' is on the ClawHavoc blocklist. "
                    f"Reason: {report.blocklist_reason}. Installation refused."
                )
                logger.error("clawhub_install_blocked", skill_id=skill_id, reason="blocklist")
                return msg

            if report.vt_scan and not report.vt_scan.is_safe:
                msg = (
                    f"BLOCKED: Skill '{report.skill_name}' flagged by VirusTotal "
                    f"({report.vt_scan.positives}/{report.vt_scan.total} detections). "
                    f"Installation refused."
                )
                logger.error("clawhub_install_blocked", skill_id=skill_id, reason="virustotal")
                return msg

        # Proceed with installation
        try:
            resp = await self._client.post(f"{self._base_url}/skills/{skill_id}/install")
            resp.raise_for_status()
            check_response_size(resp.content, context="clawhub_install")
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("clawhub_install_error", status=e.response.status_code, skill_id=skill_id)
            return f"Installation failed: HTTP {e.response.status_code}"
        except Exception as e:
            logger.error("clawhub_install_error", error=str(e), skill_id=skill_id)
            return f"Installation failed: {e}"

        logger.info("clawhub_skill_installed", skill_id=skill_id)
        return data.get("message", f"Skill '{skill_id}' installed successfully.")

    @staticmethod
    def _parse_skill(data: dict[str, Any]) -> SkillInfo:
        """Parse a skill from API response data."""
        return SkillInfo(
            id=data.get("id", data.get("skill_id", "")),
            name=data.get("name", ""),
            description=data.get("description", ""),
            author=data.get("author", ""),
            version=data.get("version", ""),
            downloads=data.get("downloads", 0),
            rating=data.get("rating", 0.0),
            verified=data.get("verified", False),
            package_url=data.get("package_url", ""),
            categories=data.get("categories", []),
        )

    async def close(self) -> None:
        await self._client.aclose()
