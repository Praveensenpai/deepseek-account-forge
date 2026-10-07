"""Detect and resolve the DeepSeek session state before acting.

The CLI should never blindly sign up or blindly trust a cached token. This
module answers one question first: is the session logged in, blocked by the
age modal, or unauthenticated?
"""

from __future__ import annotations

from enum import Enum

from patchright.sync_api import Page

CHAT_INPUT_SELECTOR = "textarea"
NEW_CHAT_TEXT = "text=New chat"
AGE_MODAL_TEXT = "text=When were you born?"
SIGNUP_FORM_SELECTOR = 'input[placeholder="Email address"]'
SIGNIN_FORM_SELECTOR = 'input[placeholder="Phone number / email address"]'


class SessionState(Enum):
    """What the current page represents."""

    LOGGED_IN = "logged_in"
    NEEDS_AGE = "needs_age"
    NEEDS_SIGNUP = "needs_signup"
    NEEDS_SIGNIN = "needs_signin"
    UNKNOWN = "unknown"


def _visible(page: Page, selector: str) -> bool:
    """Return True when a selector matches at least one visible node."""
    try:
        return page.locator(selector).first.is_visible(timeout=2_000)
    except Exception:
        return False


def detect_state(page: Page) -> SessionState:
    """Inspect the page and classify the session.

    Checked in order of certainty: the age modal and signup form are explicit
    gates; the chat input plus "New chat" only appear once authenticated.
    """
    if _visible(page, AGE_MODAL_TEXT):
        return SessionState.NEEDS_AGE
    if _visible(page, SIGNUP_FORM_SELECTOR):
        return SessionState.NEEDS_SIGNUP
    if _visible(page, SIGNIN_FORM_SELECTOR):
        return SessionState.NEEDS_SIGNIN
    if _visible(page, CHAT_INPUT_SELECTOR) or _visible(page, NEW_CHAT_TEXT):
        return SessionState.LOGGED_IN
    return SessionState.UNKNOWN


def report_state(state: SessionState) -> None:
    """Print the detected state in a stable, greppable format."""
    print(f"[state] detected={state.value}")
