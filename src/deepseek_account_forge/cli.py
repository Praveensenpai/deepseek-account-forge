"""Command-line entrypoint for the DeepSeek auth automation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from patchright.sync_api import Page

from .age import AgeError, complete_age_if_present
from .auth_wait import AuthError
from .browser import LaunchOptions, open_session
from .credentials import DEFAULT_CRED_PATH, load_credentials
from .delete_account import DeleteError, run_delete
from .identity import IdentityMismatch, ensure_matching_session
from .navigate import DEFAULT_OUT_DIR, capture, extract_json, open_page, wait_for_selector
from .signin import run_signin
from .signup import EMAIL_SELECTOR, run_signup
from .state import SessionState, detect_state, report_state
from .token import DEFAULT_TOKEN_PATH, extract_user_token
from .verify import report_verification, verify_token

SIGNUP_URL = "https://chat.deepseek.com/sign_up"
SIGNIN_URL = "https://chat.deepseek.com/sign_in"
CHAT_URL = "https://chat.deepseek.com"


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="deepseek-forge",
        description="Stealth browser automation for chat.deepseek.com.",
    )
    parser.add_argument("url", nargs="?", default=None, help="Target URL to open.")
    parser.add_argument(
        "-s",
        "--selector",
        dest="selectors",
        action="append",
        default=[],
        help="CSS selector to extract. Repeat for multiple selectors.",
    )
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Output directory for screenshot and HTML.",
    )
    parser.add_argument(
        "--wait-until",
        default="networkidle",
        choices=["load", "domcontentloaded", "networkidle", "commit"],
        help="Playwright navigation wait condition.",
    )
    parser.add_argument(
        "-w",
        "--wait-for",
        default=None,
        help="Selector to wait for before capture.",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="Sign in (or skip if already logged in), clear age, extract + verify token.",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="Sign up with auto OTP, clear age, extract + verify token.",
    )
    parser.add_argument(
        "--cred",
        type=Path,
        default=DEFAULT_CRED_PATH,
        help="Path to the credential JSON file (default: ./cred.json).",
    )
    parser.add_argument(
        "--otp",
        default=None,
        help="OTP code to submit directly instead of fetching from mail.",
    )
    parser.add_argument(
        "--token-out",
        type=Path,
        default=DEFAULT_TOKEN_PATH,
        help="Path to save the extracted token (default: ./auth.json).",
    )
    parser.add_argument(
        "--delete-account",
        action="store_true",
        help="Open Settings -> Profile -> Delete and stop at the confirmation dialog.",
    )
    parser.add_argument(
        "--confirm-delete",
        action="store_true",
        help="With --delete-account, type the phrase and commit the deletion (irreversible).",
    )
    return parser


def _extract_and_verify(page: Page, token_out: Path) -> None:
    """Extract the userToken and prove it against the API."""
    auth = extract_user_token(page, token_out)
    report_verification(verify_token(auth.user_token))


def _resolve_login(context, page: Page, cred_path: Path) -> None:
    """Reach a logged-in state as the cred.json account.

    If the profile is signed in as a different account, clear that session and
    re-run on the fresh page. Raises AuthError when the account cannot be
    brought to LOGGED_IN.
    """
    creds = load_credentials(cred_path)
    for _attempt in range(2):
        state = detect_state(page)
        report_state(state)
        if state is SessionState.LOGGED_IN:
            ensure_matching_session(context, page, creds.email)
            if detect_state(page) is SessionState.LOGGED_IN:
                print("[login] already logged in; skipping form")
                return
            continue
        if state is SessionState.NEEDS_AGE:
            complete_age_if_present(page)
            run_signin(page, creds)
            return
        if state is SessionState.NEEDS_SIGNUP:
            raise AuthError("no account for this email; run --register to create one")
        page.goto(SIGNIN_URL, wait_until="domcontentloaded")
        run_signin(page, creds)
        return
    raise IdentityMismatch("could not establish a session matching cred.json after clearing twice")


def _resolve_register(context, page: Page, cred_path: Path, otp: str | None) -> None:
    """Create or confirm the cred.json account, then clear age.

    If the profile is signed in as a different account, clear that session and
    re-run on the fresh page.
    """
    creds = load_credentials(cred_path)
    for _attempt in range(2):
        state = detect_state(page)
        report_state(state)
        if state is SessionState.LOGGED_IN:
            ensure_matching_session(context, page, creds.email)
            if detect_state(page) is SessionState.LOGGED_IN:
                print("[register] already logged in; skipping signup")
                return
            continue
        if state is SessionState.NEEDS_AGE:
            complete_age_if_present(page)
            return
        page.goto(SIGNUP_URL, wait_until="domcontentloaded")
        wait_for_selector(page, EMAIL_SELECTOR, timeout_ms=15_000)
        run_signup(page, creds, otp)
        return
    raise IdentityMismatch("could not establish a session matching cred.json after clearing twice")


def _resolve_delete(context, page: Page, cred_path: Path) -> None:
    """Bring the profile to the cred.json account before deleting.

    If the profile is signed in as someone else, clear that session and sign
    in as cred.json. Deleting the wrong account is unrecoverable, so this never
    proceeds on an unverified identity.
    """
    creds = load_credentials(cred_path)
    for _attempt in range(2):
        state = detect_state(page)
        report_state(state)
        if state is SessionState.LOGGED_IN:
            ensure_matching_session(context, page, creds.email)
            if detect_state(page) is SessionState.LOGGED_IN:
                print("[delete] session matches cred.json")
                return
            continue
        if state is SessionState.NEEDS_AGE:
            complete_age_if_present(page)
            continue
        page.goto(SIGNIN_URL, wait_until="domcontentloaded")
        run_signin(page, creds)
        return
    raise IdentityMismatch("could not establish a session matching cred.json for deletion")


def _identity_preflight(context, page: Page, cred_path: Path) -> None:
    """Check the signed-in account against cred.json before acting.

    Lands on the authenticated root so a cached session is visible regardless
    of the flag's target URL. A mismatch clears the account session in place.
    """
    if "chat.deepseek.com" not in page.url:
        page.goto(CHAT_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2_000)
    ensure_matching_session(context, page, load_credentials(cred_path).email)


def run(
    url: str | None,
    selectors: list[str],
    out_dir: Path,
    wait_until: str,
    wait_for: str | None,
    login: bool,
    register: bool,
    cred_path: Path,
    otp: str | None,
    token_out: Path,
    delete_account: bool,
    confirm_delete: bool,
) -> int:
    """Execute a single run."""
    options = LaunchOptions.from_env()
    # Each flow has a sensible default target; an explicit URL still overrides.
    if url:
        effective_url = url
    elif login:
        effective_url = SIGNIN_URL
    elif register:
        effective_url = SIGNUP_URL
    else:
        effective_url = CHAT_URL
    # Signup needs the email field present before it starts filling.
    effective_wait_for = wait_for
    print(f"[deepseek-forge] headless={options.headless} url={effective_url}")
    with open_session(options) as context:
        page = open_page(context, effective_url, wait_until=wait_until)
        if effective_wait_for:
            found = wait_for_selector(page, effective_wait_for, timeout_ms=options.timeout_ms)
            print(f"[deepseek-forge] wait_for={effective_wait_for!r} found={found}")
        if login or register or delete_account:
            _identity_preflight(context, page, cred_path)
        if login:
            _resolve_login(context, page, cred_path)
            _extract_and_verify(page, token_out)
        elif register:
            _resolve_register(context, page, cred_path, otp)
            _extract_and_verify(page, token_out)
        elif delete_account:
            _resolve_delete(context, page, cred_path)
            run_delete(page, confirm=confirm_delete)
        result = capture(page, effective_url, out_dir)
        print(f"[deepseek-forge] final_url={result.final_url}")
        print(f"[deepseek-forge] title={result.title!r}")
        print(f"[deepseek-forge] screenshot={result.screenshot}")
        print(f"[deepseek-forge] html={result.html}")
        if selectors:
            print(extract_json(page, selectors))
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    args = build_parser().parse_args(argv)
    try:
        return run(
            args.url,
            args.selectors,
            args.out,
            args.wait_until,
            args.wait_for,
            args.login,
            args.register,
            args.cred,
            args.otp,
            args.token_out,
            args.delete_account,
            args.confirm_delete,
        )
    except KeyboardInterrupt:
        return 130
    except AuthError as exc:
        print(f"[deepseek-forge] auth failed: {exc}", file=sys.stderr)
        return 2
    except DeleteError as exc:
        print(f"[deepseek-forge] delete failed: {exc}", file=sys.stderr)
        return 3
    except AgeError as exc:
        print(f"[deepseek-forge] age verification failed: {exc}", file=sys.stderr)
        return 4
    except Exception as exc:  # surface a clean CLI error
        print(f"[deepseek-forge] error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
