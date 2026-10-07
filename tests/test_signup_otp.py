"""Unit tests for the OTP resolution order in signup.prompt_for_otp."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from deepseek_account_forge import signup
from deepseek_account_forge.credentials import Credentials
from deepseek_account_forge.otp_mail import OtpMailError


def _creds(imap: bool) -> Credentials:
    """Build credentials with or without IMAP fields."""
    return Credentials(
        email="a@b.com",
        password="pw",
        imap_email="inbox@gmail.com" if imap else "",
        imap_password="app-pw" if imap else "",
    )


def test_override_wins_over_imap(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit --otp value is used and IMAP is never contacted."""
    monkeypatch.setattr(
        signup, "fetch_latest_otp", lambda *_a, **_k: pytest.fail("IMAP should not be hit")
    )
    assert signup.prompt_for_otp("999999", _creds(imap=True)) == "999999"


def test_env_otp_used_when_no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """The OTP env var is honored before IMAP."""
    monkeypatch.setenv("OTP", "123123")
    monkeypatch.setattr(
        signup, "fetch_latest_otp", lambda *_a, **_k: pytest.fail("IMAP should not be hit")
    )
    assert signup.prompt_for_otp(None, _creds(imap=True)) == "123123"


def test_imap_used_when_no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """With IMAP creds and no override, the code is fetched from mail."""
    monkeypatch.delenv("OTP", raising=False)
    monkeypatch.setattr(signup, "fetch_latest_otp", lambda *_a, **_k: "555555")
    assert signup.prompt_for_otp(None, _creds(imap=True)) == "555555"


def test_imap_failure_falls_back_to_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed IMAP fetch drops to the terminal prompt instead of aborting."""
    monkeypatch.delenv("OTP", raising=False)

    def boom(*_a: object, **_k: object) -> str:
        raise OtpMailError("no OTP found")

    monkeypatch.setattr(signup, "fetch_latest_otp", boom)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "777777")
    assert signup.prompt_for_otp(None, _creds(imap=True)) == "777777"


def test_no_imap_creds_skips_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without IMAP creds the flow goes straight to the prompt."""
    monkeypatch.delenv("OTP", raising=False)
    monkeypatch.setattr(
        signup, "fetch_latest_otp", lambda *_a, **_k: pytest.fail("IMAP should not be hit")
    )
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "246810")
    assert signup.prompt_for_otp(None, _creds(imap=False)) == "246810"


def test_since_cutoff_is_passed_to_imap(monkeypatch: pytest.MonkeyPatch) -> None:
    """The code-request timestamp reaches fetch_latest_otp as `since`."""
    monkeypatch.delenv("OTP", raising=False)
    cutoff = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    captured: dict[str, object] = {}

    def spy(*_a: object, **kwargs: object) -> str:
        captured.update(kwargs)
        return "123456"

    monkeypatch.setattr(signup, "fetch_latest_otp", spy)
    assert signup.prompt_for_otp(None, _creds(imap=True), since=cutoff) == "123456"
    assert captured.get("since") == cutoff
