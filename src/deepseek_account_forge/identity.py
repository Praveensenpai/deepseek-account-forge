"""Verify the signed-in account matches cred.json before acting.

A destructive flag must never run against the wrong account. The page shows a
masked email (``pv*****03@gmail.com``); this module reproduces DeepSeek's mask
rule and compares it to the cred email. On mismatch it clears only the account
session (not the HTTP cache) and retries the flow.
"""

from __future__ import annotations

from patchright.sync_api import BrowserContext, Page

from .auth_wait import AuthError
from .state import SessionState, detect_state

ACCOUNT_LABEL_SELECTOR = "div._9d8da05"
SESSION_COOKIE_NAMES = ("ds_session_id",)
SESSION_STORAGE_KEYS = ("userToken",)
MAX_CLEAR_ATTEMPTS = 2


class IdentityMismatch(AuthError):
    """Raised when the signed-in account does not match cred.json."""


def mask_email(email: str) -> str:
    """Reproduce DeepSeek's masked-email display.

    Keep the first two and last two characters of the local part, replace the
    middle with stars, and keep the domain. For short local parts, keep the
    first character and star the rest.
    """
    local, sep, domain = email.partition("@")
    if not sep:
        return email
    if len(local) <= 4:
        masked = local[:1] + "*" * max(len(local) - 1, 0)
    else:
        masked = local[:2] + "*" * (len(local) - 4) + local[-2:]
    return f"{masked}@{domain}"


def read_session_email(page: Page) -> str | None:
    """Return the masked email shown in the account control, or None."""
    try:
        node = page.locator(ACCOUNT_LABEL_SELECTOR).first
        if node.is_visible(timeout=3_000):
            text = (node.inner_text() or "").strip()
            return text or None
    except Exception:
        return None
    return None


def clear_account_session(context: BrowserContext, page: Page) -> None:
    """Drop only the DeepSeek account session, keeping the HTTP cache.

    A blanket clear_cookies() would also wipe the static-asset cache and force
    a full re-download. This removes just the session cookie and the account
    storage keys so the browser logs out without losing cached JS/CSS/images.
    """
    for cookie in context.cookies():
        if cookie["name"] in SESSION_COOKIE_NAMES:
            context.clear_cookies(name=cookie["name"], domain=cookie["domain"])
    keys = ", ".join(f'"{k}"' for k in SESSION_STORAGE_KEYS)
    page.evaluate(
        f"() => {{ for (const k of [{keys}]) localStorage.removeItem(k); "
        "for (let i = localStorage.length - 1; i >= 0; i--) { "
        "const key = localStorage.key(i); "
        "if (key && key.includes('_userStorage')) localStorage.removeItem(key); } }"
    )


def session_matches(page: Page, expected_email: str) -> bool:
    """True when the visible masked email equals the mask of expected_email."""
    seen = read_session_email(page)
    if seen is None:
        return False
    return seen == mask_email(expected_email)


def ensure_matching_session(
    context: BrowserContext,
    page: Page,
    expected_email: str,
) -> None:
    """Assert the signed-in account matches cred.json, or clear and report.

    The caller owns the auth retry: this only inspects the visible account,
    and when it differs, surgically clears the account session so the caller
    can re-run its flow on a fresh page. Raises IdentityMismatch when the
    account label cannot be read (fail closed).
    """
    if detect_state(page) is not SessionState.LOGGED_IN:
        return
    seen = read_session_email(page)
    if seen is None:
        raise IdentityMismatch("logged in but the account label is unreadable; refusing to act")
    if seen == mask_email(expected_email):
        print(f"[identity] session matches {seen}")
        return
    print(
        f"[identity] session is {seen} but cred.json is "
        f"{mask_email(expected_email)}; clearing account session"
    )
    clear_account_session(context, page)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(2_000)
