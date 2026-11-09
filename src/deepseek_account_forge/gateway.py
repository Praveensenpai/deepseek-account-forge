"""Push extracted auth tokens to the local deeperseeker-rs admin token pool."""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_GATEWAY_URL = os.environ.get(
    "DEEPSEEKER_GATEWAY_URL", "http://127.0.0.1:4000/api/admin/tokens"
)
DEFAULT_GATEWAY_KEY = os.environ.get("DEEPSEEKER_API_KEY", "dseeker")
DEFAULT_TIMEOUT_S = 10.0


def push_token_to_gateway(
    token: str,
    alias: str,
    url: str = DEFAULT_GATEWAY_URL,
    api_key: str = DEFAULT_GATEWAY_KEY,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any] | None:
    """Register an auth token with the deeperseeker-rs gateway.

    Sends a POST request to /api/admin/tokens with Authorization: Bearer <key>.
    If the token is already present in the database, updates its alias and ensures
    its status is ACTIVE.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "auth_token": token.strip(),
        "alias": alias.strip(),
    }
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=timeout_s)
        if response.status_code == 200:
            data = response.json()
            token_meta = data.get("token", {})
            token_id = token_meta.get("id", "unknown")
            masked = token_meta.get("masked_token", "")
            print(
                f"[gateway] token registered in pool: alias='{alias}' id={token_id} masked={masked}"
            )
            return data

        # If it failed because token is already in the database, update its alias and activate it
        if response.status_code == 400 and "Failed to insert token" in response.text:
            list_resp = httpx.get(url, headers=headers, timeout=timeout_s)
            if list_resp.status_code == 200:
                for t in list_resp.json().get("tokens", []):
                    prefix = t.get("masked_token", "")[:8]
                    if t.get("alias") == alias or (prefix and token.startswith(prefix)):
                        t_id = t["id"]
                        patch_url = url.rstrip("/") + f"/{t_id}"
                        httpx.patch(
                            patch_url,
                            headers=headers,
                            json={"alias": alias},
                            timeout=timeout_s,
                        )
                        httpx.post(
                            f"{patch_url}/status",
                            headers=headers,
                            json={"status": "ACTIVE"},
                            timeout=timeout_s,
                        )
                        print(
                            f"[gateway] existing token updated and activated: "
                            f"alias='{alias}' id={t_id}"
                        )
                        return {"status": "ok", "message": "Token updated", "token": t}

        print(f"[gateway] warning: gateway answered HTTP {response.status_code}: {response.text}")
        return None
    except Exception as exc:
        print(f"[gateway] warning: could not reach gateway at {url}: {exc}")
        return None
