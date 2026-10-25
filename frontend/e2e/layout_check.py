"""Playwright layout and state checks from frontend/FRONTEND_UI_REVIEW.md.

Needs the dev server and the API. Usage:
    python e2e/layout_check.py [URL] [SCREENSHOT_DIR]
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

CACHED_CHROME = Path.home() / "AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe"
AXE = Path(__file__).resolve().parents[1] / "node_modules" / "axe-core" / "axe.min.js"
URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173/"
SHOTS = Path(sys.argv[2]) if len(sys.argv) > 2 else None
WIDTHS = [(320, 720), (390, 844), (768, 1024), (1024, 768), (1440, 900)]

AXE_RUN = r"""async () => (await axe.run(document, { runOnly: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] }))
  .violations.map((v) => v.id + ' ' + v.nodes.length + ' ' + v.nodes.slice(0, 2).map((n) => n.target.join(' ')).join(', '))"""

# Every interactive element must lie inside the viewport horizontally.
OUT_OF_VIEW = r"""() => [...document.querySelectorAll('button, input, select, textarea, a[href], h1, h2')]
  .filter((e) => { const r = e.getBoundingClientRect(); if (!r.width || !e.checkVisibility()) return false; if (e.closest('.discover-categories, .place-results')) return false; return r.left < -1 || r.right > innerWidth + 1 })
  .map((e) => (e.className || e.tagName) + ':' + (e.getAttribute('aria-label') || e.textContent || '').trim().slice(0, 24))"""

failures: list[str] = []
report: dict[str, object] = {}


def check(name: str, ok: bool, detail: object = None) -> None:
    print(("OK  " if ok else "FAIL"), name, "" if detail is None else detail)
    report[name] = {"ok": ok, "detail": detail}
    if not ok:
        failures.append(name)


def shot(page: Page, name: str) -> None:
    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"{name}.png"))


def axe(page: Page) -> list[str]:
    page.add_script_tag(path=str(AXE))
    return page.evaluate(AXE_RUN)


def boot(page: Page) -> None:
    page.goto(URL)
    page.wait_for_selector(".plan-wrap:not(.plan-empty)", timeout=30000)
    page.wait_for_timeout(1500)


def rect(page: Page, selector: str) -> dict | None:
    return page.evaluate(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) return null; const r = e.getBoundingClientRect(); return {{ top: r.top, bottom: r.bottom, left: r.left, right: r.right, height: r.height }} }})()")


def intersects(a: dict | None, b: dict | None) -> bool:
    if not a or not b:
        return False
    return not (a["right"] <= b["left"] or a["left"] >= b["right"] or a["bottom"] <= b["top"] or a["top"] >= b["bottom"])


def route_a_to_b(page: Page) -> None:
    page.get_by_role("button", name="Browse").click()
    page.locator(".discover-categories button", has_text="Rooms").first.click()
    page.locator(".discover-types button").first.click()
    page.locator(".place-card").first.get_by_role("button", name="Route here").click()
    page.wait_for_timeout(500)
    if page.locator(".navigation-drawer").count():
        page.locator(".location-results button").first.click()
    page.wait_for_selector(".map-route-target", timeout=20000)
    page.wait_for_timeout(800)


def main() -> int:
    with sync_playwright() as playwright:
        launch: dict[str, object] = {"headless": True}
        if os.environ.get("PLAYWRIGHT_CHROMIUM"):
            launch["executable_path"] = os.environ["PLAYWRIGHT_CHROMIUM"]
        elif CACHED_CHROME.exists():
            launch["executable_path"] = str(CACHED_CHROME)
        browser = playwright.chromium.launch(**launch)

        # Layout at every width, both themes: the plan and the composer are reachable without page scroll.
        for theme in ("dark", "light"):
            for width, height in WIDTHS:
                context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=theme)
                page = context.new_page()
                page.add_init_script(f"localStorage.setItem('talk-building-theme', '{theme}')")
                boot(page)
                # The debug button only exists in dev builds; measure the production layout.
                page.add_style_tag(content=".dev-toggle { display: none !important; }")
                tag = f"{theme}-{width}"
                shot(page, tag)
                plan = rect(page, ".plan-wrap")
                check(f"{tag} no page overflow", page.evaluate("document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight + 1"))
                check(f"{tag} nothing outside the viewport", not page.evaluate(OUT_OF_VIEW), page.evaluate(OUT_OF_VIEW))
                check(f"{tag} plan starts in the top 45%", bool(plan) and plan["top"] <= height * 0.45, plan and round(plan["top"]))
                if width > 800:
                    composer = rect(page, ".chat-composer")
                    check(f"{tag} composer on screen", bool(composer) and composer["bottom"] <= height + 1, composer and round(composer["bottom"]))
                walk = rect(page, ".walk-pad")
                for chrome in (".map-toolbar", ".map-tools", ".place-search"):
                    check(f"{tag} walk pad clear of {chrome}", not intersects(walk, rect(page, chrome)))
                if width in (390, 1440):
                    violations = axe(page)
                    check(f"{tag} axe", violations == [], violations)
                context.close()

        # Route state, desktop and phone.
        for width, height in ((1440, 900), (390, 844)):
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            boot(page)
            next_bar = page.locator(".next-bar").inner_text()
            check(f"{width} idle bar does not claim no route", "No step-free route" not in next_bar, next_bar.replace("\n", " | "))
            route_a_to_b(page)
            shot(page, f"route-{width}")
            check(f"{width} route: guide me is the primary action", page.locator(".next-action.is-primary", has_text="Guide me").count() == 1)
            check(f"{width} route: start shown in chip", "Set your location" not in page.locator(".building-meta > .location-chip").inner_text())
            walk = rect(page, ".walk-pad")
            check(f"{width} route: walk pad clear of tools", not intersects(walk, rect(page, ".map-tools")))
            violations = axe(page)
            check(f"{width} route axe", violations == [], violations)
            context.close()

        # Keyboard: few Tab stops to the composer.
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        boot(page)
        page.add_style_tag(content=".dev-toggle { display: none !important; }")

        def tabs_to_composer(skip: bool) -> int:
            # Start from the top of the document, as a keyboard user does after load.
            boot(page)
            page.add_style_tag(content=".dev-toggle { display: none !important; }")
            for count in range(1, 80):
                page.keyboard.press("Tab")
                if skip and page.evaluate("document.activeElement?.getAttribute('href') === '#guide-pane'"):
                    page.keyboard.press("Enter")
                if page.evaluate("document.activeElement?.closest('.chat-composer') !== null"):
                    return count
            return 80

        # Was 81 before the review. The skip link is the short way; the natural order stays bounded.
        natural = tabs_to_composer(False)
        check("tab stops to composer <= 35", natural <= 35, natural)
        skipped = tabs_to_composer(True)
        check("skip link reaches the guide quickly", skipped <= 12, skipped)
        check("one Tab stop for rooms", page.evaluate("document.querySelectorAll('polygon.space[tabindex=\"0\"]').length") == 1)
        live = page.evaluate("[...document.querySelectorAll('[role=status], [aria-live], [role=log]')].map((e) => e.className || e.tagName)")
        check("live regions <= 4", len(live) <= 4, live)
        context.close()

        # Loading: no false "disconnected" or developer wording.
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        cdp = context.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 2500, "downloadThroughput": -1, "uploadThroughput": -1})
        page.goto(URL, wait_until="commit")
        page.wait_for_selector(".topbar", timeout=60000)
        page.wait_for_timeout(1500)
        text = page.locator("body").inner_text()
        shot(page, "loading")
        check("loading says connecting", "Connecting" in text)
        false_state = re.findall(r".{0,30}(?:disconnected|fixture|Floor 1\n).{0,30}", text)
        check("loading has no false state", not false_state, false_state)
        context.close()

        # Failure: message first, styled reconnect, details folded.
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.route(re.compile(r".*/api/v1/sessions.*"), lambda route: route.fulfill(status=503, content_type="application/json", body="{}"))
        page.goto(URL)
        page.wait_for_selector(".app-alert", timeout=20000)
        shot(page, "error")
        check("error: reconnect styled", page.locator(".app-alert .small-action", has_text="Reconnect").count() == 1)
        check("error: offline state", page.locator(".status-pill.is-offline").count() == 1)
        check("error: bar offers no route actions", page.locator(".next-actions").count() == 0)
        page.unroute(re.compile(r".*/api/v1/sessions.*"))
        page.get_by_role("button", name="Reconnect").click()
        page.wait_for_selector(".plan-wrap:not(.plan-empty)", timeout=30000)
        check("error: reconnect recovers", page.locator(".app-alert").count() == 0)
        context.close()

        # Phone editor: the editor is visible right after opening it.
        context = browser.new_context(viewport={"width": 390, "height": 844})
        page = context.new_page()
        boot(page)
        page.get_by_role("button", name=re.compile("Edit map")).click()
        page.wait_for_timeout(600)
        editor = rect(page, ".editor-panel")
        shot(page, "editor-390")
        check("phone editor in view", bool(editor) and editor["top"] < 844 and editor["bottom"] > 0, editor and round(editor["top"]))
        check("phone editor keeps map visible", rect(page, ".plan-wrap") is not None and rect(page, ".plan-wrap")["height"] > 0)
        context.close()

        # Long names at 320 px.
        context = browser.new_context(viewport={"width": 320, "height": 720})
        page = context.new_page()

        def lengthen(route, key: str, suffix: str) -> None:
            response = route.fetch()
            data = response.json()
            for item in data.get(key, []):
                item["name"] = item["name"] + suffix
            route.fulfill(response=response, json=data)

        page.route(re.compile(r".*/api/v1/buildings.*"), lambda route: lengthen(route, "items", " – Produktions- und Verwaltungsgebäude Nord, Bauabschnitt III"))
        page.route(re.compile(r".*/floors/.*/plan"), lambda route: lengthen(route, "spaces", " Konstruktionsbüro Qualitätssicherung"))
        boot(page)
        page.locator(".building-meta > .location-chip").click()
        page.locator(".location-results button").first.click()
        page.wait_for_timeout(500)
        shot(page, "long-320")
        check("long names: nothing outside the viewport", not page.evaluate(OUT_OF_VIEW), page.evaluate(OUT_OF_VIEW))
        check("long names: chip has full name as title", bool(page.locator(".building-meta > .location-chip").get_attribute("title")))
        context.close()

        browser.close()
    if SHOTS:
        (SHOTS / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
