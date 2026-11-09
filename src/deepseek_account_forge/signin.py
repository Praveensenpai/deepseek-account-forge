"""Email/password sign-in flow for DeepSeek."""

from __future__ import annotations

from datetime import UTC, datetime

from patchright.sync_api import Page

from .age import complete_age_if_present
from .auth_wait import AuthError, require_success
from .credentials import Credentials
from .signup import prompt_for_otp
from .state import SessionState, detect_state

ACCOUNT_SELECTOR = 'input[placeholder="Phone number / email address"]'
PASSWORD_SELECTOR = 'input[placeholder="Password"]'
SUBMIT_SELECTOR = "div.ds-button--filled"
VERIFY_MODAL_TEXT = "Verify your account"
VERIFY_CODE_SELECTOR = 'input[placeholder*="verification code" i], input[placeholder*="Code" i]'
SEND_CODE_TEXT = "Send code"
VERIFY_SUBMIT_TEXT = "Verify and log in"


def _fill(page: Page, selector: str, value: str) -> None:
    """Clear and type a value into a field."""
    field = page.wait_for_selector(selector, state="visible")
    field.click()
    field.fill("")
    field.type(value, delay=25)


def fill_signin(page: Page, creds: Credentials) -> None:
    """Fill the account and password fields."""
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


def wait_for_signin_state(page: Page, timeout_ms: int = 15_000) -> SessionState:
    """Poll until the page transitions from NEEDS_SIGNIN to another state."""
    waited = 0
    step_ms = 500
    while waited < timeout_ms:
        state = detect_state(page)
        if state is not SessionState.NEEDS_SIGNIN:
            return state
        page.wait_for_timeout(step_ms)
        waited += step_ms
    return detect_state(page)


def handle_verify_modal_if_present(
    page: Page, creds: Credentials, otp: str | None = None, timeout_ms: int = 10_000
) -> bool:
    """Detect and resolve the 'Verify your account' login challenge."""
    try:
        modal = page.get_by_text(VERIFY_MODAL_TEXT).first
        subtitle = page.get_by_text("complete verification to continue logging in").first
        if not modal.is_visible(timeout=timeout_ms) and not subtitle.is_visible(timeout=500):
            return False
    except Exception:
        return False

    print(f"[signin] login verification challenge triggered for {creds.email}; requesting OTP...")
    requested_at = datetime.now(UTC)
    send_btn = page.get_by_text(SEND_CODE_TEXT, exact=True).first
    send_btn.click()
    print("[signin] clicked 'Send code'; check your email for the OTP")

    code = prompt_for_otp(otp, creds, since=requested_at)
    code_field = page.locator(VERIFY_CODE_SELECTOR).first
    code_field.wait_for(state="visible", timeout=10_000)
    code_field.click()
    code_field.fill("")
    code_field.type(code, delay=25)
    print("[signin] filled OTP")

    verify_btn = page.get_by_text(VERIFY_SUBMIT_TEXT, exact=True).first
    verify_btn.click()
    print(f"[signin] clicked '{VERIFY_SUBMIT_TEXT}'")
    return True


def run_signin(page: Page, creds: Credentials, otp: str | None = None) -> None:
    """Run the full sign-in: fill, submit, verify outcome, clear age gate."""
    fill_signin(page, creds)
    click_signin(page)
    state = wait_for_signin_state(page, timeout_ms=15_000)
    if state is SessionState.NEEDS_VERIFY:
        handle_verify_modal_if_present(page, creds, otp, timeout_ms=5_000)
        require_success(page, "signin_verification")
    elif state not in (SessionState.LOGGED_IN, SessionState.NEEDS_AGE):
        if handle_verify_modal_if_present(page, creds, otp, timeout_ms=2_000):
            require_success(page, "signin_verification")
        else:
            require_success(page, "signin")
    print(f"[signin] final_url={page.url}")
    if complete_age_if_present(page):
        print("[signin] age verification completed")
