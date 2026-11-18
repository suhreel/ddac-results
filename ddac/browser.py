"""Headless Chromium (Playwright) for JS-driven results sites."""
from __future__ import annotations

import contextlib
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import ROOT

UA = ("Mozilla/5.0 (compatible; DDAC-results-bot/1.0; "
      "+https://ddac.ie; club results collection)")

DEBUG_DIR = ROOT / "debug"


@contextlib.contextmanager
def browser_page():
    with sync_playwright() as p:
        exe = os.environ.get("CHROME_PATH")  # optional: use an installed Chrome locally
        b = p.chromium.launch(headless=True, executable_path=exe) if exe else p.chromium.launch(headless=True)
        ctx = b.new_context(user_agent=UA, viewport={"width": 1400, "height": 1000})
        page = ctx.new_page()
        page.set_default_timeout(30_000)
        try:
            yield page
        finally:
            ctx.close()
            b.close()


def dump(page, name: str):
    """Save HTML + screenshot when DEBUG=1, for checking selectors."""
    if os.environ.get("DEBUG") != "1":
        return
    DEBUG_DIR.mkdir(exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:80]
    (DEBUG_DIR / f"{safe}.html").write_text(page.content(), encoding="utf-8")
    with contextlib.suppress(Exception):
        page.screenshot(path=str(DEBUG_DIR / f"{safe}.png"), full_page=True)
