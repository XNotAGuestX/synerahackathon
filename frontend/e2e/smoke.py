"""UI regression: real direct routing, scripted chat delivery/retry, recovery and mobile layout.

Start the real API and Vite first. This test does not call a paid model.
Run with a Python environment containing playwright and an installed Chromium browser.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:5173/'


def main() -> int:
    with sync_playwright() as playwright:
        launch = {'headless': True}
        if os.environ.get('PLAYWRIGHT_CHROMIUM'):
            launch['executable_path'] = os.environ['PLAYWRIGHT_CHROMIUM']
        browser = playwright.chromium.launch(**launch)
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.goto(URL)
        page.get_by_role('button', name='Show Ground floor', exact=True).wait_for()
        assert page.locator('.place-search, .walk-pad, .debug-panel').count() == 0
        page.get_by_role('button', name='Set your location', exact=True).click()
        page.get_by_role('textbox', name='Search starting rooms', exact=True).fill('Warehouse zone H-C2')
        page.get_by_role('button', name='Warehouse zone H-C2 Ground floor', exact=True).click()
        page.get_by_role('button', name='Find a place', exact=True).click()
        page.get_by_role('textbox', name='Filter by name or type', exact=True).fill('Production zone H-A1')
        with page.expect_response(lambda response: response.url.endswith('/routes') and response.request.method == 'POST') as result:
            page.get_by_role('button', name='Route here', exact=True).click()
        response = result.value
        assert response.status == 201, response.text()
        route = response.json()
        session_path = response.url.removesuffix('/routes')
        session = page.request.get(session_path).json()

        def route_points():
            return page.locator('.plan .route').evaluate_all("elements => elements.map(element => element.getAttribute('points').split(' ').map(pair => pair.split(',').map(Number)))")

        page.locator('.plan .route').first.wait_for()
        expected = [leg['points'] for leg in route['legs'] if leg['floor_id'] == route['legs'][0]['floor_id']]
        assert route_points() == expected
        page.get_by_role('button', name='Next direction →', exact=True).press('Enter')
        assert route_points() == expected
        print('OK real HTTP route, full waypoint geometry, next-step persistence')

        transcript = []
        retry_keys = []
        attempts = 0

        def chat_api(intercept):
            nonlocal attempts
            if intercept.request.method == 'GET':
                intercept.fulfill(json={'schema_version': 1, 'items': transcript, 'next_cursor': None, 'has_more': False})
                return
            body = intercept.request.post_data_json
            text = body['text']
            if text == 'Retry test':
                retry_keys.append(intercept.request.headers['idempotency-key'])
                attempts += 1
                if attempts == 1:
                    intercept.fulfill(status=503, json={'code': '40001_model_unavailable', 'message': 'Temporary test failure.', 'trace_id': 'offline-ui-test'})
                    return
            now = datetime.now(timezone.utc).isoformat()
            selected_route = None
            effects = []
            if text == 'Show route':
                selected_route = {**route, 'id': str(uuid4())}
                effects = [{'type': 'draw_route', 'route_id': selected_route['id']}]
            elif text == 'Unreachable route':
                selected_route = {**route, 'id': str(uuid4()), 'reachable': False, 'length_m': None, 'legs': [], 'directions': []}
                effects = [{'type': 'draw_route', 'route_id': selected_route['id']}]
            elif text == 'Clear route':
                effects = [{'type': 'clear_route'}]
            user = {'id': str(uuid4()), 'session_id': session['id'], 'role': 'user', 'text': text, 'created_at': now, 'understood': None, 'effects': [], 'pending_action_id': None}
            guide = {**user, 'id': str(uuid4()), 'role': 'guide', 'text': 'Reply to: ' + text, 'effects': effects}
            transcript.extend([user, guide])
            intercept.fulfill(status=201, json={'schema_version': 1, 'session': session, 'user_message': user, 'guide_message': guide, 'routes': [selected_route] if selected_route else [], 'pending_action': None, 'usage': None})

        page.route('**/api/v1/sessions/*/messages*', chat_api)
        field = page.get_by_role('textbox', name='Message your building', exact=True)
        field.fill('Retry test')
        page.get_by_role('button', name='Send message', exact=True).click()
        assert field.input_value() == ''
        field.fill('Keep this new draft')
        page.get_by_role('button', name='Retry', exact=True).click()
        page.get_by_text('Reply to: Retry test', exact=True).wait_for()
        assert field.input_value() == 'Keep this new draft'
        assert page.locator('.chat-outgoing').filter(has_text='Retry test').count() == 1
        assert len(retry_keys) == 2 and retry_keys[0] == retry_keys[1]
        assert route_points() == expected
        page.reload()
        page.get_by_text('Reply to: Retry test', exact=True).wait_for()
        page.locator('.plan .route').first.wait_for()
        assert route_points() == expected
        print('OK cleared composer, failure/retry key, draft, transcript recovery, retained route')

        page.set_viewport_size({'width': 390, 'height': 844})
        page.get_by_role('button', name='Chat', exact=True).click()
        field.fill('Show route')
        page.get_by_role('button', name='Send message', exact=True).click()
        page.locator('.mobile-tabs button[aria-pressed="true"]').filter(has_text='Map').wait_for()
        page.locator('.plan .route').first.wait_for()
        assert route_points() == expected
        for width in [320, 390, 768, 899, 1024, 1440]:
            page.set_viewport_size({'width': width, 'height': 900})
            assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1'), width
            assert page.evaluate('document.documentElement.scrollHeight <= innerHeight + 1'), width
        page.locator('.more-menu > summary').click()
        page.get_by_role('button', name='Dark', exact=True).click()
        page.get_by_role('button', name='Light', exact=True).click()
        page.locator('.more-menu > summary').click()
        print('OK automatic mobile map, responsive viewport, light/dark controls')

        field.fill('Unreachable route')
        page.get_by_role('button', name='Send message', exact=True).click()
        page.get_by_text('Reply to: Unreachable route', exact=True).wait_for()
        assert page.locator('.plan .route, .plan .start, .plan .destination').count() == 0
        field.fill('Show route')
        page.get_by_role('button', name='Send message', exact=True).click()
        page.locator('.plan .route').first.wait_for()
        field.fill('Clear route')
        page.get_by_role('button', name='Send message', exact=True).click()
        page.get_by_text('Reply to: Clear route', exact=True).wait_for()
        assert page.locator('.plan .route, .plan .start, .plan .destination').count() == 0
        print('OK unreachable and explicit clearing remove old paths and endpoint markers')
        browser.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
