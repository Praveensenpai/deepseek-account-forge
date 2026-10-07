"""Unit tests for IMAP OTP retrieval.

No network: imaplib is stubbed with a scripted client so the search, fetch, and
regex logic is exercised offline.
"""

from __future__ import annotations

import email
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

import pytest

from deepseek_account_forge import otp_mail
from deepseek_account_forge.otp_mail import MailConfig, OtpMailError, fetch_latest_otp

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _message(sender: str, body: str, when: datetime | None = None) -> bytes:
    """Build a raw email body as bytes, dated `when` (default: a fixed time)."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["Subject"] = "Your code"
    msg["Date"] = (when or NOW).strftime("%a, %d %b %Y %H:%M:%S %z")
    msg.set_content(body)
    return msg.as_bytes()


class FakeIMAP:
    """Scripted IMAP client returning a fixed message list."""

    def __init__(self, messages: list[bytes], login_error: Exception | None = None) -> None:
        """Store raw messages (newest last) and an optional login failure."""
        self._messages = messages
        self._login_error = login_error
        self.logged_out = False

    def login(self, _user: str, _password: str) -> tuple[str, list[bytes]]:
        """Raise if configured, else succeed."""
        if self._login_error:
            raise self._login_error
        return "OK", [b"logged in"]

    def select(self, _mailbox: str) -> tuple[str, list[bytes]]:
        """Pretend the inbox opened."""
        return "OK", [str(len(self._messages)).encode()]

    def uid(self, command: str, *args: object) -> tuple[str, list[object]]:
        """Handle SEARCH, FETCH, and logout-like commands."""
        if command == "search":
            ids = [str(i).encode() for i in range(1, len(self._messages) + 1)]
            return "OK", [b" ".join(ids)]
        if command == "fetch":
            uid = args[0]
            index = int(uid) - 1 if isinstance(uid, (int, bytes, str)) else 0
            if 0 <= index < len(self._messages):
                return "OK", [(b"1 (RFC822 {..})", self._messages[index])]
            return "OK", [None]
        return "OK", [b""]

    def logout(self) -> tuple[str, list[bytes]]:
        """Record that the connection was closed."""
        self.logged_out = True
        return "BYE", [b""]


def _install(monkeypatch: pytest.MonkeyPatch, client: FakeIMAP) -> None:
    """Make otp_mail use the fake client and skip real polling sleeps."""
    monkeypatch.setattr(otp_mail.imaplib, "IMAP4_SSL", lambda *_a, **_k: client)
    monkeypatch.setattr(otp_mail.time, "sleep", lambda _s: None)


def test_extracts_six_digit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """A DeepSeek email carrying a 6-digit code yields that code."""
    raw = _message("no-reply@deepseek.com", "Your verification code is 428139. It expires soon.")
    _install(monkeypatch, FakeIMAP([raw]))
    code = fetch_latest_otp(MailConfig(email="a@gmail.com", app_password="x"), timeout_s=1)
    assert code == "428139"


def test_ignores_non_deepseek_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mail from another sender is skipped; the OTP is never taken from it."""
    raw = _message("spam@example.com", "your code is 111111")
    _install(monkeypatch, FakeIMAP([raw]))
    with pytest.raises(OtpMailError, match="no OTP found"):
        fetch_latest_otp(MailConfig(email="a@gmail.com", app_password="x"), timeout_s=0.1)


def test_newest_matching_message_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """When two DeepSeek mails exist, the newest one's code is returned."""
    old = _message("no-reply@deepseek.com", "code 111111")
    new = _message("no-reply@deepseek.com", "code 222222")
    _install(monkeypatch, FakeIMAP([old, new]))
    code = fetch_latest_otp(MailConfig(email="a@gmail.com", app_password="x"), timeout_s=1)
    assert code == "222222"


def test_login_failure_raises_otpmailerror(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bad App Password surfaces as OtpMailError, not a raw imaplib error."""
    client = FakeIMAP([], login_error=otp_mail.imaplib.IMAP4.error("auth failed"))
    _install(monkeypatch, client)
    with pytest.raises(OtpMailError, match="IMAP login failed"):
        fetch_latest_otp(MailConfig(email="a@gmail.com", app_password="bad"), timeout_s=1)


def test_connection_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The client is logged out even when no code is found."""
    client = FakeIMAP([_message("spam@example.com", "hi")])
    _install(monkeypatch, client)
    with pytest.raises(OtpMailError):
        fetch_latest_otp(MailConfig(email="a@gmail.com", app_password="x"), timeout_s=0.1)
    assert client.logged_out is True


def test_body_text_handles_plain_message() -> None:
    """_body_text returns the decoded body for a non-multipart message."""
    msg = email.message_from_bytes(_message("x@y.com", "hello 123456"))
    assert "123456" in otp_mail._body_text(msg)


def test_config_defaults() -> None:
    """MailConfig defaults target Gmail IMAP and a DeepSeek sender filter."""
    cfg = MailConfig(email="a@gmail.com", app_password="x")
    assert cfg.host == "imap.gmail.com"
    assert cfg.port == 993
    assert cfg.sender_filter == "deepseek"


def test_stale_code_before_cutoff_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mail dated before `since` is skipped so an old code cannot be reused."""
    stale = _message("no-reply@deepseek.com", "code 111111", when=NOW - timedelta(minutes=5))
    _install(monkeypatch, FakeIMAP([stale]))
    with pytest.raises(OtpMailError, match="no OTP found"):
        fetch_latest_otp(
            MailConfig(email="a@gmail.com", app_password="x"),
            timeout_s=0.1,
            since=NOW,
        )


def test_fresh_code_after_cutoff_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mail dated after `since` is accepted."""
    fresh = _message("no-reply@deepseek.com", "code 333333", when=NOW + timedelta(seconds=5))
    _install(monkeypatch, FakeIMAP([fresh]))
    code = fetch_latest_otp(
        MailConfig(email="a@gmail.com", app_password="x"),
        timeout_s=1,
        since=NOW,
    )
    assert code == "333333"


def test_stale_ignored_and_fresh_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """With both present, the post-cutoff code wins even though the stale one is older."""
    stale = _message("no-reply@deepseek.com", "code 111111", when=NOW - timedelta(minutes=5))
    fresh = _message("no-reply@deepseek.com", "code 444444", when=NOW + timedelta(seconds=5))
    _install(monkeypatch, FakeIMAP([stale, fresh]))
    code = fetch_latest_otp(
        MailConfig(email="a@gmail.com", app_password="x"),
        timeout_s=1,
        since=NOW,
    )
    assert code == "444444"


def test_message_without_date_is_ignored_when_since_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """A message with no Date header cannot satisfy a cutoff and is skipped."""
    msg = EmailMessage()
    msg["From"] = "no-reply@deepseek.com"
    msg.set_content("code 555555")
    _install(monkeypatch, FakeIMAP([msg.as_bytes()]))
    with pytest.raises(OtpMailError, match="no OTP found"):
        fetch_latest_otp(
            MailConfig(email="a@gmail.com", app_password="x"),
            timeout_s=0.1,
            since=NOW,
        )
