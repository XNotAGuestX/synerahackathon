"""Two real UI sessions against a temporary API output directory (no model calls).

Start the API on 8017 with --output pointing at a scratch directory, and Vite on
5175 with API_PROXY=http://127.0.0.1:8017. Run from the repository root:
  uv run --no-project --with playwright python frontend/e2e/shared-objects-smoke.py
"""
import asyncio
import os
import sys
from uuid import uuid4

from playwright.async_api import async_playwright, expect

URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:5175/'
CHROME = os.environ.get('PLAYWRIGHT_CHROMIUM', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
NAME = f'Shared browser table {uuid4().hex[:8]}'


async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=CHROME, headless=True)
        contexts = [await browser.new_context(viewport={'width': 1440, 'height': 1000}) for _ in range(2)]
        pages = [await context.new_page() for context in contexts]
        errors = []
        for page in pages:
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(URL)
            await expect(page.get_by_text('API connected', exact=True)).to_be_visible(timeout=20000)
        first, other = pages
        await other.get_by_role('textbox', name='Filter by name or type').fill(NAME)
        await expect(other.locator('.place-search').get_by_text(NAME, exact=True)).to_have_count(0)
        await first.get_by_role('button', name='Edit map', exact=True).click()
        await first.get_by_label('Search all types', exact=True).fill('coffee table')
        await first.get_by_role('button', name='Coffee table', exact=False).click()
        await first.get_by_label('Room', exact=True).select_option(label='Production zone H-A1')
        await first.get_by_role('button', name='Place in room', exact=True).click()
        await first.get_by_label('Name', exact=True).fill(NAME)
        await first.get_by_role('button', name='Save', exact=True).click()
        await expect(first.get_by_role('button', name='Save', exact=True)).to_be_disabled(timeout=15000)
        await expect(other.locator('.place-search').get_by_text(NAME, exact=True)).to_be_visible(timeout=7000)
        # An unsaved rename survives a foreign edit and requires review before saving.
        await first.get_by_label('Name', exact=True).fill(NAME + ' retained draft')
        session = await other.evaluate("JSON.parse(sessionStorage.getItem('wayfinder-session-v1') || 'null')")
        assert session and session['id']
        api = URL.rstrip('/') + '/api/v1'
        proposal = await contexts[1].request.post(f"{api}/sessions/{session['id']}/actions", data={'kind': 'add_object', 'type': 'chair', 'space': 'H-A1'}, headers={'Idempotency-Key': str(uuid4())})
        assert proposal.status == 201, await proposal.text()
        action = await proposal.json()
        confirmed = await contexts[1].request.post(f"{api}/sessions/{session['id']}/actions/{action['id']}/confirmations", data={}, headers={'Idempotency-Key': str(uuid4())})
        assert confirmed.status == 200, await confirmed.text()
        await expect(first.get_by_text('The room objects changed. Your draft is kept. Review it against the updated map, then Save again.', exact=True)).to_be_visible(timeout=7000)
        await expect(first.get_by_label('Name', exact=True)).to_have_value(NAME + ' retained draft')
        await first.get_by_role('button', name='Save', exact=True).click()
        await expect(first.get_by_role('button', name='Save', exact=True)).to_be_enabled()
        await first.get_by_role('button', name='Save', exact=True).click()
        await expect(first.get_by_role('button', name='Save', exact=True)).to_be_disabled(timeout=15000)
        await other.get_by_role('textbox', name='Filter by name or type').fill(NAME + ' retained draft')
        await expect(other.locator('.place-search').get_by_text(NAME + ' retained draft', exact=True)).to_be_visible(timeout=7000)
        await first.get_by_role('button', name='Remove', exact=True).click()
        await first.get_by_role('button', name='Remove', exact=True).click()
        await expect(other.locator('.place-search').get_by_text(NAME + ' retained draft', exact=True)).to_have_count(0, timeout=7000)
        assert not errors, errors
        print('PASS: UI add, automatic second-session refresh, retained stale draft/review, rename and shared removal; no browser errors.')
        await browser.close()


asyncio.run(main())
