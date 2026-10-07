"""Integration smoke test: the stealth browser reaches DeepSeek.

Marked `integration`; needs a browser and network, so it is excluded from the
default unit run (`-m "not integration"`).
"""

from __future__ import annotations

import pytest

from deepseek_account_forge.browser import LaunchOptions, open_session
from deepseek_account_forge.navigate import open_page

TARGET = "https://chat.deepseek.com/sign_up"

pytestmark = pytest.mark.integration


@pytest.mark.timeout(120)
def test_signup_page_loads() -> None:
    """Open the signup page headless and assert it renders a title."""
    options = LaunchOptions(headless=True)
    with open_session(options) as context:
        page = open_page(context, TARGET, wait_until="domcontentloaded")
        assert page.url.startswith("https://chat.deepseek.com")
        assert page.title() != ""
