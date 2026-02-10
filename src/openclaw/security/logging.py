"""Secure logging setup - masks secrets automatically."""

import re

import structlog

# Patterns that indicate sensitive values in log entries
_SENSITIVE_KEYS = re.compile(
    r"(api_key|api[-_]?secret|token|password|secret|credential|auth)",
    re.IGNORECASE,
)


def _mask_sensitive_values(
    logger: object, method_name: str, event_dict: dict,
) -> dict:
    """Structlog processor that masks values for sensitive-looking keys."""
    for key in list(event_dict.keys()):
        if _SENSITIVE_KEYS.search(key):
            val = event_dict[key]
            if isinstance(val, str) and len(val) > 8:
                event_dict[key] = val[:4] + "***" + val[-4:]
            elif isinstance(val, str):
                event_dict[key] = "***"
    return event_dict


def setup_secure_logging() -> None:
    """Configure structured logging with automatic secret masking."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _mask_sensitive_values,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO level
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
