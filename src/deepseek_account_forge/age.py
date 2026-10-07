"""Fill the DeepSeek age-verification modal with a random birth date."""

from __future__ import annotations

import random

from patchright.sync_api import Page

YEAR_MIN = 1970
YEAR_MAX = 2006
MONTH_MIN = 1
MONTH_MAX = 12

MODAL_TEXT = "When were you born?"
PLACEHOLDER_SELECTOR = ".ds-select__placeholder"
OPTION_SELECTOR = ".ds-select-option"
CONFIRM_TEXT = "Confirm"
OPTION_WAIT_MS = 5_000


class AgeError(RuntimeError):
    """Raised when the age modal cannot be filled to a confirmed state."""


def random_year(year_min: int = YEAR_MIN, year_max: int = YEAR_MAX) -> int:
    """Return a random birth year within the allowed range."""
    return random.randint(year_min, year_max)


def random_month() -> int:
    """Return a random month number (1-12)."""
    return random.randint(MONTH_MIN, MONTH_MAX)


def _placeholder_for(page: Page, label: str):
    """Return the placeholder locator for a dropdown label."""
    return page.locator(PLACEHOLDER_SELECTOR, has_text=label).first


def _select_once(page: Page, label: str, value: str) -> None:
    """One attempt: open the dropdown, click the exact option, wait for it to clear."""
    _placeholder_for(page, label).click(timeout=OPTION_WAIT_MS)
    # Wait for the option list to actually render before clicking.
    option = page.locator(OPTION_SELECTOR, has_text=value).first
    option.wait_for(state="visible", timeout=OPTION_WAIT_MS)
    option.click()
    # The placeholder disappears only when the selection registered.
    _placeholder_for(page, label).wait_for(state="detached", timeout=OPTION_WAIT_MS)


def select_option(page: Page, label: str, value: str) -> None:
    """Open a custom dropdown and select the exact option text.

    Retries once, then raises AgeError. A no-op selection must never pass as
    success: the placeholder detaching is the proof the value registered.
    """
    for attempt in (1, 2):
        try:
            _select_once(page, label, value)
            return
        except Exception as exc:
            if attempt == 2:
                raise AgeError(f"could not select {label}={value!r}: {exc}") from exc


def fill_age(page: Page, year: int | None = None, month: int | None = None) -> tuple[int, int]:
    """Select a birth year and month, then click Confirm. Returns the chosen values.

    Raises AgeError if either dropdown could not be set.
    """
    chosen_year = year if year is not None else random_year()
    chosen_month = month if month is not None else random_month()
    select_option(page, "Year", str(chosen_year))
    select_option(page, "Month", str(chosen_month))
    confirm = page.get_by_text(CONFIRM_TEXT, exact=True).first
    confirm.wait_for(state="visible", timeout=OPTION_WAIT_MS)
    confirm.click()
    # Let the submit register before callers poll for the modal to detach.
    page.wait_for_timeout(1_500)
    print(f"[age] selected year={chosen_year} month={chosen_month} and confirmed")
    return chosen_year, chosen_month


def complete_age_if_present(page: Page) -> bool:
    """Fill the age modal if it is showing. Returns True when handled.

    After clicking Confirm, waits for the modal to actually detach so callers
    do not proceed while the request is still in flight.
    """
    try:
        page.wait_for_selector(f"text={MODAL_TEXT}", timeout=10_000, state="visible")
    except Exception:
        return False
    # Let the dropdowns become interactive before touching them.
    page.wait_for_timeout(1_000)
    fill_age(page)
    try:
        page.wait_for_selector(f"text={MODAL_TEXT}", timeout=30_000, state="detached")
        print("[age] modal dismissed")
    except Exception as exc:
        raise AgeError("age modal still present after confirm") from exc
    page.wait_for_load_state("networkidle")
    print(f"[age] final_url={page.url}")
    return True
