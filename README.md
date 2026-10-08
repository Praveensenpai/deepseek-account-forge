# DeepSeek Account Forge

Create and manage DeepSeek accounts from your terminal.

## What it does

- **Create an account** — fills the signup form, grabs the email code, and finishes signup.
- **Log in** — signs in and saves your access token to `auth.json`.
- **Delete an account** — walks to the delete dialog, with an optional flag to actually confirm.

Everything is automatic except the signup captcha, which you solve once in the browser.

## Install

```bash
git clone https://github.com/Praveensenpai/deepseek-account-forge.git
cd deepseek-account-forge
uv sync
uv run patchright install chrome
```

## Setup

Copy the template and fill in your details:

```bash
cp cred.example.json cred.json
```

`cred.json` (never committed):

```json
{
  "email": "you@example.com",
  "password": "your-password",
  "imap_email": "your-inbox@gmail.com",
  "imap_password": "your-16-char-app-password"
}
```

`imap_email` and `imap_password` are optional. Add them if you want the tool to read the signup code from your Gmail inbox automatically. Without them, you type the code in yourself.

To get a Gmail App Password: turn on 2-Step Verification, then create one at https://myaccount.google.com/apppasswords.

## Captcha

Creating an account needs one manual step: when the hCaptcha appears, solve it in the browser window yourself. The tool waits for you to finish, then continues. Everything else (form, email code, age gate, token) is automatic.

## Usage

```bash
# Create a new account
uv run deepseek-forge --register

# Log in and save the token
uv run deepseek-forge --login

# Start deleting an account (stops at the confirmation dialog)
uv run deepseek-forge --delete-account

# Actually delete (irreversible)
uv run deepseek-forge --delete-account --confirm-delete
```

Run it without a visible browser:

```bash
HEADLESS=1 uv run deepseek-forge --login
```

## Flags

| Flag | What it does |
| --- | --- |
| `--register` | Create a new account |
| `--login` | Log in and save the token |
| `--delete-account` | Walk to the delete dialog and stop |
| `--confirm-delete` | With `--delete-account`, confirm the deletion (**irreversible**) |
| `--token-out` | Where to save the token (default `auth.json`) |
| `--cred` | Credentials file (default `cred.json`) |
| `--otp` | Signup code, if you already have it |

## Files

- `auth.json` — your saved token. Keep it private.
- `out/` — screenshots and page dumps from each run.

## Safety

Before logging in, registering, or deleting, the tool checks that the signed-in account matches the email in `cred.json`. If it doesn't match, it clears the session and stops instead of touching the wrong account.

The delete command only deletes when you pass `--confirm-delete`. A plain `--delete-account` just opens the dialog.