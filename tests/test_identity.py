"""Unit tests for account-identity verification.

Pins the mask rule against the two masks observed live, and proves the
mismatch path clears the account session instead of acting on the wrong one.
"""

from __future__ import annotations

import pytest

from deepseek_account_forge import identity
from deepseek_account_forge.identity import IdentityMismatch, mask_email, session_matches


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("pvnt00003@gmail.com", "pv*****03@gmail.com"),
        ("pvnt3001@gmail.com", "pv****01@gmail.com"),
        ("abcd@x.com", "a***@x.com"),
        ("abc@x.com", "a**@x.com"),
        ("ab@x.com", "a*@x.com"),
        ("not-an-email", "not-an-email"),
    ],
)
def test_mask_email_matches_live_rule(email: str, expected: str) -> None:
    """The mask keeps first 2 + last 2 of the local part, stars the middle."""
    assert mask_email(email) == expected


class FakeLocator:
    """Locator stub returning a scripted visible label."""

    def __init__(self, text: str | None) -> None:
        """Store the label text (None means not visible)."""
        self.text = text

    @property
    def first(self) -> FakeLocator:
        """Mimic Playwright's .first."""
        return self

    def is_visible(self, timeout: int | None = None) -> bool:
        """Report visibility based on whether a label was scripted."""
        return self.text is not None

    def inner_text(self) -> str:
        """Return the scripted label."""
        return self.text or ""


class FakePage:
    """Page stub recording reloads and evaluating the clear script."""

    def __init__(self, label: str | None) -> None:
        """Store the masked label shown in the account control."""
        self.label = label
        self.reloads = 0
        self.scripts: list[str] = []

    def locator(self, selector: str) -> FakeLocator:
        """Return a locator for the account label selector."""
        return FakeLocator(self.label)

    def evaluate(self, script: str) -> None:
        """Record the storage-clear script."""
        self.scripts.append(script)

    def reload(self, wait_until: str | None = None) -> None:
        """Count reloads."""
        self.reloads += 1

    def wait_for_timeout(self, ms: int) -> None:
        """No-op wait."""


def test_session_matches_true_on_same_account() -> None:
    """The mask of the cred email equals the visible label."""
    page = FakePage("pv*****03@gmail.com")
    assert session_matches(page, "pvnt00003@gmail.com") is True


def test_session_matches_false_on_other_account() -> None:
    """A different masked label does not match."""
    page = FakePage("pv****01@gmail.com")
    assert session_matches(page, "pvnt00003@gmail.com") is False


def test_session_matches_false_when_unreadable() -> None:
    """No visible label fails closed."""
    page = FakePage(None)
    assert session_matches(page, "pvnt00003@gmail.com") is False


class FakeContext:
    """Context stub recording cleared cookies."""

    def __init__(self, names: list[str]) -> None:
        """Store the cookie names present in the context."""
        self.names = names
        self.cleared: list[tuple[str, str]] = []

    def cookies(self) -> list[dict[str, str]]:
        """Return cookie dicts for each stored name."""
        return [{"name": n, "domain": "chat.deepseek.com"} for n in self.names]

    def clear_cookies(self, name: str | None = None, domain: str | None = None) -> None:
        """Record a targeted cookie clear."""
        if name is not None and domain is not None:
            self.cleared.append((name, domain))


def test_clear_account_session_only_touches_session_cookie() -> None:
    """Only ds_session_id is cleared; the cache cookie survives."""
    context = FakeContext(["ds_session_id", ".thumbcache_abc", "smidV2"])
    page = FakePage("pv*****03@gmail.com")
    identity.clear_account_session(context, page)
    assert context.cleared == [("ds_session_id", "chat.deepseek.com")]
    assert any("userToken" in s for s in page.scripts)


def test_ensure_matching_session_passes_on_match(monkeypatch) -> None:
    """A matching account proceeds without clearing or reloading."""
    monkeypatch.setattr(identity, "detect_state", lambda page: identity.SessionState.LOGGED_IN)
    context = FakeContext(["ds_session_id"])
    page = FakePage("pv*****03@gmail.com")
    identity.ensure_matching_session(context, page, "pvnt00003@gmail.com")
    assert context.cleared == []
    assert page.reloads == 0


def test_ensure_matching_session_clears_on_mismatch(monkeypatch) -> None:
    """A different account is cleared and the page reloaded."""
    monkeypatch.setattr(identity, "detect_state", lambda page: identity.SessionState.LOGGED_IN)
    context = FakeContext(["ds_session_id"])
    page = FakePage("pv****01@gmail.com")
    identity.ensure_matching_session(context, page, "pvnt00003@gmail.com")
    assert context.cleared == [("ds_session_id", "chat.deepseek.com")]
    assert page.reloads == 1


def test_ensure_matching_session_fails_closed_when_unreadable(monkeypatch) -> None:
    """A logged-in page with no readable label raises instead of acting."""
    monkeypatch.setattr(identity, "detect_state", lambda page: identity.SessionState.LOGGED_IN)
    context = FakeContext(["ds_session_id"])
    page = FakePage(None)
    with pytest.raises(IdentityMismatch):
        identity.ensure_matching_session(context, page, "pvnt00003@gmail.com")
    assert context.cleared == []
