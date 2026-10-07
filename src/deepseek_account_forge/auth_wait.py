"""Wait for the outcome of an auth submit and classify it.

Clicking submit is not success. The page can land on the chat UI, stall behind
Cloudflare Turnstile, or render a credential error. This module watches for
those outcomes so callers never report a blocked or failed login as done.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from patchright.sync_api import Page

from .state import SessionState, detect_state

CF_OVERLAY_SELECTOR = "#cf-overlay"
ERROR_NODE_SELECTORS = (
    ".ds-toast",
    ".ds-notification",
    ".ds-form-item__error",
    '[class*="error"]',
    '[class*="toast"]',
)
SUCCESS_TIMEOUT_MS = 45_000
POLL_STEP_MS = 500
ERROR_TEXT_LIMIT = 300


class Outcome(Enum):
    """How an auth submit resolved."""

    SUCCESS = "success"
    TURNSTILE_BLOCK = "turnstile_block"
    CREDENTIAL_ERROR = "credential_error"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class AuthOutcome:
    """Result of waiting on an auth submit."""

    outcome: Outcome
    message: str = ""

    @property
    def ok(self) -> bool:
        """True only when the submit actually authenticated."""
        return self.outcome is Outcome.SUCCESS


class AuthError(RuntimeError):
    """Raised when an auth submit does not reach a logged-in state."""


def _visible(page: Page, selector: str) -> bool:
    """Return True when a selector matches a visible node."""
    try:
        return page.locator(selector).first.is_visible(timeout=500)
    except Exception:
        return False


def _error_text(page: Page) -> str | None:
    """Return the first visible error-like node's text, or None."""
    for selector in ERROR_NODE_SELECTORS:
        try:
            node = page.locator(selector).first
            if node.is_visible(timeout=300):
                text = re.sub(r"\s+", " ", (node.inner_text() or "")).strip()
                if text:
                    return text[:ERROR_TEXT_LIMIT]
        except Exception:
            continue
    return None


def wait_for_outcome(page: Page, timeout_ms: int = SUCCESS_TIMEOUT_MS) -> AuthOutcome:
    """Watch the page until the submit resolves to a known outcome.

    Success wins first: a logged-in state is the only signal that the request
    actually authenticated. A visible Turnstile overlay is reported as a block,
    and any visible error node as a credential failure.
    """
    waited = 0
    while waited < timeout_ms:
        if detect_state(page) is SessionState.LOGGED_IN:
            return AuthOutcome(Outcome.SUCCESS)
        if _visible(page, CF_OVERLAY_SELECTOR):
            return AuthOutcome(
                Outcome.TURNSTILE_BLOCK,
                "Cloudflare Turnstile is blocking the request",
            )
        text = _error_text(page)
        if text:
            return AuthOutcome(Outcome.CREDENTIAL_ERROR, text)
        page.wait_for_timeout(POLL_STEP_MS)
        waited += POLL_STEP_MS
    return AuthOutcome(Outcome.TIMEOUT, f"no outcome after {timeout_ms} ms")


def require_success(page: Page, action: str, timeout_ms: int = SUCCESS_TIMEOUT_MS) -> None:
    """Wait for the outcome and raise AuthError unless it succeeded."""
    result = wait_for_outcome(page, timeout_ms)
    if result.ok:
        print(f"[{action}] authenticated")
        return
    detail = f": {result.message}" if result.message else ""
    raise AuthError(f"{action} failed ({result.outcome.value}){detail}")
