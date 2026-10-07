"""Verify a DeepSeek userToken against the live API.

A cached localStorage value proves nothing on its own. The only honest test is
an authenticated request whose *body* confirms success. DeepSeek returns HTTP
200 with an error payload (``code: 40003``) for invalid tokens, so the status
line alone is not proof.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from http import HTTPStatus

import httpx

API_BASE = "https://chat.deepseek.com/api/v0"
USERS_CURRENT_PATH = "/users/current"
AUTH_HEADER = "Authorization"
AUTH_SCHEME = "Bearer"
VERIFY_TIMEOUT_S = 20.0
SUCCESS_BODY_CODE = 0


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of a token verification request."""

    ok: bool
    status_code: int
    detail: str


def _body_verdict(response: httpx.Response) -> tuple[bool, str]:
    """Interpret the JSON body. DeepSeek signals failure inside a 200 response."""
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return False, "response body was not JSON"
    if not isinstance(payload, dict):
        return False, "unexpected response shape"
    code = payload.get("code")
    if code == SUCCESS_BODY_CODE:
        return True, "token is live"
    message = str(payload.get("msg") or "rejected")
    return False, f"api rejected token (code={code}: {message})"


def verify_token(token: str, base_url: str = API_BASE) -> VerifyResult:
    """Make one read-only authenticated request to confirm the token works.

    The token is live only when the request succeeds *and* the JSON body reports
    success. A non-200 status is reported as-is rather than guessed at.
    """
    url = f"{base_url.rstrip('/')}{USERS_CURRENT_PATH}"
    headers = {AUTH_HEADER: f"{AUTH_SCHEME} {token}"}
    try:
        response = httpx.get(url, headers=headers, timeout=VERIFY_TIMEOUT_S)
    except httpx.HTTPError as exc:
        return VerifyResult(ok=False, status_code=0, detail=f"request failed: {exc}")
    if response.status_code != HTTPStatus.OK:
        detail = f"rejected with HTTP {response.status_code}"
        return VerifyResult(ok=False, status_code=response.status_code, detail=detail)
    ok, detail = _body_verdict(response)
    return VerifyResult(ok=ok, status_code=response.status_code, detail=detail)


def report_verification(result: VerifyResult) -> None:
    """Print the verification outcome in a stable, greppable format."""
    verdict = "VALID" if result.ok else "INVALID"
    print(f"[token] verify={verdict} status={result.status_code} ({result.detail})")
