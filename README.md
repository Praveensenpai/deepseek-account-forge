# DeepSeek Account Forge

Full account lifecycle automation for `chat.deepseek.com`, built on [Patchright](https://github.com/KaliVinyzu/patchright-python) — a patched Playwright that removes CDP/runtime leaks. Handles sign up, sign in, the age-verification gate, token extract + verify, and account deletion, with an identity guard that refuses to act on the wrong account.

## Why

Vanilla Playwright leaks fingerprints (`navigator.webdriver`, CDP artifacts, headless UA mismatches). DeepSeek sits behind a Cloudflare-style bot check, so a stealth launch is the baseline. On top of that, the flow is a client-rendered SPA with custom dropdowns and an age gate — all handled here.

## Flow

```
open page
   │
   ├─ detect state ──► logged in? ──► extract + verify token ──► auth.json
   │                      │
   │                      ├─ age modal? ──► random year 1970-2006 + month ──► confirm
   │                      │
   │                      ├─ sign-in form? ──► email + password ──► submit
   │                      │
   │                      └─ signup form? ──► email + password ──► send code
   │                                             │
   │                                             └─ OTP from IMAP or terminal ──► submit
   ├─ delete-account? ──► menu → Settings → Profile → Delete
   │                          │
   │                          └─ --confirm-delete? ──► type phrase + confirm
   └─ capture screenshot + HTML to out/
```

## Install

```bash
uv sync
uv run patchright install chrome
```

## Setup

Copy the credential template and fill it in:

```bash
cp cred.example.json cred.json
```

`cred.json` (git-ignored):

```json
{
  "email": "you@example.com",
  "password": "your-password",
  "imap_email": "your-inbox@gmail.com",
  "imap_password": "your-16-char-app-password"
}
```

The signup form's confirm-password box is filled from `password`; it is not a separate field.

The `imap_*` fields are optional. When both are set, `--register` fetches the OTP from that Gmail inbox over IMAP instead of prompting you in the terminal.

### Gmail App Password

Gmail blocks plain-password IMAP. To read the OTP inbox you need an App Password:

1. Enable 2-Step Verification on the Google account.
2. Go to https://myaccount.google.com/apppasswords
3. Create an app password for "Mail" and copy the 16-character code.
4. Put it in `cred.json` as `imap_password` (spaces are fine, or strip them).

If `imap_email`/`imap_password` are absent, signup falls back to the terminal prompt — nothing breaks.

## Usage

```bash
# Sign in (or skip if already logged in), clear age, extract + verify token
uv run deepseek-forge --login

# Sign up: fill creds, auto OTP from Gmail, submit, clear age, verify token
uv run deepseek-forge --register

# Delete flow, safe mode: walk to the confirmation dialog and stop
uv run deepseek-forge --delete-account

# Delete flow, commit: type the phrase and delete the account (irreversible)
uv run deepseek-forge --delete-account --confirm-delete

# Generic mode: open a URL and extract CSS selector text
uv run deepseek-forge https://example.com -s "h1" -s "a"
```

Non-interactive OTP (grab the code from email first):

```bash
uv run deepseek-forge --register --otp 123456
```

Headless:

```bash
HEADLESS=1 uv run deepseek-forge --login
```

## Flags

| Flag | Effect |
| --- | --- |
| `--login` | Sign in, or skip if already logged in; clear age; extract + verify token |
| `--register` | Sign up with auto OTP; clear age; extract + verify token |
| `--token-out` | Token output path (default `auth.json`) |
| `--delete-account` | Walk Settings -> Profile -> Delete and stop at the confirmation dialog |
| `--confirm-delete` | With `--delete-account`, type the phrase and commit (**irreversible**) |
| `--cred` | Credentials path (default `cred.json`) |
| `--otp` | OTP for non-interactive signup |
| `-s/--selector` | CSS selector to extract (repeatable) |
| `-w/--wait-for` | Selector to wait for before capture |
| `--wait-until` | Playwright nav wait condition |
| `-o/--out` | Artifact output dir (default `out`) |

## Output

- `out/<slug>.png` — full-page screenshot
- `out/<slug>.html` — rendered DOM dump
- `auth.json` — `{"userToken": "..."}` (git-ignored)

## Config

| Env var | Effect |
| --- | --- |
| `HEADLESS` | `1`/`true` for headless |
| `STEALTH_PROFILE` | Override persistent profile dir |
| `OTP` | OTP code for non-interactive signup (highest priority) |

## Failure handling

A submit is never treated as success on its own. After clicking sign-in or signup, `auth_wait.py` watches for one of four outcomes:

| Outcome | Signal |
| --- | --- |
| `success` | session state becomes `LOGGED_IN` |
| `turnstile_block` | Cloudflare Turnstile overlay (`#cf-overlay`) becomes visible |
| `credential_error` | a visible error node appears; its text is reported as-is |
| `timeout` | nothing resolved within 45s |

Wrong email/password, a duplicate signup email, a bad OTP, and a Turnstile block all fail loudly instead of printing a fake success. Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | success |
| `1` | generic error |
| `2` | auth failed (`AuthError`) |
| `3` | delete failed (`DeleteError`) |
| `130` | interrupted |

On a cold browser profile, Cloudflare Turnstile can hold the login request before the credential check runs. That surfaces as `turnstile_block`, not a credential failure — the login genuinely did not happen.

## Account identity guard

A destructive flag must never run against the wrong account. Before `--login`, `--register`, or `--delete-account` act, the tool reads the masked email in the sidebar (`pv*****03@gmail.com`) and compares it to the mask of `cred.json`'s email.

The mask rule: keep the first two and last two characters of the local part, star the middle, keep the domain.

| cred.json | page mask |
| --- | --- |
| `pvnt00003@gmail.com` | `pv*****03@gmail.com` |

On mismatch the tool clears **only the account session** — the `ds_session_id` cookie and the `userToken`/`*_userStorage` localStorage keys — then reloads and retries the flow. It never calls the app's logout button, so the server-side token stays valid for other apps. The HTTP cache (JS/CSS/images) is left intact, so repeat runs stay fast.

If the page is logged in but the account label cannot be read, the tool fails closed (`IdentityMismatch`, exit `2`) rather than acting on an unverified account.

## OTP retrieval (IMAP)

Signup needs a 6-digit code that DeepSeek emails you. By default you type it at the terminal. To remove that step, add IMAP credentials to `cred.json` and the tool reads the code from your inbox itself.

Order of resolution in `signup.prompt_for_otp`:

1. `--otp <code>` or the `OTP` env var — used as-is.
2. `imap_email` + `imap_password` in `cred.json` — connect to `imap.gmail.com:993` over SSL, find the newest message from a sender matching `deepseek`, pull the first standalone 6-digit number.
3. Terminal prompt — the fallback, and what runs when IMAP is not configured.

If an IMAP fetch fails (bad App Password, timeout, no mail), the flow prints the reason and falls back to the prompt rather than aborting.

SMTP is not used and cannot be: SMTP only sends mail, reading an inbox requires IMAP.

## Token verification

`--login` and `--register` are self-contained: each authenticates, clears the age modal if it appears, then extracts and verifies the token. The check reads the **JSON body**, not just the status line. The token is live only when the response is `200 {"code":0,...}`.

This matters because DeepSeek answers `200 {"code":40003,"msg":"Authorization Failed (invalid token)"}` for a dead token — a 200 that is not success. The verifier rejects it.

`userToken` is a live credential. It's git-ignored; never commit it or paste it in chat. Log out of DeepSeek to invalidate a leaked token.

## Account deletion

Irreversible. The flow is split so a stray command cannot delete anything:

```bash
# Safe: opens account menu -> Settings -> Profile -> Delete, stops at the dialog
uv run deepseek-forge --delete-account

# Commit: types DELETE MY ACCOUNT and clicks through
uv run deepseek-forge --delete-account --confirm-delete
```

`--delete-account` alone never types the phrase and never clicks confirm. Proof it worked: after a real deletion the token dies — a `--login` run reports no session, and the API answers `code:40003`.

## Verify

```bash
uv run ruff format . && uv run ruff check . && uv run ruff format --check .
uv run pytest -q          # 69 unit tests, offline
uv run deepseek-forge --login
```

`pytest` runs offline by default; the one browser integration test is marked `integration` and deselected. Run it with `uv run pytest -m integration`.

## Architecture

See [CODEBASE.md](CODEBASE.md) for the module-by-module symbol index.

- `browser.py` — stealth launch + persistent profile
- `navigate.py` — open, capture, extract
- `state.py` — session-state detection
- `auth_wait.py` — post-submit outcome classification
- `signup.py` / `signin.py` — auth flows
- `age.py` — age-verification modal
- `token.py` / `verify.py` — token extraction + API verification
- `otp_mail.py` — IMAP OTP retrieval from a Gmail inbox
- `delete_account.py` — Settings -> Profile -> Delete (safe walk + gated commit)
- `credentials.py` — `cred.json` loader
- `cli.py` — orchestration
