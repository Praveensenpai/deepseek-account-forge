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
    counter: int | None = None
    gateway_url: str = ""
    gateway_key: str = ""

    @property
    def has_imap(self) -> bool:
        """True when IMAP credentials are present for OTP retrieval."""
        return bool(self.imap_email and self.imap_password)

    def resolve_email(self, index: int | None = None) -> str:
        """Return the effective email for a specific index or counter.

        If an index or counter is present, appends +{index} to the base local part.
        Otherwise returns email unchanged.
        """
        target_idx = index if index is not None else self.counter
        if target_idx is None:
            return self.email

        local, sep, domain = self.email.partition("@")
        if not sep:
            return self.email

        base_local = local.split("+")[0]
        return f"{base_local}+{target_idx}@{domain}"

    def with_resolved_email(self, index: int | None = None) -> Credentials:
        """Return a new Credentials instance with the effective email resolved."""
        return Credentials(
            email=self.resolve_email(index),
            password=self.password,
            imap_email=self.imap_email,
            imap_password=self.imap_password,
            counter=self.counter,
            gateway_url=self.gateway_url,
            gateway_key=self.gateway_key,
        )


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
    imap_email = str(raw.get("imap_email", "")).strip()
    imap_password = str(raw.get("imap_password", "")).strip()
    raw_counter = raw.get("counter")
    counter = int(raw_counter) if raw_counter is not None else None
    gateway_url = str(raw.get("gateway_url", "")).strip()
    gateway_key = str(raw.get("gateway_key", "")).strip()
    if not email or not password:
        raise ValueError(f"{path}: 'email' and 'password' are required")
    return Credentials(
        email=email,
        password=password,
        imap_email=imap_email,
        imap_password=imap_password,
        counter=counter,
        gateway_url=gateway_url,
        gateway_key=gateway_key,
    )


def increment_counter(path: Path = DEFAULT_CRED_PATH) -> int:
    """Increment the counter field in cred.json by 1 and return the new value."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    current = int(raw.get("counter", 10))
    next_val = current + 1
    raw["counter"] = next_val
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return next_val
