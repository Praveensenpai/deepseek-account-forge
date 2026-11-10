"""Command-line entrypoint for the DeepSeek auth automation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from patchright.sync_api import Page

from .age import AgeError, complete_age_if_present
from .auth_wait import AuthError, require_success
from .browser import LaunchOptions, open_session
from .cooldown import check_b11_cooldown
from .credentials import DEFAULT_CRED_PATH, increment_counter, load_credentials
from .delete_account import DeleteError, run_delete
from .gateway import DEFAULT_GATEWAY_KEY, DEFAULT_GATEWAY_URL, push_token_to_gateway
from .identity import IdentityMismatch, ensure_matching_session
from .navigate import DEFAULT_OUT_DIR, capture, extract_json, open_page, wait_for_selector
from .signin import handle_verify_modal_if_present, run_signin
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
        default="domcontentloaded",
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
        "-i",
        "--index",
        type=int,
        default=None,
        help="Account index for plus-addressing (e.g. 10 for user+10@gmail.com).",
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
        "--gateway-url",
        default=DEFAULT_GATEWAY_URL,
        help="deeperseeker-rs admin tokens endpoint (default: http://127.0.0.1:4000/api/admin/tokens).",
    )
    parser.add_argument(
        "--gateway-key",
        default=DEFAULT_GATEWAY_KEY,
        help="Master API key for deeperseeker-rs admin endpoint (default: dseeker).",
    )
    parser.add_argument(
        "--no-gateway",
        action="store_true",
        help="Do not push extracted tokens to the deeperseeker-rs gateway.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt if B11 cooldown is active.",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=None,
        help="Optional directory to persist browser profile across runs (default: ephemeral).",
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


def _extract_and_verify(
    page: Page,
    token_out: Path,
    index: int | None = None,
    email: str | None = None,
    gateway_url: str = DEFAULT_GATEWAY_URL,
    gateway_key: str = DEFAULT_GATEWAY_KEY,
    sync_gateway: bool = True,
) -> None:
    """Extract the userToken, prove it against the API, and push to gateway."""
    auth = extract_user_token(page, token_out)
    report_verification(verify_token(auth.user_token))
    if sync_gateway:
        alias = email or (f"index-{index}" if index is not None else "primary")
        push_token_to_gateway(auth.user_token, alias=alias, url=gateway_url, api_key=gateway_key)


def _resolve_login(
    context, page: Page, cred_path: Path, otp: str | None = None, index: int | None = None
) -> str:
    """Reach a logged-in state as the cred.json account."""
    creds = load_credentials(cred_path).with_resolved_email(index)
    for _attempt in range(2):
        state = detect_state(page)
        report_state(state)
        if state is SessionState.LOGGED_IN:
            ensure_matching_session(context, page, creds.email)
            if detect_state(page) is SessionState.LOGGED_IN:
                print(f"[login] already logged in as {creds.email}; skipping form")
                return creds.email
            continue
        if state is SessionState.NEEDS_VERIFY:
            handle_verify_modal_if_present(page, creds, otp)
            require_success(page, "signin_verification")
            if complete_age_if_present(page):
                print("[signin] age verification completed")
            return creds.email
        if state is SessionState.NEEDS_AGE:
            complete_age_if_present(page)
            run_signin(page, creds, otp)
            return creds.email
        if state is SessionState.NEEDS_SIGNUP:
            raise AuthError("no account for this email; run --register to create one")
        page.goto(SIGNIN_URL, wait_until="domcontentloaded")
        run_signin(page, creds, otp)
        return creds.email
    raise IdentityMismatch("could not establish a session matching cred.json after clearing twice")


def _resolve_register(
    context, page: Page, cred_path: Path, otp: str | None, index: int | None = None
) -> str:
    """Create or confirm the cred.json account, then clear age."""
    creds = load_credentials(cred_path).with_resolved_email(index)
    for _attempt in range(2):
        state = detect_state(page)
        report_state(state)
        if state is SessionState.LOGGED_IN:
            ensure_matching_session(context, page, creds.email)
            if detect_state(page) is SessionState.LOGGED_IN:
                print(f"[register] already logged in as {creds.email}; skipping signup")
                return creds.email
            continue
        if state is SessionState.NEEDS_AGE:
            complete_age_if_present(page)
            return creds.email
        page.goto(SIGNUP_URL, wait_until="domcontentloaded")
        wait_for_selector(page, EMAIL_SELECTOR, timeout_ms=15_000)
        run_signup(page, creds, otp)
        return creds.email
    raise IdentityMismatch("could not establish a session matching cred.json after clearing twice")


def _resolve_delete(context, page: Page, cred_path: Path, index: int | None = None) -> None:
    """Bring the profile to the cred.json account before deleting."""
    creds = load_credentials(cred_path).with_resolved_email(index)
    for _attempt in range(2):
        state = detect_state(page)
        report_state(state)
        if state is SessionState.LOGGED_IN:
            ensure_matching_session(context, page, creds.email)
            if detect_state(page) is SessionState.LOGGED_IN:
                print(f"[delete] session matches {creds.email}")
                return
            continue
        if state is SessionState.NEEDS_AGE:
            complete_age_if_present(page)
            continue
        page.goto(SIGNIN_URL, wait_until="domcontentloaded")
        run_signin(page, creds)
        return
    raise IdentityMismatch("could not establish a session matching cred.json for deletion")


def _identity_preflight(context, page: Page, cred_path: Path, index: int | None = None) -> None:
    """Check the signed-in account against cred.json before acting."""
    creds = load_credentials(cred_path).with_resolved_email(index)
    if detect_state(page) is SessionState.LOGGED_IN:
        if page.url.rstrip("/") != CHAT_URL:
            page.goto(CHAT_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(2_000)
        ensure_matching_session(context, page, creds.email)


def run(
    url: str | None,
    selectors: list[str],
    out_dir: Path,
    wait_until: str,
    wait_for: str | None,
    login: bool,
    register: bool,
    index: int | None,
    cred_path: Path,
    otp: str | None,
    token_out: Path,
    delete_account: bool,
    confirm_delete: bool,
    gateway_url: str = DEFAULT_GATEWAY_URL,
    gateway_key: str = DEFAULT_GATEWAY_KEY,
    no_gateway: bool = False,
    profile: Path | None = None,
    yes: bool = False,
) -> int:
    """Execute a single run."""
    if register and not check_b11_cooldown(force=yes):
        print("[deepseek-forge] registration aborted due to active B11 cooldown")
        return 0
    options = LaunchOptions.from_env(profile=profile)
    effective_url = url or (SIGNIN_URL if login else (SIGNUP_URL if register else CHAT_URL))
    raw_creds = load_credentials(cred_path)
    eff_index = index if index is not None else raw_creds.counter
    gw_url_override = raw_creds.gateway_url or DEFAULT_GATEWAY_URL
    eff_gw_url = gateway_url if gateway_url != DEFAULT_GATEWAY_URL else gw_url_override
    gw_key_override = raw_creds.gateway_key or DEFAULT_GATEWAY_KEY
    eff_gw_key = gateway_key if gateway_key != DEFAULT_GATEWAY_KEY else gw_key_override
    print(f"[deepseek-forge] headless={options.headless} url={effective_url} index={eff_index}")
    with open_session(options) as context:
        page = open_page(context, effective_url, wait_until=wait_until)
        if wait_for and wait_for_selector(page, wait_for, timeout_ms=options.timeout_ms):
            print(f"[deepseek-forge] wait_for={wait_for!r} found=True")
        if login or register or delete_account:
            _identity_preflight(context, page, cred_path, index=eff_index)
        if login:
            login_email = _resolve_login(context, page, cred_path, otp=otp, index=eff_index)
            _extract_and_verify(
                page,
                token_out,
                index=eff_index,
                email=login_email,
                gateway_url=eff_gw_url,
                gateway_key=eff_gw_key,
                sync_gateway=not no_gateway,
            )
        elif register:
            reg_email = _resolve_register(context, page, cred_path, otp, index=eff_index)
            _extract_and_verify(
                page,
                token_out,
                index=eff_index,
                email=reg_email,
                gateway_url=eff_gw_url,
                gateway_key=eff_gw_key,
                sync_gateway=not no_gateway,
            )
            nxt = increment_counter(cred_path)
            print(f"[register] registered {reg_email}; next counter={nxt}")
        elif delete_account:
            _resolve_delete(context, page, cred_path, index=eff_index)
            run_delete(page, confirm=confirm_delete)
        result = capture(page, effective_url, out_dir)
        print(f"[deepseek-forge] final_url={result.final_url} screenshot={result.screenshot}")
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
            args.index,
            args.cred,
            args.otp,
            args.token_out,
            args.delete_account,
            args.confirm_delete,
            args.gateway_url,
            args.gateway_key,
            args.no_gateway,
            args.profile,
            args.yes,
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
    except Exception as exc:
        print(f"[deepseek-forge] error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
