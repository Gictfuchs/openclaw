"""Fochs integration clients.

Shared utilities for all integration modules.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import quote, urlparse

# Safe ID pattern: alphanumeric, hyphens, underscores, dots, colons
_SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-.:]+$")

# Max length for IDs used in URL paths
_MAX_ID_LENGTH = 256


def validate_id(value: str, field_name: str = "id") -> str:
    """Validate and sanitize an ID before use in URL paths.

    Prevents path traversal and URL injection attacks from LLM-generated IDs.

    Args:
        value: The ID value to validate.
        field_name: Name of the field (for error messages).

    Returns:
        The validated ID (stripped of whitespace).

    Raises:
        ValueError: If the ID is empty, too long, or contains unsafe characters.
    """
    value = value.strip()

    if not value:
        msg = f"{field_name} cannot be empty"
        raise ValueError(msg)

    if len(value) > _MAX_ID_LENGTH:
        msg = f"{field_name} exceeds maximum length of {_MAX_ID_LENGTH}"
        raise ValueError(msg)

    if not _SAFE_ID_PATTERN.match(value):
        msg = f"{field_name} contains invalid characters (allowed: alphanumeric, hyphens, underscores, dots, colons)"
        raise ValueError(msg)

    return value


def safe_url_path(value: str) -> str:
    """URL-encode a value for safe use in URL path segments.

    Defense-in-depth: even after validate_id(), URL-encode the value.
    """
    return quote(value, safe="")


# -----------------------------------------------------------------------
# URL validation (SSRF prevention)
# -----------------------------------------------------------------------

# Domains that must never be fetched
_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",  # noqa: S104
        "169.254.169.254",  # AWS IMDS
        "metadata.google.internal",  # GCP metadata
        "[::1]",
    }
)


def _is_private_ip(addr: str) -> bool:
    """Check if an IP address string is private/reserved using stdlib ipaddress.

    Handles IPv4, IPv6, octal (0177.0.0.1), hex (0x7f.0.0.1), and
    decimal-integer (2130706433) encodings because ``ipaddress.ip_address``
    normalises them all.
    """
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local or ip.is_multicast or ip.is_unspecified


def validate_url(url: str) -> str | None:
    """Validate a URL for safe external fetching (SSRF prevention).

    Returns an error string if the URL is unsafe, or None if safe.

    Defence layers:
    1. Scheme check (http/https only).
    2. Hostname blocklist (known metadata endpoints).
    3. Parsed-hostname IP check (catches octal, hex, decimal IPs).
    4. DNS resolution check — resolves the hostname and verifies that
       *every* resulting IP is public.  This catches DNS-rebinding
       attacks where a hostname resolves to an internal IP.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL"

    if parsed.scheme not in ("http", "https"):
        return f"Unsupported scheme: {parsed.scheme}. Only http/https allowed."

    hostname = (parsed.hostname or "").lower()

    if not hostname:
        return "Missing hostname"

    # Strip IPv6 brackets for consistent checking
    bare_host = hostname.strip("[]")

    if bare_host in _BLOCKED_HOSTS or hostname in _BLOCKED_HOSTS:
        return f"Blocked host: {hostname}"

    # --- Layer 3: detect encoded/numeric IP addresses ---
    if _is_private_ip(bare_host):
        return "Private/internal IP addresses are not allowed."

    # --- Layer 4: DNS resolution check (anti DNS-rebinding) ---
    try:
        infos = socket.getaddrinfo(bare_host, None, proto=socket.IPPROTO_TCP)
        for _family, _type, _proto, _canonname, sockaddr in infos:
            resolved_ip = sockaddr[0]
            if _is_private_ip(resolved_ip):
                return f"Hostname resolves to private IP ({resolved_ip}). Not allowed."
    except socket.gaierror:
        # Cannot resolve hostname — allow; the HTTP client will fail later
        pass

    return None


# -----------------------------------------------------------------------
# Response size safety
# -----------------------------------------------------------------------

# Default maximum response size: 5 MB
_DEFAULT_MAX_RESPONSE_BYTES = 5 * 1024 * 1024


def check_response_size(
    response_content: bytes,
    max_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
    context: str = "",
) -> None:
    """Raise ValueError if a response exceeds the size limit.

    Call this after receiving an HTTP response to prevent memory exhaustion
    from unexpectedly large API responses.

    Args:
        response_content: The raw response content bytes.
        max_bytes: Maximum allowed size in bytes.
        context: Description of the request (for error messages).

    Raises:
        ValueError: If the response exceeds max_bytes.
    """
    size = len(response_content)
    if size > max_bytes:
        ctx = f" ({context})" if context else ""
        msg = f"Response too large{ctx}: {size} bytes (max {max_bytes})"
        raise ValueError(msg)
