"""VirusTotal security scanning client.

Used by ClawHub to scan skills before installation, addressing the
ClawHavoc malware incident (341 malicious skills found on ClawHub).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
import structlog

logger = structlog.get_logger()

_VT_API_URL = "https://www.virustotal.com/api/v3"


@dataclass
class ScanResult:
    """VirusTotal scan result."""

    resource_id: str
    positives: int
    total: int
    is_safe: bool
    permalink: str = ""
    scan_date: str = ""
    verbose_msg: str = ""


class VirusTotalClient:
    """Client for the VirusTotal API v3.

    Provides URL and file-hash scanning for security verification.
    """

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "x-apikey": api_key,
                "Accept": "application/json",
            },
        )

    async def scan_url(self, url: str) -> ScanResult:
        """Submit a URL for scanning and retrieve the report.

        For the free API tier this performs a lookup of the URL hash.
        """
        try:
            # URL scan submission
            resp = await self._client.post(
                f"{_VT_API_URL}/urls",
                data={"url": url},
            )
            resp.raise_for_status()
            data = resp.json()
            analysis_id = data.get("data", {}).get("id", "")

            if not analysis_id:
                logger.warning("vt_no_analysis_id", url=url)
                return ScanResult(resource_id=url, positives=0, total=0, is_safe=False)

            # Get the analysis report
            return await self._get_analysis(analysis_id, resource_id=url)

        except httpx.HTTPStatusError as e:
            logger.error("vt_scan_url_error", status=e.response.status_code, url=url)
            raise
        except Exception as e:
            logger.error("vt_scan_url_error", error=str(e), url=url)
            raise

    async def scan_file_hash(self, file_hash: str) -> ScanResult:
        """Look up a file by its SHA-256 / SHA-1 / MD5 hash."""
        # Validate hash format (MD5=32, SHA1=40, SHA256=64 hex chars)
        file_hash = file_hash.strip()
        if not re.match(r"^[a-fA-F0-9]{32,64}$", file_hash):
            msg = f"Invalid file hash format: {file_hash!r}"
            raise ValueError(msg)
        try:
            resp = await self._client.get(f"{_VT_API_URL}/files/{file_hash}")
            resp.raise_for_status()
            data = resp.json()

            attrs = data.get("data", {}).get("attributes", {})
            stats = attrs.get("last_analysis_stats", {})
            malicious = stats.get("malicious", 0)
            suspicious = stats.get("suspicious", 0)
            total = sum(stats.values()) if stats else 0
            positives = malicious + suspicious

            return ScanResult(
                resource_id=file_hash,
                positives=positives,
                total=total,
                is_safe=positives == 0,
                permalink=f"https://www.virustotal.com/gui/file/{file_hash}",
                scan_date=attrs.get("last_analysis_date", ""),
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.info("vt_file_not_found", hash=file_hash)
                return ScanResult(
                    resource_id=file_hash,
                    positives=0,
                    total=0,
                    is_safe=True,
                    verbose_msg="File not found in VirusTotal database",
                )
            logger.error("vt_scan_hash_error", status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("vt_scan_hash_error", error=str(e))
            raise

    async def _get_analysis(self, analysis_id: str, resource_id: str = "") -> ScanResult:
        """Get an analysis report by ID."""
        try:
            resp = await self._client.get(f"{_VT_API_URL}/analyses/{analysis_id}")
            resp.raise_for_status()
            data = resp.json()

            attrs = data.get("data", {}).get("attributes", {})
            stats = attrs.get("stats", {})
            malicious = stats.get("malicious", 0)
            suspicious = stats.get("suspicious", 0)
            total = sum(stats.values()) if stats else 0
            positives = malicious + suspicious

            return ScanResult(
                resource_id=resource_id or analysis_id,
                positives=positives,
                total=total,
                is_safe=positives == 0,
                scan_date=attrs.get("date", ""),
            )
        except Exception as e:
            logger.error("vt_analysis_error", error=str(e), analysis_id=analysis_id)
            raise

    async def close(self) -> None:
        await self._client.aclose()
