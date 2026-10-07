"""Load and validate signup credentials from a JSON file."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CRED_PATH = Path("cred.json")


@dataclass(frozen=True)
class Credentials:
    """Signup credentials read from disk."""

    email: str
    password: str
    imap_email: str = ""
    imap_password: str = ""

    @property
    def has_imap(self) -> bool:
        """True when IMAP credentials are present for OTP retrieval."""
        return bool(self.imap_email and self.imap_password)


def load_credentials(path: Path = DEFAULT_CRED_PATH) -> Credentials:
    """Read and validate credentials from a JSON file.

    Raises FileNotFoundError if the file is missing, ValueError if required
    fields are blank.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"credential file not found: {path} (copy cred.example.json to cred.json)"
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    email = str(raw.get("email", "")).strip()
    password = str(raw.get("password", ""))
    # IMAP is optional; when both fields are set, signup can fetch the OTP itself.
    imap_email = str(raw.get("imap_email", "")).strip()
    imap_password = str(raw.get("imap_password", "")).strip()
    if not email or not password:
        raise ValueError(f"{path}: 'email' and 'password' are required")
    return Credentials(
        email=email,
        password=password,
        imap_email=imap_email,
        imap_password=imap_password,
    )
