"""Fetch the DeepSeek signup OTP from a Gmail inbox over IMAP.

SMTP sends mail; reading an inbox needs IMAP. This module connects to
``imap.gmail.com`` over SSL, finds the newest DeepSeek message, and pulls a
six-digit code out of it. It replaces the manual terminal prompt so signup can
run unattended.

Gmail requires an App Password (not the account password) when 2FA is on.
"""

from __future__ import annotations

import contextlib
import email
import imaplib
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import Message
from email.utils import parsedate_to_datetime

DEFAULT_HOST = "imap.gmail.com"
DEFAULT_PORT = 993
DEFAULT_SENDER_FILTER = "deepseek"
DEFAULT_TIMEOUT_S = 120.0
DEFAULT_POLL_S = 5.0
OTP_RE = re.compile(r"\b(\d{6})\b")


class OtpMailError(RuntimeError):
    """Raised when the inbox cannot be reached or no OTP is found in time."""


@dataclass(frozen=True)
class MailConfig:
    """IMAP connection settings for the OTP inbox."""

    email: str
    app_password: str
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    sender_filter: str = DEFAULT_SENDER_FILTER


def _connect(config: MailConfig) -> imaplib.IMAP4_SSL:
    """Open an authenticated IMAP SSL connection."""
    try:
        client = imaplib.IMAP4_SSL(config.host, config.port)
        client.login(config.email, config.app_password)
    except (imaplib.IMAP4.error, OSError) as exc:
        raise OtpMailError(f"IMAP login failed for {config.email}: {exc}") from exc
    return client


def _body_text(message: Message) -> str:
    """Flatten a message's text parts into one string."""
    if message.is_multipart():
        chunks = []
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    chunks.append(payload.decode(part.get_content_charset() or "utf-8", "ignore"))
        return "\n".join(chunks)
    payload = message.get_payload(decode=True)
    if payload:
        return payload.decode(message.get_content_charset() or "utf-8", "ignore")
    return ""


def _message_date(message: Message) -> datetime | None:
    """Return the message's Date header as an aware UTC datetime, or None."""
    raw = message.get("Date")
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(str(raw))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _latest_deepseek_uid(
    client: imaplib.IMAP4_SSL,
    sender_filter: str,
    since: datetime | None = None,
) -> str | None:
    """Return the UID of the newest message from the sender, or None.

    When ``since`` is given, messages dated before it are skipped. This is what
    stops a stale code from an earlier signup attempt being reused.
    """
    status, _ = client.select("INBOX")
    if status != "OK":
        raise OtpMailError("could not open INBOX")
    status, data = client.uid("search", None, "ALL")
    if status != "OK" or not data or not data[0]:
        return None
    uids = data[0].split()
    for uid in reversed(uids):
        status, msg_data = client.uid("fetch", uid, "(RFC822)")
        if status != "OK" or not msg_data:
            continue
        raw = next((part[1] for part in msg_data if isinstance(part, tuple)), None)
        if not raw:
            continue
        message = email.message_from_bytes(raw)
        sender = str(message.get("From", "")).lower()
        if sender_filter.lower() not in sender:
            continue
        if since is not None:
            sent = _message_date(message)
            if sent is None or sent < since:
                continue
        return uid.decode() if isinstance(uid, bytes) else str(uid)
    return None


def fetch_latest_otp(
    config: MailConfig,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    since: datetime | None = None,
) -> str:
    """Poll the inbox until a DeepSeek OTP appears, then return it.

    Only messages dated at or after ``since`` are considered, so a code from an
    earlier attempt is never reused. Raises OtpMailError on connection failure
    or when no fresh code arrives within the timeout.
    """
    deadline = time.monotonic() + timeout_s
    client = _connect(config)
    try:
        while time.monotonic() < deadline:
            uid = _latest_deepseek_uid(client, config.sender_filter, since)
            if uid:
                status, msg_data = client.uid("fetch", uid, "(RFC822)")
                if status == "OK" and msg_data:
                    raw = next((p[1] for p in msg_data if isinstance(p, tuple)), None)
                    if raw:
                        match = OTP_RE.search(_body_text(email.message_from_bytes(raw)))
                        if match:
                            return match.group(1)
            # Sleep no longer than the remaining budget so short timeouts exit fast.
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(DEFAULT_POLL_S, remaining))
    finally:
        # Best-effort close: a failed logout must not mask the real outcome.
        with contextlib.suppress(Exception):
            client.logout()
    raise OtpMailError(f"no OTP found within {timeout_s:.0f}s")
