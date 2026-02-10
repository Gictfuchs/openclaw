"""E-Mail client for IMAP reading and SMTP sending."""

from __future__ import annotations

import email
import email.utils
from dataclasses import dataclass
from email.mime.text import MIMEText
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class EmailMessage:
    """Parsed email message."""

    subject: str
    sender: str
    to: str
    date: str
    body: str
    uid: str = ""
    is_read: bool = False


@dataclass
class EmailConfig:
    """Email connection configuration."""

    address: str
    password: str
    imap_host: str
    smtp_host: str
    imap_port: int = 993
    smtp_port: int = 587


class EmailClient:
    """Async email client for reading (IMAP) and sending (SMTP)."""

    def __init__(self, config: EmailConfig) -> None:
        self._config = config

    async def fetch_recent(self, folder: str = "INBOX", limit: int = 10) -> list[EmailMessage]:
        """Fetch recent emails from IMAP."""
        import aioimaplib

        try:
            client = aioimaplib.IMAP4_SSL(host=self._config.imap_host, port=self._config.imap_port)
            await client.wait_hello_from_server()
            await client.login(self._config.address, self._config.password)
            await client.select(folder)

            # Search for recent messages
            _, data = await client.search("ALL")
            message_ids = data[0].split() if data[0] else []

            # Get the most recent ones
            recent_ids = message_ids[-limit:] if len(message_ids) > limit else message_ids
            recent_ids.reverse()  # Newest first

            messages = []
            for msg_id in recent_ids:
                _, msg_data = await client.fetch(msg_id.decode(), "(RFC822 FLAGS)")
                if not msg_data or len(msg_data) < 2:
                    continue

                # Parse the raw email
                raw = msg_data[1]
                if isinstance(raw, tuple):
                    raw = raw[1]
                if isinstance(raw, bytes):
                    parsed = email.message_from_bytes(raw)
                else:
                    continue

                body = self._extract_body(parsed)
                is_read = b"\\Seen" in (msg_data[0] if isinstance(msg_data[0], bytes) else b"")

                messages.append(
                    EmailMessage(
                        subject=self._decode_header(parsed.get("Subject", "")),
                        sender=self._decode_header(parsed.get("From", "")),
                        to=self._decode_header(parsed.get("To", "")),
                        date=parsed.get("Date", ""),
                        body=body[:5000],  # Limit body size
                        uid=msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
                        is_read=is_read,
                    )
                )

            await client.logout()
            return messages

        except Exception as e:
            logger.error("email_fetch_error", error=str(e))
            raise

    async def send(self, to: str, subject: str, body: str) -> None:
        """Send an email via SMTP."""
        import aiosmtplib

        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = self._config.address
        msg["To"] = to
        msg["Subject"] = subject

        try:
            await aiosmtplib.send(
                msg,
                hostname=self._config.smtp_host,
                port=self._config.smtp_port,
                username=self._config.address,
                password=self._config.password,
                start_tls=True,
            )
            logger.info("email_sent", to=to, subject=subject)
        except Exception as e:
            logger.error("email_send_error", to=to, error=str(e))
            raise

    @staticmethod
    def _extract_body(msg: Any) -> str:
        """Extract plain text body from email message."""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        return payload.decode(charset, errors="replace")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        return ""

    @staticmethod
    def _decode_header(value: str) -> str:
        """Decode MIME-encoded header value."""
        try:
            decoded_parts = email.header.decode_header(value)
            parts = []
            for part, charset in decoded_parts:
                if isinstance(part, bytes):
                    parts.append(part.decode(charset or "utf-8", errors="replace"))
                else:
                    parts.append(part)
            return " ".join(parts)
        except Exception:
            return value
