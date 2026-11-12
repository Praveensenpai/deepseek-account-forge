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

    For local parts <= 4 chars: keep first char and star the rest.
    For local parts 5-10 chars: keep first 2 and last 2, star middle.
    For local parts > 10 chars: keep first 3 and last 3, star middle.
    """
    local, sep, domain = email.partition("@")
    if not sep:
        return email
    if len(local) <= 4:
        masked = local[:1] + "*" * max(len(local) - 1, 0)
    elif len(local) <= 10:
        masked = local[:2] + "*" * (len(local) - 4) + local[-2:]
    else:
        masked = local[:3] + "*" * (len(local) - 6) + local[-3:]
    return f"{masked}@{domain}"


def _matches_mask(seen: str, expected_email: str) -> bool:
    """Check if a masked email matches expected email strictly or by pattern."""
    if seen == mask_email(expected_email):
        return True

    seen_local, seen_sep, seen_domain = seen.partition("@")
    exp_local, exp_sep, exp_domain = expected_email.partition("@")
    if not seen_sep or not exp_sep or seen_domain != exp_domain:
        return False
    if "*" not in seen_local or len(seen_local) != len(exp_local):
        return False

    prefix = seen_local.split("*")[0]
    suffix = seen_local.split("*")[-1]
    return exp_local.startswith(prefix) and exp_local.endswith(suffix)


def read_session_email(page: Page) -> str | None:
    """Return the masked email shown in the account control, or None."""
    try:
        node = page.locator(ACCOUNT_LABEL_SELECTOR).first
        if node.is_visible(timeout=5_000):
            text = (node.inner_text() or "").strip()
            if text:
                return text
        account_ctrl = page.locator("div._2afd28d").first
        if account_ctrl.is_visible(timeout=2_000):
            for line in (account_ctrl.inner_text() or "").splitlines():
                if "@" in line:
                    return line.strip()
    except Exception:
        return None
    return None


def clear_account_session(context: BrowserContext, page: Page) -> None:
    """Drop only the local browser session without triggering a backend logout.

    This surgically removes the session cookies (ds_session_id) and localStorage/
    sessionStorage keys directly from the browser without calling DeepSeek's logout
    API. This ensures the extracted token remains 100% live and valid for other APIs.
    """
    for cookie in context.cookies():
        if cookie["name"] in SESSION_COOKIE_NAMES:
            context.clear_cookies(name=cookie["name"], domain=cookie["domain"])
    keys = ", ".join(f'"{k}"' for k in SESSION_STORAGE_KEYS)
    page.evaluate(
        f"() => {{ for (const k of [{keys}]) localStorage.removeItem(k); "
        "window.sessionStorage.clear(); "
        "for (let i = localStorage.length - 1; i >= 0; i--) { "
        "const key = localStorage.key(i); "
        "if (key && (key.includes('_userStorage') || key.includes('userToken'))) "
        "localStorage.removeItem(key); } }"
    )


def session_matches(page: Page, expected_email: str) -> bool:
    """True when the visible masked email matches expected_email."""
    seen = read_session_email(page)
    if seen is None:
        return False
    return _matches_mask(seen, expected_email)


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
    if _matches_mask(seen, expected_email):
        print(f"[identity] session matches {seen}")
        return
    print(
        f"[identity] session is {seen} but target is {mask_email(expected_email)}; "
        "removing local browser session (token preserved for other APIs)"
    )
    clear_account_session(context, page)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(2_000)
