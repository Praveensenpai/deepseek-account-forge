"""Extract the DeepSeek auth token from an authenticated browser session."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from patchright.sync_api import Page

USER_TOKEN_KEY = "userToken"
DEFAULT_TOKEN_PATH = Path("auth.json")
READ_TOKEN_JS = f"() => window.localStorage.getItem({USER_TOKEN_KEY!r})"


@dataclass(frozen=True)
class AuthToken:
    """The extracted auth token."""

    user_token: str
    path: Path


def read_user_token(page: Page) -> str | None:
    """Return the raw userToken string, or None when absent.

    DeepSeek stores the token as a JSON envelope: {"value": "<token>", ...}.
    Unwrap it so callers get the bare token.
    """
    raw = page.evaluate(READ_TOKEN_JS)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(parsed, dict) and "value" in parsed:
        value = parsed["value"]
        return value if isinstance(value, str) else json.dumps(value)
    return raw


def wait_for_user_token(page: Page, timeout_ms: int = 30_000) -> str:
    """Poll localStorage until userToken appears, then return it.

    Raises RuntimeError on timeout so the caller sees a clear failure instead
    of a silent None.
    """
    deadline_ms = timeout_ms
    step_ms = 500
    waited = 0
    while waited < deadline_ms:
        token = read_user_token(page)
        if token:
            return token
        page.wait_for_timeout(step_ms)
        waited += step_ms
    raise RuntimeError(f"userToken not found after {timeout_ms} ms; is the session logged in?")


def save_user_token(token: str, path: Path = DEFAULT_TOKEN_PATH) -> Path:
    """Write the token to a JSON file and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"userToken": token}, indent=2), encoding="utf-8")
    return path


def extract_user_token(page: Page, path: Path = DEFAULT_TOKEN_PATH) -> AuthToken:
    """Read the userToken and save it. Returns the token and output path."""
    token = wait_for_user_token(page)
    saved = save_user_token(token, path)
    print(f"[token] saved userToken (len={len(token)}) to {saved}")
    return AuthToken(user_token=token, path=saved)
