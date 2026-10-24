"""Playwright smoke for start, route, clarify, unreachable, pending, and widths."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CACHED_CHROME = Path.home() / "AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe"

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173/"
WIDTHS = [320, 390, 768, 1024, 1440]


def main() -> int:
    failures: list[str] = []

    def check(name: str, ok: bool) -> None:
        print(("OK" if ok else "FAIL"), name)
        if not ok:
            failures.append(name)

    with sync_playwright() as playwright:
        launch = {"headless": True}
        if os.environ.get("PLAYWRIGHT_CHROMIUM") :
            launch["executable_path"] = os.environ["PLAYWRIGHT_CHROMIUM"]
        elif CACHED_CHROME.exists():
            launch["executable_path"] = str(CACHED_CHROME)
        browser = playwright.chromium.launch(**launch)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(URL)
        page.wait_for_load_state("networkidle")
        check("start", page.get_by_role("heading", name="Ground floor").is_visible())
        page.get_by_role("button", name="Toggle debug view").click()
        page.get_by_role("button", name="Where is the desk?").click()
        check("clarify", page.get_by_role("button", name="Reception desk 0.19, Ground floor").is_visible())
        page.get_by_role("button", name="Unreachable step-free route").click()
        check("unreachable", page.get_by_role("alert").is_visible())
        page.get_by_role("button", name="Close the office lift").click()
        check("pending confirm", page.get_by_role("button", name="Confirm").is_visible())
        check("pending cancel", page.get_by_role("button", name="Cancel").is_visible())
        page.keyboard.press("Tab")
        check("keyboard focus", page.evaluate("() => document.activeElement !== document.body"))
        axe_path = Path(__file__).resolve().parents[1] / "node_modules" / "axe-core" / "axe.min.js"
        page.add_script_tag(content=axe_path.read_text(encoding="utf-8"))
        violations = page.evaluate(
            """() => axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] } })
              .then(result => result.violations.map(item => item.id + ' ' + item.nodes.length))"""
        )
        page.get_by_role("button", name="Stack floors").click()
        page.wait_for_timeout(400)
        check("three canvas", page.locator(".floor-stack-3d canvas").count() == 1)
        check("axe wcag", violations == [])
        if violations:
            print("axe", violations[:8])
        for width in WIDTHS:
            page.set_viewport_size({"width": width, "height": 900})
            overflow = page.evaluate("() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1")
            check(f"width {width}", not overflow)
        page.evaluate("() => { document.documentElement.dataset.theme = 'dark' }")
        background = page.locator(".debug-panel").evaluate("node => getComputedStyle(node).backgroundColor")
        check("dark debug is not white", background not in {"rgb(255, 255, 255)", "rgba(255, 255, 255, 1)"})
        browser.close()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
