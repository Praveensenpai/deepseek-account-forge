"""Patchright launch helpers with ephemeral or persistent stealth profile."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from patchright.sync_api import BrowserContext, Playwright, sync_playwright

DEFAULT_USER_DATA_DIR = Path.home() / ".local" / "share" / "deepseek-account-forge" / "profile"
DEFAULT_TIMEOUT_MS = 60_000
DEFAULT_VIEWPORT = {"width": 1280, "height": 900}


def prune_stale_temp_profiles() -> None:
    """Remove any orphaned deepseek-forge temporary directories in /tmp."""
    temp_dir = Path(tempfile.gettempdir())
    for path in temp_dir.glob("deepseek-forge-*"):
        if path.is_dir():
            with contextlib.suppress(Exception):
                shutil.rmtree(path, ignore_errors=True)


@dataclass(frozen=True)
class LaunchOptions:
    """Configuration for a stealth browser session."""

    headless: bool = False
    user_data_dir: Path | None = None
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    locale: str | None = None
    timezone: str | None = None

    @classmethod
    def from_env(cls, profile: Path | None = None) -> LaunchOptions:
        """Build options from CLI flags and environment variables.

        If profile is provided or STEALTH_PROFILE is set, persists to that directory.
        Otherwise defaults to None, provisioning a clean ephemeral directory.
        Timezone and locale default to None to inherit host OS settings matching the IP.
        """
        headless = os.environ.get("HEADLESS", "").lower() in {"1", "true", "yes"}
        env_profile = os.environ.get("STEALTH_PROFILE")
        target_dir: Path | None = None
        if profile is not None:
            target_dir = profile.expanduser()
        elif env_profile:
            target_dir = Path(env_profile).expanduser()
        locale = os.environ.get("LOCALE") or None
        timezone = os.environ.get("TIMEZONE") or None
        return cls(headless=headless, user_data_dir=target_dir, locale=locale, timezone=timezone)


def _sanitize_preferences(user_data_dir: Path) -> None:
    """Patch Chrome prefs that trigger first-run and restore prompts.

    Chrome rewrites Preferences on exit, so a fresh or abruptly-closed profile
    shows the restore bubble, the save-password prompt, and the default-browser
    check on the next launch. Patching the file before launch keeps the window
    quiet. Failures are non-fatal: a missing or unreadable file is skipped.
    """
    prefs_path = user_data_dir / "Default" / "Preferences"
    if not prefs_path.exists():
        return
    try:
        prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    prefs.setdefault("profile", {}).update(
        {
            "exit_type": "Normal",
            "exited_cleanly": True,
            "password_manager_enabled": False,
        }
    )
    prefs["credentials_enable_service"] = False
    prefs.setdefault("browser", {}).update(
        {
            "has_seen_welcome_page": True,
            "check_default_browser": False,
        }
    )
    prefs_path.write_text(json.dumps(prefs), encoding="utf-8")


def launch_context(playwright: Playwright, options: LaunchOptions) -> BrowserContext:
    """Launch a Chromium context tuned for stealth."""
    assert options.user_data_dir is not None
    options.user_data_dir.mkdir(parents=True, exist_ok=True)
    _sanitize_preferences(options.user_data_dir)
    context_kwargs: dict[str, object] = {
        "user_data_dir": str(options.user_data_dir),
        "headless": options.headless,
        "channel": "chrome",
        "viewport": DEFAULT_VIEWPORT,
        "ignore_default_args": ["--enable-automation"],
        "args": [
            "--disable-blink-features=AutomationControlled",
            f"--window-size={DEFAULT_VIEWPORT['width']},{DEFAULT_VIEWPORT['height']}",
            "--no-first-run",
            "--no-default-browser-check",
            "--hide-crash-restore-bubble",
            "--password-store=basic",
        ],
    }
    if options.locale is not None:
        context_kwargs["locale"] = options.locale
    if options.timezone is not None:
        context_kwargs["timezone_id"] = options.timezone

    context = playwright.chromium.launch_persistent_context(**context_kwargs)  # type: ignore[arg-type]
    context.set_default_timeout(options.timeout_ms)
    return context


def open_session(options: LaunchOptions | None = None):
    """Context manager yielding a stealth browser context.

    Yields the context; the caller opens pages. Automatically prunes old temp
    dirs on startup and destroys ephemeral profiles on exit unless an explicit
    user_data_dir was specified.
    """
    opts = options or LaunchOptions.from_env()

    class _Session:
        def __init__(self) -> None:
            self._pw: Playwright | None = None
            self._ctx: BrowserContext | None = None
            self._temp_dir: tempfile.TemporaryDirectory[str] | None = None

        def __enter__(self) -> BrowserContext:
            prune_stale_temp_profiles()
            if opts.user_data_dir is not None:
                effective_dir = opts.user_data_dir
            else:
                self._temp_dir = tempfile.TemporaryDirectory(
                    prefix="deepseek-forge-", ignore_cleanup_errors=True
                )
                effective_dir = Path(self._temp_dir.name)

            effective_opts = LaunchOptions(
                headless=opts.headless,
                user_data_dir=effective_dir,
                timeout_ms=opts.timeout_ms,
                locale=opts.locale,
                timezone=opts.timezone,
            )
            self._pw = sync_playwright().start()
            self._ctx = launch_context(self._pw, effective_opts)
            return self._ctx

        def __exit__(self, *exc: object) -> None:
            if self._ctx is not None:
                with contextlib.suppress(Exception):
                    self._ctx.close()
            if self._pw is not None:
                with contextlib.suppress(Exception):
                    self._pw.stop()
            if self._temp_dir is not None:
                with contextlib.suppress(Exception):
                    self._temp_dir.cleanup()

    return _Session()
