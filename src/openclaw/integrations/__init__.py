"""Fochs integration clients.

Shared utilities for all integration modules.
"""

from __future__ import annotations

import re
from urllib.parse import quote

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
