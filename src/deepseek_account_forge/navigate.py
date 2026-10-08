"""Open a URL, capture artifacts, and extract selector text."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from patchright.sync_api import BrowserContext, ElementHandle, Page

DEFAULT_OUT_DIR = Path("out")
SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


@dataclass(frozen=True)
class Capture:
    """Result of opening a page."""

    url: str
    final_url: str
    title: str
    screenshot: Path
    html: Path


def _slug(url: str) -> str:
    """Turn a URL into a filesystem-safe slug."""
    stripped = re.sub(r"^https?://", "", url)
    return SAFE_NAME_RE.sub("_", stripped).strip("_") or "page"


def open_page(context: BrowserContext, url: str, wait_until: str = "networkidle") -> Page:
    """Open a URL in a page and wait for load.

    Reuses the context's initial blank tab when one is present, so a persistent
    profile does not end up with a stray about:blank tab beside the target page.
    """
    page = next((p for p in context.pages if p.url in ("", "about:blank")), None)
    if page is None:
        page = context.new_page()
    page.goto(url, wait_until=wait_until)
    return page


def wait_for_selector(page: Page, selector: str, timeout_ms: int = 60_000) -> bool:
    """Wait for a selector to appear. Returns False instead of raising on timeout.

    Use this to wait out Cloudflare-style interstitials that resolve after
    network idle, when the real form is not yet in the DOM.
    """
    try:
        page.wait_for_selector(selector, timeout=timeout_ms, state="visible")
        return True
    except Exception:
        return False


def capture(page: Page, url: str, out_dir: Path = DEFAULT_OUT_DIR) -> Capture:
    """Save a screenshot and HTML dump for the current page."""
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug(url)
    screenshot = out_dir / f"{slug}.png"
    html = out_dir / f"{slug}.html"
    page.screenshot(path=str(screenshot), full_page=True)
    html.write_text(page.content(), encoding="utf-8")
    return Capture(
        url=url,
        final_url=page.url,
        title=page.title(),
        screenshot=screenshot,
        html=html,
    )


def _node_text(node: ElementHandle) -> str:
    """Extract usable text from a node, covering form fields.

    Inputs have no inner text; their meaningful content is the value, falling
    back to placeholder or aria-label so the result is not silently empty.
    """
    for attr in ("value", "placeholder", "aria-label"):
        value = node.get_attribute(attr)
        if value:
            return value.strip()
    return (node.inner_text() or "").strip()


def extract(page: Page, selectors: list[str]) -> dict[str, list[str]]:
    """Return text or field values for each selector that matches a node."""
    results: dict[str, list[str]] = {}
    for selector in selectors:
        nodes = page.query_selector_all(selector)
        texts = [_node_text(node) for node in nodes]
        results[selector] = [text for text in texts if text]
    return results


def extract_json(page: Page, selectors: list[str]) -> str:
    """Serialize selector extraction as pretty JSON."""
    return json.dumps(extract(page, selectors), indent=2, ensure_ascii=False)
