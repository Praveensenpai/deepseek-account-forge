"""Track DeepSeek B11 risk-device cooldowns and warn on premature registration."""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_STATE_PATH = Path.home() / ".local" / "share" / "deepseek-account-forge" / "b11_state.json"
DEFAULT_COOLDOWN_MINUTES = 45.0


def record_b11(
    timestamp: datetime | None = None,
    path: Path = DEFAULT_STATE_PATH,
) -> None:
    """Record a B11 error timestamp to persistent state."""
    ts = timestamp or datetime.now(UTC)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"last_b11_at": ts.isoformat()}
    try:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"[cooldown] failed to record B11 state: {exc}")


def clear_b11(path: Path = DEFAULT_STATE_PATH) -> None:
    """Clear recorded B11 state upon successful authentication."""
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def get_last_b11(path: Path = DEFAULT_STATE_PATH) -> datetime | None:
    """Read the last B11 timestamp if recorded."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("last_b11_at")
        if not raw:
            return None
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def check_b11_cooldown(
    force: bool = False,
    cooldown_minutes: float = DEFAULT_COOLDOWN_MINUTES,
    path: Path = DEFAULT_STATE_PATH,
) -> bool:
    """Check elapsed time since last B11 error and prompt if still in cooldown.

    Returns True if execution should proceed, False if aborted.
    """
    last_b11 = get_last_b11(path)
    if last_b11 is None:
        return True

    now = datetime.now(UTC)
    elapsed_minutes = (now - last_b11).total_seconds() / 60.0
    if elapsed_minutes < 0:
        return True

    if elapsed_minutes >= cooldown_minutes:
        print(
            f"[cooldown] last B11 error was {elapsed_minutes:.1f} mins ago "
            f"(cooldown of {cooldown_minutes:.0f}m has expired)"
        )
        return True

    remaining = cooldown_minutes - elapsed_minutes
    print(
        f"[cooldown] WARNING: Last B11 (RISK_DEVICE_DETECTED) occurred "
        f"{elapsed_minutes:.1f} mins ago ({remaining:.1f}m remaining in recommended 45m cooldown)."
    )
    print("[cooldown] Proceeding now may fail and reset your cooldown window.")

    if force:
        print("[cooldown] --yes specified; proceeding despite cooldown")
        return True

    try:
        answer = input("[cooldown] Do you still want to proceed? [y/N]: ").strip().lower()
    except EOFError:
        print("[cooldown] non-interactive session without --yes; aborting")
        return False

    return answer in ("y", "yes")
