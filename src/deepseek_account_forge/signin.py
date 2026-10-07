"""Email/password sign-in flow for DeepSeek."""

from __future__ import annotations

from patchright.sync_api import Page

from .age import complete_age_if_present
from .auth_wait import AuthError, require_success
from .credentials import Credentials

ACCOUNT_SELECTOR = 'input[placeholder="Phone number / email address"]'
PASSWORD_SELECTOR = 'input[placeholder="Password"]'
SUBMIT_SELECTOR = "div.ds-button--filled"


def _fill(page: Page, selector: str, value: str) -> None:
    """Clear and type a value into a field."""
    field = page.wait_for_selector(selector, state="visible")
    field.click()
    field.fill("")
    field.type(value, delay=25)


def fill_signin(page: Page, creds: Credentials) -> None:
    """Fill the account and password fields.

    Waits for the account field first. If the session is already authenticated,
    /sign_in redirects to the chat home and the form never renders, so raise a
    clear error instead of a bare 60s selector timeout.
    """
    try:
        page.wait_for_selector(ACCOUNT_SELECTOR, state="visible", timeout=15_000)
    except Exception as exc:
        raise AuthError(
            f"sign-in form not found at {page.url}; the session may already be logged in"
        ) from exc
    _fill(page, ACCOUNT_SELECTOR, creds.email)
    _fill(page, PASSWORD_SELECTOR, creds.password)
    print(f"[signin] filled credentials for {creds.email}")


def click_signin(page: Page) -> None:
    """Click the primary filled submit button."""
    page.locator(SUBMIT_SELECTOR).first.click()
    print("[signin] clicked 'Log in'")


def run_signin(page: Page, creds: Credentials) -> None:
    """Run the full sign-in: fill, submit, verify outcome, clear age gate.

    Raises AuthError when the submit does not reach a logged-in state, so a
    Turnstile block or a bad credential is never reported as success.
    """
    fill_signin(page, creds)
    click_signin(page)
    require_success(page, "signin")
    print(f"[signin] final_url={page.url}")
    if complete_age_if_present(page):
        print("[signin] age verification completed")
