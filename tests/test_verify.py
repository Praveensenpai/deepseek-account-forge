"""Unit tests for token API verification.

The verifier must not trust the HTTP status alone: DeepSeek answers 200 with an
error body for invalid tokens, so these tests pin both the status check and the
JSON body check.
"""

from __future__ import annotations

import httpx
import pytest

from deepseek_account_forge.verify import VerifyResult, verify_token


class FakeResponse:
    """Minimal httpx.Response stand-in with a status code and JSON body."""

    def __init__(self, status_code: int, payload: object = None) -> None:
        """Store the status code and the payload json() should return."""
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        """Return the scripted payload, or raise for a non-JSON body."""
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _patch_get(monkeypatch: pytest.MonkeyPatch, result: object) -> dict[str, object]:
    """Replace httpx.get with a stub that records the call and returns result.

    Returns a dict capturing the url, headers, and timeout the code under test
    passed. When result is an Exception instance, the stub raises it instead.
    """
    captured: dict[str, object] = {}

    def fake_get(
        url: object,
        *,
        headers: object = None,
        timeout: object = None,
        **_kw: object,
    ) -> object:
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(httpx, "get", fake_get)
    return captured


def test_200_with_success_body_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 200 plus a success code marks the token live."""
    _patch_get(monkeypatch, FakeResponse(200, {"code": 0, "data": {"id": "x"}}))
    result = verify_token("tok")
    assert result.ok is True
    assert result.status_code == 200


def test_200_with_invalid_token_code_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact false positive: HTTP 200 but code 40003 must be invalid."""
    payload = {"code": 40003, "msg": "Authorization Failed (invalid token)", "data": None}
    _patch_get(monkeypatch, FakeResponse(200, payload))
    result = verify_token("garbage")
    assert result.ok is False
    assert result.status_code == 200
    assert "40003" in result.detail


def test_200_with_non_json_body_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 200 whose body is not JSON cannot be trusted as valid."""
    _patch_get(monkeypatch, FakeResponse(200, None))
    result = verify_token("tok")
    assert result.ok is False
    assert "not JSON" in result.detail


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_status_is_invalid(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    """401 and 403 mark the token invalid before the body is even read."""
    _patch_get(monkeypatch, FakeResponse(status, {"code": 0}))
    result = verify_token("tok")
    assert result.ok is False
    assert result.status_code == status


def test_bearer_header_and_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """The request uses a Bearer header against the users endpoint."""
    captured = _patch_get(monkeypatch, FakeResponse(200, {"code": 0}))
    verify_token("secret")
    assert captured["headers"] == {"Authorization": "Bearer secret"}
    assert str(captured["url"]).endswith("/users/current")


def test_network_error_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transport error becomes a failed result, not an exception."""
    _patch_get(monkeypatch, httpx.ConnectError("boom"))
    result = verify_token("tok")
    assert result.ok is False
    assert result.status_code == 0
    assert "request failed" in result.detail


def test_result_dataclass_is_frozen() -> None:
    """VerifyResult is immutable."""
    result = VerifyResult(ok=True, status_code=200, detail="ok")
    with pytest.raises(AttributeError):
        result.ok = False  # type: ignore[misc]
