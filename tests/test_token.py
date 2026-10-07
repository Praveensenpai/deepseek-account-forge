"""Unit tests for userToken extraction and envelope unwrapping."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deepseek_account_forge.token import (
    read_user_token,
    save_user_token,
    wait_for_user_token,
)


class FakePage:
    """Minimal stand-in for a Playwright Page, scripted per test."""

    def __init__(self, evaluate_values: list[Any] | Any) -> None:
        """Store the value(s) that evaluate() should return in order."""
        self._values = evaluate_values if isinstance(evaluate_values, list) else [evaluate_values]
        self._index = 0
        self.waits = 0

    def evaluate(self, _script: str) -> Any:
        """Return the next scripted value, repeating the last one."""
        value = self._values[min(self._index, len(self._values) - 1)]
        self._index += 1
        return value

    def wait_for_timeout(self, _ms: int) -> None:
        """Count poll waits without sleeping."""
        self.waits += 1


def test_missing_token_returns_none() -> None:
    """No stored value yields None."""
    assert read_user_token(FakePage(None)) is None  # type: ignore[arg-type]


def test_envelope_is_unwrapped() -> None:
    """The {"value": ...} envelope is unwrapped to the bare token."""
    page = FakePage(json.dumps({"value": "abc123", "__version": "0"}))
    assert read_user_token(page) is not None  # type: ignore[arg-type]


def test_envelope_unwrap_value() -> None:
    """The unwrapped value is exactly the inner token string."""
    page = FakePage(json.dumps({"value": "abc123"}))
    assert read_user_token(page) == "abc123"  # type: ignore[arg-type]


def test_plain_string_passthrough() -> None:
    """A non-JSON stored value is returned as-is."""
    assert read_user_token(FakePage("raw-token")) == "raw-token"  # type: ignore[arg-type]


def test_json_without_value_returns_raw() -> None:
    """Valid JSON lacking a value key is returned unmodified."""
    raw = json.dumps({"other": 1})
    assert read_user_token(FakePage(raw)) == raw  # type: ignore[arg-type]


def test_wait_returns_once_token_appears() -> None:
    """Polling returns as soon as a token is present."""
    page = FakePage([None, None, json.dumps({"value": "late"})])
    assert wait_for_user_token(page, timeout_ms=10_000) == "late"  # type: ignore[arg-type]
    assert page.waits == 2


def test_wait_times_out_with_clear_error() -> None:
    """Persistent absence raises RuntimeError rather than returning None."""
    page = FakePage(None)
    with pytest.raises(RuntimeError, match="userToken not found"):
        wait_for_user_token(page, timeout_ms=1_000)  # type: ignore[arg-type]


def test_save_writes_single_key(tmp_path: Path) -> None:
    """The saved file contains exactly a userToken key."""
    path = save_user_token("tok", tmp_path / "auth.json")
    assert json.loads(path.read_text(encoding="utf-8")) == {"userToken": "tok"}


def test_save_creates_parent_dir(tmp_path: Path) -> None:
    """Nested output paths are created."""
    path = save_user_token("tok", tmp_path / "nested" / "auth.json")
    assert path.exists()
