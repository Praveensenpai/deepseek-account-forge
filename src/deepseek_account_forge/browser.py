"""Patchright launch helpers with a persistent stealth profile."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from patchright.sync_api import BrowserContext, Playwright, sync_playwright

DEFAULT_USER_DATA_DIR = Path.home() / ".local" / "share" / "deepseek-account-forge" / "profile"
DEFAULT_TIMEOUT_MS = 60_000
DEFAULT_VIEWPORT = {"width": 1280, "height": 900}


@dataclass(frozen=True)
class LaunchOptions:
    """Configuration for a stealth browser session."""

    headless: bool = False
    user_data_dir: Path = DEFAULT_USER_DATA_DIR
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    locale: str = "en-US"
    timezone: str = "America/New_York"

    @classmethod
    def from_env(cls) -> LaunchOptions:
        """Build options from environment variables."""
        headless = os.environ.get("HEADLESS", "").lower() in {"1", "true", "yes"}
        profile = os.environ.get("STEALTH_PROFILE")
        user_data_dir = Path(profile).expanduser() if profile else DEFAULT_USER_DATA_DIR
        return cls(headless=headless, user_data_dir=user_data_dir)


def launch_context(playwright: Playwright, options: LaunchOptions) -> BrowserContext:
    """Launch a persistent Chromium context tuned for stealth."""
    options.user_data_dir.mkdir(parents=True, exist_ok=True)
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(options.user_data_dir),
        headless=options.headless,
        channel="chrome",
        # Pin the layout size instead of following the OS window. Some window
        # managers ignore --window-size, which collapses DeepSeek's left rail
        # off-screen (negative x) and hides the account control.
        viewport=DEFAULT_VIEWPORT,
        locale=options.locale,
        timezone_id=options.timezone,
        args=[
            "--disable-blink-features=AutomationControlled",
            f"--window-size={DEFAULT_VIEWPORT['width']},{DEFAULT_VIEWPORT['height']}",
        ],
    )
    context.set_default_timeout(options.timeout_ms)
    return context


def open_session(options: LaunchOptions | None = None):
    """Context manager yielding a stealth browser context.

    Yields the context; the caller opens pages. Closes on exit.
    """
    opts = options or LaunchOptions.from_env()

    class _Session:
        def __enter__(self) -> BrowserContext:
            self._pw = sync_playwright().start()
            self._ctx = launch_context(self._pw, opts)
            return self._ctx

        def __exit__(self, *exc: object) -> None:
            self._ctx.close()
            self._pw.stop()

    return _Session()
