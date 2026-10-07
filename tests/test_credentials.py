"""Unit tests for credential loading and validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deepseek_account_forge.credentials import Credentials, load_credentials


def _write(tmp_path: Path, payload: dict[str, object]) -> Path:
    """Write a credential file and return its path."""
    path = tmp_path / "cred.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_missing_file_raises_filenotfound(tmp_path: Path) -> None:
    """A missing credential file is a clear FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_credentials(tmp_path / "nope.json")


def test_valid_credentials_load(tmp_path: Path) -> None:
    """Email and password load as given."""
    path = _write(tmp_path, {"email": "a@b.com", "password": "pw"})
    creds = load_credentials(path)
    assert creds == Credentials(email="a@b.com", password="pw")


def test_legacy_confirm_password_is_ignored(tmp_path: Path) -> None:
    """An old cred.json with confirm_password still loads; the field is dropped."""
    path = _write(tmp_path, {"email": "a@b.com", "password": "pw", "confirm_password": "pw"})
    creds = load_credentials(path)
    assert creds.password == "pw"
    assert not hasattr(creds, "confirm_password")


def test_email_is_trimmed(tmp_path: Path) -> None:
    """Surrounding whitespace on the email is stripped."""
    path = _write(tmp_path, {"email": "  a@b.com  ", "password": "pw"})
    assert load_credentials(path).email == "a@b.com"


@pytest.mark.parametrize("payload", [{"password": "pw"}, {"email": "a@b.com"}, {}])
def test_missing_required_fields_raise_valueerror(
    tmp_path: Path, payload: dict[str, object]
) -> None:
    """A blank email or password is rejected."""
    path = _write(tmp_path, payload)
    with pytest.raises(ValueError):
        load_credentials(path)
