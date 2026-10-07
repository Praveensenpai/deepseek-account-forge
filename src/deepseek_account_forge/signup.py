"""Interactive DeepSeek signup flow with terminal OTP prompt."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from patchright.sync_api import Page

from .age import complete_age_if_present
from .auth_wait import require_success
from .credentials import Credentials
from .otp_mail import MailConfig, OtpMailError, fetch_latest_otp

EMAIL_SELECTOR = 'input[placeholder="Email address"]'
PASSWORD_SELECTOR = 'input[placeholder="Password"]'
CONFIRM_SELECTOR = 'input[placeholder="Confirm password"]'
CODE_SELECTOR = 'input[placeholder="Code"]'
SEND_CODE_TEXT = "Send code"
SIGNUP_TEXT = "Sign up"


def _fill(page: Page, selector: str, value: str) -> None:
    """Clear and type a value into a field."""
    field = page.wait_for_selector(selector, state="visible")
    field.click()
    field.fill("")
    field.type(value, delay=25)


def fill_credentials(page: Page, creds: Credentials) -> None:
    """Fill email, password, and confirm-password fields."""
    _fill(page, EMAIL_SELECTOR, creds.email)
    _fill(page, PASSWORD_SELECTOR, creds.password)
    # DeepSeek requires the confirm box filled; it is always the same password.
    _fill(page, CONFIRM_SELECTOR, creds.password)
    print(f"[signup] filled credentials for {creds.email}")


def request_code(page: Page) -> None:
    """Click the 'Send code' button to trigger the email OTP."""
    button = page.get_by_text(SEND_CODE_TEXT, exact=True)
    button.click()
    print("[signup] clicked 'Send code'; check your email for the OTP")


def prompt_for_otp(
    otp_override: str | None = None,
    creds: Credentials | None = None,
    since: datetime | None = None,
) -> str:
    """Return the OTP from an override, the OTP env var, IMAP, or a prompt.

    Order: ``--otp`` / ``OTP`` env -> IMAP fetch (when creds carry an App
    Password) -> terminal prompt. ``since`` is the instant the code was
    requested; mail older than it is ignored, so a stale code cannot win. The
    IMAP branch is what removes the manual step; if it fails the flow falls
    back to prompting rather than aborting.
    """
    override = otp_override or os.environ.get("OTP", "")
    if override.strip():
        print("[signup] using provided OTP")
        return override.strip()
    if creds is not None and creds.has_imap:
        print(f"[signup] fetching OTP from {creds.imap_email} over IMAP...")
        try:
            code = fetch_latest_otp(
                MailConfig(email=creds.imap_email, app_password=creds.imap_password),
                since=since,
            )
            print("[signup] OTP fetched from mail")
            return code
        except OtpMailError as exc:
            print(f"[signup] IMAP fetch failed: {exc}; falling back to prompt")
    while True:
        try:
            code = input("[signup] enter the OTP from your email: ").strip()
        except EOFError as exc:
            raise RuntimeError(
                "no TTY to read the OTP; pass --otp <code> or set OTP=<code>"
            ) from exc
        if code:
            return code
        print("[signup] OTP cannot be empty, try again")


def submit_code(page: Page, code: str) -> None:
    """Fill the OTP field and click the signup button."""
    _fill(page, CODE_SELECTOR, code)
    print("[signup] filled OTP")


def click_signup(page: Page) -> None:
    """Click the final 'Sign up' submit button."""
    page.get_by_text(SIGNUP_TEXT, exact=True).click()
    print("[signup] clicked 'Sign up'")


def run_signup(page: Page, creds: Credentials, otp: str | None = None) -> None:
    """Run the full signup: fill, send code, prompt OTP, submit, verify.

    Raises AuthError when the submit does not reach a logged-in state, so a
    duplicate email, bad OTP, or Turnstile block is never reported as success.
    """
    fill_credentials(page, creds)
    # Cutoff for the OTP: only mail that arrives after this click is valid.
    requested_at = datetime.now(UTC)
    request_code(page)
    code = prompt_for_otp(otp, creds, since=requested_at)
    submit_code(page, code)
    click_signup(page)
    require_success(page, "signup")
    print(f"[signup] final_url={page.url}")
    if complete_age_if_present(page):
        print("[signup] age verification completed")
