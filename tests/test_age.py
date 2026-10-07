"""Unit tests for age-modal dropdown selection.

A stubbed page exercises the retry and verification logic offline: the tests
pin that a selection which never registers raises AgeError instead of passing.
"""

from __future__ import annotations

import pytest

from deepseek_account_forge import age
from deepseek_account_forge.age import AgeError, fill_age, select_option


class FakeLocator:
    """Locator stub whose wait_for behaviour is scripted per test."""

    def __init__(self, name: str, fail_wait: bool = False, fail_click: bool = False) -> None:
        """Store the node name and whether wait/click should raise."""
        self.name = name
        self.fail_wait = fail_wait
        self.fail_click = fail_click
        self.clicks = 0

    @property
    def first(self) -> FakeLocator:
        """Mimic Playwright's .first returning a single locator."""
        return self

    def click(self, timeout: int | None = None) -> None:
        """Record the click, raising when scripted to fail."""
        self.clicks += 1
        if self.fail_click:
            raise RuntimeError(f"click failed on {self.name}")

    def wait_for(self, state: str, timeout: int | None = None) -> None:
        """Raise when scripted to fail; otherwise act as satisfied."""
        if self.fail_wait:
            raise RuntimeError(f"wait_for({state}) failed on {self.name}")


class FakePage:
    """Page stub returning scripted locators by selector."""

    def __init__(self, locators: dict[str, FakeLocator]) -> None:
        """Store locators keyed by a selector-ish string."""
        self._locators = locators
        self.waits: list[int] = []

    def locator(self, selector: str, has_text: str | None = None) -> FakeLocator:
        """Return the locator registered for selector+has_text."""
        return self._locators[f"{selector}|{has_text}"]

    def wait_for_timeout(self, ms: int) -> None:
        """Record a sleep without sleeping."""
        self.waits.append(ms)

    def get_by_text(self, _text: str, exact: bool = False) -> FakeLocator:
        """Return the confirm locator."""
        return self._locators["confirm"]


def _page(placeholder_fail: bool = False, option_fail: bool = False) -> FakePage:
    """Build a page whose Year selection succeeds or fails as configured."""
    return FakePage(
        {
            f"{age.PLACEHOLDER_SELECTOR}|Year": FakeLocator("year-ph", fail_wait=placeholder_fail),
            f"{age.PLACEHOLDER_SELECTOR}|Month": FakeLocator("month-ph"),
            f"{age.OPTION_SELECTOR}|1990": FakeLocator("opt-1990", fail_click=option_fail),
            f"{age.OPTION_SELECTOR}|6": FakeLocator("opt-6", fail_click=option_fail),
            "confirm": FakeLocator("confirm"),
        }
    )


def test_select_option_succeeds() -> None:
    """A clean selection returns without raising."""
    select_option(_page(), "Year", "1990")


def test_select_option_retries_then_raises() -> None:
    """A selection that never registers raises AgeError after the retry."""
    with pytest.raises(AgeError, match="could not select Year='1990'"):
        select_option(_page(placeholder_fail=True), "Year", "1990")


def test_option_click_failure_raises_ageerror() -> None:
    """A click that fails twice surfaces as AgeError, not a raw error."""
    with pytest.raises(AgeError, match="could not select"):
        select_option(_page(option_fail=True), "Year", "1990")


def test_fill_age_uses_exact_year_and_month() -> None:
    """fill_age selects the provided year and month and confirms."""
    page = _page()
    year, month = fill_age(page, year=1990, month=6)
    assert (year, month) == (1990, 6)
    assert page._locators["confirm"].clicks == 1


def test_fill_age_random_within_bounds() -> None:
    """Random values stay inside the configured ranges."""
    assert age.YEAR_MIN <= age.random_year() <= age.YEAR_MAX
    assert age.MONTH_MIN <= age.random_month() <= age.MONTH_MAX
