"""Unit tests for post-submit outcome classification.

These cover the exact logic that failed silently earlier in the project: a
submit that never authenticated must never be reported as success.
"""

from __future__ import annotations

import pytest

from deepseek_account_forge import auth_wait
from deepseek_account_forge.auth_wait import (
    AuthError,
    AuthOutcome,
    Outcome,
    require_success,
    wait_for_outcome,
)
from deepseek_account_forge.state import SessionState


class ScriptedPage:
    """Page stub whose visible selectors and state can be scripted per poll."""

    def __init__(
        self,
        states: list[SessionState] | SessionState,
        visible: set[str] | None = None,
        error_text: str | None = None,
    ) -> None:
        """Store the sequence of states and visible selectors."""
        self._states = states if isinstance(states, list) else [states]
        self._visible = visible or set()
        self._error_text = error_text
        self._index = 0

    @property
    def _current(self) -> SessionState:
        """The state for the current poll, repeating the last value."""
        return self._states[min(self._index, len(self._states) - 1)]

    def wait_for_timeout(self, _ms: int) -> None:
        """Advance the poll counter without sleeping."""
        self._index += 1


@pytest.fixture(autouse=True)
def _stub_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route detect_state/_visible/_error_text through the scripted page."""

    def fake_detect(page: ScriptedPage) -> SessionState:
        return page._current

    def fake_visible(page: ScriptedPage, selector: str) -> bool:
        return selector in page._visible

    def fake_error(page: ScriptedPage) -> str | None:
        return page._error_text

    monkeypatch.setattr(auth_wait, "detect_state", fake_detect)
    monkeypatch.setattr(auth_wait, "_visible", fake_visible)
    monkeypatch.setattr(auth_wait, "_error_text", fake_error)


def test_logged_in_is_success() -> None:
    """A logged-in state resolves to SUCCESS."""
    result = wait_for_outcome(ScriptedPage(SessionState.LOGGED_IN))  # type: ignore[arg-type]
    assert result.outcome is Outcome.SUCCESS
    assert result.ok is True


def test_turnstile_overlay_is_blocked() -> None:
    """A visible Turnstile overlay is reported as a block, not success."""
    page = ScriptedPage(SessionState.NEEDS_SIGNIN, visible={auth_wait.CF_OVERLAY_SELECTOR})
    result = wait_for_outcome(page)  # type: ignore[arg-type]
    assert result.outcome is Outcome.TURNSTILE_BLOCK
    assert result.ok is False


def test_error_text_is_credential_error() -> None:
    """A visible error node carries its message into the outcome."""
    page = ScriptedPage(SessionState.NEEDS_SIGNIN, error_text="Wrong password")
    result = wait_for_outcome(page)  # type: ignore[arg-type]
    assert result.outcome is Outcome.CREDENTIAL_ERROR
    assert result.message == "Wrong password"


def test_success_wins_over_error() -> None:
    """A logged-in state beats a lingering error node."""
    page = ScriptedPage(SessionState.LOGGED_IN, error_text="stale toast")
    result = wait_for_outcome(page)  # type: ignore[arg-type]
    assert result.outcome is Outcome.SUCCESS


def test_no_signal_times_out() -> None:
    """Nothing resolving within the budget yields TIMEOUT, not success."""
    page = ScriptedPage(SessionState.UNKNOWN)
    result = wait_for_outcome(page, timeout_ms=1_000)  # type: ignore[arg-type]
    assert result.outcome is Outcome.TIMEOUT
    assert result.ok is False


def test_require_success_passes_when_logged_in() -> None:
    """require_success returns quietly on a genuine success."""
    require_success(ScriptedPage(SessionState.LOGGED_IN), "signin")  # type: ignore[arg-type]


def test_require_success_raises_on_credential_error() -> None:
    """A credential failure raises AuthError with the reason."""
    page = ScriptedPage(SessionState.NEEDS_SIGNIN, error_text="bad creds")
    with pytest.raises(AuthError, match="credential_error"):
        require_success(page, "signin")  # type: ignore[arg-type]


def test_require_success_raises_on_block() -> None:
    """A Turnstile block raises AuthError rather than reporting success."""
    page = ScriptedPage(SessionState.NEEDS_SIGNIN, visible={auth_wait.CF_OVERLAY_SELECTOR})
    with pytest.raises(AuthError, match="turnstile_block"):
        require_success(page, "signin")  # type: ignore[arg-type]


def test_require_success_raises_on_timeout() -> None:
    """A timeout raises AuthError."""
    page = ScriptedPage(SessionState.UNKNOWN)
    with pytest.raises(AuthError, match="timeout"):
        require_success(page, "signin", timeout_ms=1_000)  # type: ignore[arg-type]


def test_ok_is_false_for_every_non_success() -> None:
    """Only SUCCESS sets ok; every other outcome is a failure."""
    for outcome in Outcome:
        result = AuthOutcome(outcome)
        assert result.ok is (outcome is Outcome.SUCCESS)
