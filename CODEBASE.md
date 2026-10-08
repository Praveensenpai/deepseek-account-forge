# CODEBASE

AI-first index of `deepseek-account-forge`. Dense symbol skeletons, module roles, and dependencies. Update on every file add/remove/rename/signature change.

## Purpose

DeepSeek account forge automation for `chat.deepseek.com`. Handles the full lifecycle: launch stealth Chromium, detect session state, sign up (email OTP), sign in, clear the age-verification modal, extract + verify the auth token, and delete the account through Settings.

## Stack

- Python >=3.11, managed by `uv`
- `patchright` (patched Playwright, stealth Chromium)
- `httpx` (token verification)
- `ruff` (dev)

## Layout

```
src/deepseek_account_forge/
  __init__.py      __version__
  browser.py       stealth launch + persistent profile session
  navigate.py      open page, capture artifacts, extract selectors
  credentials.py   load/validate cred.json
  state.py         session-state detection (logged in / age / signin / signup)
  auth_wait.py     post-submit outcome classification (success / blocked / error)
  signup.py        email OTP signup flow
  signin.py        email/password sign-in flow
  age.py           age-verification modal fill
  token.py         userToken extraction from localStorage
  verify.py        token verification against the live API
  otp_mail.py      IMAP OTP retrieval from a Gmail inbox
  delete_account.py  Settings -> Profile -> Delete flow (safe mode + commit)
  identity.py      account-mismatch guard (mask rule, surgical clear)
  cli.py           argparse entrypoint, flow orchestration
```

## Modules

### browser.py
- `DEFAULT_USER_DATA_DIR: Path` — `~/.local/share/deepseek-account-forge/profile`
- `DEFAULT_TIMEOUT_MS: int` = 60000
- `DEFAULT_VIEWPORT: dict` = 1280x900
- `@dataclass LaunchOptions` — `headless`, `user_data_dir`, `timeout_ms`, `locale`, `timezone`
  - `from_env() -> LaunchOptions` — reads `HEADLESS`, `STEALTH_PROFILE`
- `_sanitize_preferences(user_data_dir) -> None` — patches `Default/Preferences` before launch: `exit_type=Normal`, `exited_cleanly=true`, `password_manager_enabled=false`, `credentials_enable_service=false`, `has_seen_welcome_page=true`, `check_default_browser=false`. Non-fatal on missing/unreadable file. Silences restore, save-password, and default-browser prompts.
- `launch_context(playwright, options) -> BrowserContext` — persistent Chromium, stealth args
  - pins `viewport=DEFAULT_VIEWPORT` (not `no_viewport`) so the left rail renders on-screen; some window managers ignore `--window-size` and collapse the sidebar to negative x
  - quiet-launch flags: `--no-first-run`, `--no-default-browser-check`, `--hide-crash-restore-bubble`, `--password-store=basic`
- `open_session(options?) -> ContextManager[BrowserContext]`

Depends: patchright.

### navigate.py
- `DEFAULT_OUT_DIR: Path` = `out`
- `@dataclass Capture` — `url`, `final_url`, `title`, `screenshot`, `html`
- `open_page(context, url, wait_until="networkidle") -> Page` — reuses the context's initial blank tab when present, so a persistent profile does not accumulate a stray about:blank tab
- `wait_for_selector(page, selector, timeout_ms=60000) -> bool` — non-raising wait
- `capture(page, url, out_dir) -> Capture` — screenshot + HTML dump
- `extract(page, selectors) -> dict[str, list[str]]` — text/value/placeholder/aria-label
- `extract_json(page, selectors) -> str`

Depends: patchright.

### credentials.py
- `DEFAULT_CRED_PATH: Path` = `cred.json`
- `@dataclass Credentials` — `email`, `password`, `imap_email?`, `imap_password?`
  - `.has_imap` — True when both IMAP fields are set
- `load_credentials(path?) -> Credentials` — raises `FileNotFoundError` / `ValueError`

### otp_mail.py
- `DEFAULT_HOST="imap.gmail.com"`, `DEFAULT_PORT=993`, `DEFAULT_SENDER_FILTER="deepseek"`, `DEFAULT_TIMEOUT_S=120`, `DEFAULT_POLL_S=5`
- `OTP_RE` — matches a standalone 6-digit code
- `class OtpMailError(RuntimeError)`
- `@dataclass MailConfig` — `email`, `app_password`, `host`, `port`, `sender_filter`
- `_connect(config) -> IMAP4_SSL` — SSL login; wraps failures as `OtpMailError`
- `_body_text(message) -> str` — flattens text parts
- `_latest_deepseek_uid(client, sender_filter) -> str | None` — newest matching sender
- `fetch_latest_otp(config, timeout_s?) -> str` — poll until a code appears; raises on timeout

Depends: stdlib only (`imaplib`, `email`, `re`, `time`). No outbound SMTP: reading needs IMAP.

### signup.py (OTP resolution)
- `prompt_for_otp(otp_override?, creds?) -> str` — order: `--otp`/`OTP` env -> IMAP fetch (`creds.has_imap`) -> terminal prompt. An IMAP failure falls back to the prompt instead of aborting.

### state.py
- `SessionState(Enum)` — `LOGGED_IN`, `NEEDS_AGE`, `NEEDS_SIGNUP`, `NEEDS_SIGNIN`, `UNKNOWN`
- Selectors: `CHAT_INPUT_SELECTOR=textarea`, `NEW_CHAT_TEXT`, `AGE_MODAL_TEXT`, `SIGNUP_FORM_SELECTOR`, `SIGNIN_FORM_SELECTOR`
- `detect_state(page) -> SessionState` — order: age > signup > signin > logged in > unknown
- `report_state(state) -> None` — prints `[state] detected=<value>`

### auth_wait.py
- `Outcome(Enum)` — `SUCCESS`, `TURNSTILE_BLOCK`, `CREDENTIAL_ERROR`, `TIMEOUT`
- `@dataclass AuthOutcome` — `outcome`, `message`, `.ok` (True only on SUCCESS)
- `class AuthError(RuntimeError)` — raised when a submit does not authenticate
- `CF_OVERLAY_SELECTOR="#cf-overlay"`, `ERROR_NODE_SELECTORS` (toast/notification/error)
- `wait_for_outcome(page, timeout_ms=45000) -> AuthOutcome` — success wins first, then Turnstile block, then visible error text
- `require_success(page, action, timeout_ms?) -> None` — raises `AuthError` unless SUCCESS

Depends: state.

### signup.py
- Selectors: `EMAIL_SELECTOR`, `PASSWORD_SELECTOR`, `CONFIRM_SELECTOR`, `CODE_SELECTOR`
- `fill_credentials(page, creds) -> None`
- `request_code(page) -> None` — clicks "Send code"
- `prompt_for_otp(otp_override?) -> str` — `--otp`, `OTP` env, or TTY prompt
- `submit_code(page, code)`, `click_signup(page)`
- `run_signup(page, creds, otp?) -> None` — fill, send code, OTP, submit, require_success, age gate

Depends: age, auth_wait, credentials.

### signin.py
- Selectors: `ACCOUNT_SELECTOR='input[placeholder="Phone number / email address"]'`, `PASSWORD_SELECTOR`, `SUBMIT_SELECTOR="div.ds-button--filled"`
- `fill_signin(page, creds) -> None`
- `click_signin(page) -> None`
- `run_signin(page, creds) -> None` — fill, submit, require_success, age gate

Depends: age, auth_wait, credentials.

### age.py
- `YEAR_MIN=1970`, `YEAR_MAX=2006`, `MONTH_MIN=1`, `MONTH_MAX=12`
- `MODAL_TEXT`, `PLACEHOLDER_SELECTOR=.ds-select__placeholder`, `OPTION_SELECTOR=.ds-select-option`, `CONFIRM_TEXT`
- `random_year(...)`, `random_month()`
- `select_option(page, label, value) -> None` — custom dropdown
- `fill_age(page, year?, month?) -> tuple[int, int]`
- `complete_age_if_present(page) -> bool` — waits for modal, fills, waits for detach

### token.py
- `USER_TOKEN_KEY="userToken"`, `DEFAULT_TOKEN_PATH=auth.json`
- `@dataclass AuthToken` — `user_token`, `path`
- `read_user_token(page) -> str | None` — unwraps `{"value": ...}` envelope
- `wait_for_user_token(page, timeout_ms=30000) -> str` — raises on timeout
- `save_user_token(token, path?) -> Path`
- `extract_user_token(page, path?) -> AuthToken`

### verify.py
- `API_BASE="https://chat.deepseek.com/api/v0"`, `USERS_CURRENT_PATH="/users/current"`, `AUTH_SCHEME="Bearer"`, `SUCCESS_BODY_CODE=0`
- `@dataclass VerifyResult` — `ok`, `status_code`, `detail`
- `_body_verdict(response) -> tuple[bool, str]` — interprets JSON; success only when `code == 0`
- `verify_token(token, base_url?) -> VerifyResult` — live only when HTTP 200 **and** body `code == 0`. DeepSeek returns `200 {"code":40003,...}` for invalid tokens, so the status line alone is not proof.
- `report_verification(result) -> None` — prints `[token] verify=VALID|INVALID status=...`

Depends: httpx.

### delete_account.py
- Selectors: `ACCOUNT_SELECTOR=div._2afd28d`, `SETTINGS_SELECTOR=div.ds-dropdown-menu-option:has-text("Settings")`, `PROFILE_TAB_SELECTOR`, `DELETE_BUTTON_SELECTOR=div[role=button].ds-button--error:has(..."Delete")`, `CONFIRM_INPUT_SELECTOR=input.ds-input__input[placeholder="DELETE MY ACCOUNT"]`, `CONFIRM_BUTTON_SELECTOR`, `DIALOG_SELECTOR=div.ds-auth-delete-account`
- `CONFIRM_PHRASE="DELETE MY ACCOUNT"`
- `DeleteOutcome(Enum)` — `AWAITING_CONFIRM`, `DELETED`, `FAILED`
- `@dataclass DeleteResult` — `outcome`, `detail`, `.ok` (True only on DELETED)
- `class DeleteError(RuntimeError)`
- `walk_to_confirm(page, timeout_ms?) -> DeleteResult` — account menu -> Settings -> Profile -> Delete, stops at dialog; types nothing
- `confirm_delete(page, timeout_ms?) -> DeleteResult` — fills the phrase, clicks confirm; only function that commits
- `run_delete(page, confirm, timeout_ms?) -> DeleteResult` — walk, then commit only when `confirm=True`

Depends: navigate.

### identity.py
- `ACCOUNT_LABEL_SELECTOR=div._9d8da05` — the masked-email label in the sidebar footer
- `SESSION_COOKIE_NAMES=("ds_session_id",)`, `SESSION_STORAGE_KEYS=("userToken",)`
- `MAX_CLEAR_ATTEMPTS=2`
- `class IdentityMismatch(AuthError)` — signed-in account differs from cred.json
- `mask_email(email) -> str` — first 2 + last 2 of local part, stars the middle, domain kept; verified against `pvnt00003@gmail.com -> pv*****03@gmail.com`
- `read_session_email(page) -> str | None` — read the visible account label
- `clear_account_session(context, page) -> None` — surgical: drops only `ds_session_id` + the account storage keys, keeps the HTTP cache
- `session_matches(page, expected_email) -> bool`
- `ensure_matching_session(context, page, expected_email) -> None` — on match, return; on mismatch, clear + reload; on unreadable label, raise (fail closed)

Depends: auth_wait, state.

### cli.py
- `DEFAULT_URL="https://chat.deepseek.com/sign_up"`, `SIGNIN_URL="https://chat.deepseek.com/sign_in"`, `CHAT_URL="https://chat.deepseek.com"`
- Per-flow default URLs: `--login` -> `SIGNIN_URL`, `--register` -> `SIGNUP_URL`, plain run -> `CHAT_URL`; an explicit positional URL overrides
- `build_parser() -> ArgumentParser`
- `_extract_and_verify(page, token_out) -> None` — extract token, verify against API
- `_identity_preflight(context, page, cred_path) -> None` — land on the authenticated root, check the signed-in account against cred.json before acting
- `_resolve_login(context, page, cred_path) -> None` — clear age, sign in, or skip if already in; retries once after an identity clear
- `_resolve_register(context, page, cred_path, otp) -> None` — sign up (or skip if already in) with auto OTP; retries once after an identity clear
- `_resolve_delete(context, page, cred_path) -> None` — bring the profile to the cred.json account before deleting; never proceeds on an unverified identity
- `run(...) -> int` — orchestration
- `main(argv?) -> int`
- Exit codes: `0` success, `1` generic error, `2` `AuthError`, `3` `DeleteError`, `4` `AgeError`, `130` interrupt

Depends: all modules above.

## CLI flags

| Flag | Effect |
| --- | --- |
| `url` (positional) | Target URL; defaults to signup page |
| `-s/--selector` | CSS selector to extract (repeatable) |
| `-o/--out` | Artifact output dir (default `out`) |
| `--wait-until` | Playwright nav wait condition |
| `-w/--wait-for` | Selector to wait for before capture |
| `--login` | Sign in (or skip if already logged in), clear age, extract + verify token |
| `--register` | Sign up with auto OTP, clear age, extract + verify token |
| `--token-out` | Token output path (default `auth.json`) |
| `--delete-account` | Walk Settings -> Profile -> Delete, stop at the confirmation dialog |
| `--confirm-delete` | With `--delete-account`, type the phrase and commit (**irreversible**) |
| `--cred` | Credentials path (default `cred.json`) |
| `--otp` | OTP override for signup |

## Data files (git-ignored)

- `cred.json` — email, password, optional imap_email + imap_password
- `auth.json` — `{"userToken": "..."}`
- `cred.example.json` — tracked template with the IMAP fields documented

## Verification commands

```bash
uv run ruff format . && uv run ruff check . && uv run ruff format --check .
uv run deepseek-forge --login
uv run deepseek-forge --register
uv run deepseek-forge --delete-account          # safe dry run
uv run deepseek-forge --delete-account --confirm-delete   # irreversible
```

## External coupling

- DeepSeek selectors are hashed/stable class names (`ds-button`, `ds-select`, `ds-input`). Changes on their side break flows.
- `userToken` lives in `localStorage` under a `{"value": ...}` envelope.
- Token verification hits `GET /api/v0/users/current`. A valid token answers `200 {"code":0,...}`; an invalid one answers `200 {"code":40003,"msg":"Authorization Failed (invalid token)"}`. The verifier must read the body.
- The account control is a `tabindex` div (`div._2afd28d`), not a button. Settings menu items use `ds-dropdown-menu-option__label`.
- Account deletion requires typing the exact phrase `DELETE MY ACCOUNT` into `input.ds-input__input` and clicking `Confirm delete my account`.
- Sign-in and signup submits are gated by Cloudflare Turnstile (`#cf-overlay`). On a cold profile the submit can be held before the credential check runs; `auth_wait` reports this as `turnstile_block` rather than a credential failure.
