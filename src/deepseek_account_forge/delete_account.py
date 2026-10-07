"""Delete the signed-in DeepSeek account through the Settings UI.

Destructive and irreversible. The flow is split in two:

* ``walk_to_confirm`` drives account menu -> Settings -> Profile -> Delete and
  stops on the confirmation dialog. It types nothing and clicks nothing that
  commits.
* ``confirm_delete`` types the required phrase and clicks the confirm button.

Callers must opt into ``confirm_delete`` explicitly; walking alone never
deletes anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from patchright.sync_api import Page

from .navigate import wait_for_selector

ACCOUNT_SELECTOR = "div._2afd28d"
SETTINGS_SELECTOR = 'div.ds-dropdown-menu-option:has-text("Settings")'
PROFILE_TAB_SELECTOR = 'div[role="button"]:has(span.ds-button__content:text-is("Profile"))'
DELETE_BUTTON_SELECTOR = (
    'div[role="button"].ds-button--error:has(span.ds-button__content:text-is("Delete"))'
)
CONFIRM_INPUT_SELECTOR = 'input.ds-input__input[placeholder="DELETE MY ACCOUNT"]'
CONFIRM_BUTTON_SELECTOR = (
    'div[role="button"]:has(span.ds-button__content:text-is("Confirm delete my account"))'
)
CONFIRM_PHRASE = "DELETE MY ACCOUNT"
DIALOG_SELECTOR = "div.ds-auth-delete-account"

MENU_WAIT_MS = 15_000
DIALOG_WAIT_MS = 15_000


class DeleteOutcome(Enum):
    """How the delete walk resolved."""

    AWAITING_CONFIRM = "awaiting_confirm"
    DELETED = "deleted"
    FAILED = "failed"


@dataclass(frozen=True)
class DeleteResult:
    """Result of a delete run."""

    outcome: DeleteOutcome
    detail: str = ""

    @property
    def ok(self) -> bool:
        """True when the account was actually deleted."""
        return self.outcome is DeleteOutcome.DELETED


class DeleteError(RuntimeError):
    """Raised when the delete flow cannot be driven to its target state."""


def _click(page: Page, selector: str, what: str, timeout_ms: int) -> None:
    """Click a selector or raise DeleteError with context."""
    if not wait_for_selector(page, selector, timeout_ms=timeout_ms):
        raise DeleteError(f"could not find {what} ({selector})")
    page.click(selector)


def walk_to_confirm(page: Page, timeout_ms: int = MENU_WAIT_MS) -> DeleteResult:
    """Open account menu -> Settings -> Profile -> Delete and stop at the dialog.

    Types nothing and never commits. Returns AWAITING_CONFIRM once the
    confirmation dialog is open.
    """
    _click(page, ACCOUNT_SELECTOR, "account control", timeout_ms)
    _click(page, SETTINGS_SELECTOR, "Settings menu item", timeout_ms)
    _click(page, PROFILE_TAB_SELECTOR, "Profile tab", timeout_ms)
    _click(page, DELETE_BUTTON_SELECTOR, "Delete button", timeout_ms)
    if not wait_for_selector(page, DIALOG_SELECTOR, timeout_ms=DIALOG_WAIT_MS):
        raise DeleteError("delete confirmation dialog did not open")
    return DeleteResult(
        DeleteOutcome.AWAITING_CONFIRM,
        "confirmation dialog open; pass --confirm-delete to commit",
    )


def confirm_delete(page: Page, timeout_ms: int = DIALOG_WAIT_MS) -> DeleteResult:
    """Type the required phrase and click the confirm button.

    Assumes ``walk_to_confirm`` already opened the dialog. This is the only
    function that commits the deletion.
    """
    if not wait_for_selector(page, CONFIRM_INPUT_SELECTOR, timeout_ms=timeout_ms):
        raise DeleteError("confirmation input not present; dialog not open?")
    page.fill(CONFIRM_INPUT_SELECTOR, CONFIRM_PHRASE)
    _click(page, CONFIRM_BUTTON_SELECTOR, "confirm-delete button", timeout_ms)
    return DeleteResult(DeleteOutcome.DELETED, "deletion submitted")


def run_delete(page: Page, confirm: bool, timeout_ms: int = MENU_WAIT_MS) -> DeleteResult:
    """Walk to the confirmation dialog and optionally commit.

    With ``confirm=False`` this is non-destructive: it reaches the dialog and
    stops. With ``confirm=True`` it types the phrase and clicks through.
    """
    walked = walk_to_confirm(page, timeout_ms)
    if not confirm:
        print(f"[delete] {walked.detail}")
        return walked
    result = confirm_delete(page, timeout_ms)
    print("[delete] account deletion submitted")
    return result
