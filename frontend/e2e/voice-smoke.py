"""Focused voice UI smoke: real Chrome audio/VAD, local fixture responses, no paid calls.

Run with a Vite server on 5175:
  uv run --no-project --with playwright python frontend/e2e/voice-smoke.py
Uses installed Chrome; does not bypass its autoplay policy. Recognition/model wording
and speech audio are fixtures, so this does not measure live provider accuracy.
"""
import asyncio
import io
import json
import math
import os
import struct
import sys
import tempfile
import wave
from pathlib import Path
from uuid import uuid4

from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:5175/'
CHROME = os.environ.get('PLAYWRIGHT_CHROMIUM', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
FIXTURES = ROOT / 'docs/api/examples'


def fixture(name):
    return json.loads((FIXTURES / f'{name}.json').read_text())


def wav(seconds, microphone=False):
    out = io.BytesIO()
    with wave.open(out, 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b''.join(struct.pack('<h', int(5000 * math.sin(i * math.tau * 220 / 16000)))
                                  if not microphone or 1 < i / 16000 < 2.2 or 5 < i / 16000 < 6.2
                                  else b'\0\0' for i in range(int(seconds * 16000))))
    return out.getvalue()


async def scenario(browser, name, *, slow=False, fail=False, switch=False):
    context = await browser.new_context(permissions=['microphone'], viewport={'width': 390, 'height': 844})
    page = await context.new_page()
    errors, messages, clips, transcripts, sessions = [], [], [], [], {}
    active, maximum = 0, 0
    page.on('pageerror', lambda error: errors.append(str(error)))
    await page.add_init_script('''
      window.voiceContexts = []; window.voiceStops = 0;
      const Context = window.AudioContext;
      window.AudioContext = class extends Context { constructor(...args) { super(...args); window.voiceContexts.push(this); } };
      const stop = AudioBufferSourceNode.prototype.stop;
      AudioBufferSourceNode.prototype.stop = function(...args) { window.voiceStops++; return stop.apply(this, args); };
    ''')

    async def respond(route):
        nonlocal active, maximum
        request = route.request
        path = request.url.split('/api/v1', 1)[1].split('?', 1)[0]
        body = None
        status = 200
        if path == '/object-types':
            body = {'groups': [], 'schema_version': 1}
        elif path == '/buildings':
            body = {'items': [{'id': 'proc-factory-dev-003', 'name': 'Factory', 'floors': 1},
                              {'id': 'other-building', 'name': 'Other building', 'floors': 1}]}
        elif path == '/sessions':
            body = fixture('session')
            body.update(id=str(uuid4()), building_id=request.post_data_json['building_id'])
            sessions[body['id']] = body
            status = 201
        elif path.endswith('/floors'):
            body = fixture('floors')
            body['floors'] = body['floors'][:1]
        elif path.endswith('/plan'):
            body = fixture('plan')
        elif path.endswith('/preferences'):
            body = sessions[path.split('/')[2]]
            body['preferences'] = request.post_data_json
        elif path.endswith('/guidance'):
            await asyncio.sleep(0.15)
            body = {'guidance': None, 'events': [], 'cursor': 0}
        elif path.endswith('/transcriptions'):
            recorded = request.post_data_buffer
            assert recorded[:4] == b'RIFF' and request.headers['content-type'] == 'audio/wav'
            transcripts.append(path)
            if switch:
                await asyncio.sleep(2)
            if fail and len(transcripts) == 1:
                status, body = 503, {'code': '40004_speech_unavailable', 'message': 'Speech unavailable', 'details': []}
            else:
                status, body = 201, {'text': 'Where is the printer?'}
        elif path.endswith('/messages'):
            active += 1
            maximum = max(maximum, active)
            messages.append(request.post_data_json)
            if slow and len(messages) == 1:
                await asyncio.sleep(5)
            body = fixture('message')
            body['user_message']['text'] = request.post_data_json['text']
            body['guide_message'].update(text='The printer is in the production hall on the ground floor. Its location is highlighted on the map.', effects=[])
            body['guide_message']['understood'].update(intent='locate', summary='Printer location')
            body.update(routes=[], speech_clip_id=f'clip-{len(messages)}', speech_text='The printer is in the ground-floor production hall.')
            active -= 1
            status = 201
        elif '/speech-clips/' in path:
            clips.append(path)
            await route.fulfill(content_type='audio/wav', body=wav(7 if name == 'interruption' else 0.2))
            return
        elif path.endswith('/places'):
            body = {'items': [], 'has_more': False, 'next_cursor': None}
        elif path.startswith('/sessions/'):
            body = sessions.get(path.split('/')[2], fixture('session'))
        else:
            raise AssertionError(f'Unexpected API call {path}')
        try:
            await route.fulfill(status=status, content_type='application/json', body=json.dumps(body))
        except Exception:
            if not switch:
                raise

    await page.route('**/api/v1/**', respond)
    await page.goto(URL)
    await expect(page.get_by_role('button', name='Voice', exact=True)).to_be_visible()
    await page.wait_for_function("sessionStorage.getItem('wayfinder-session-v1') !== null")
    await page.get_by_role('button', name='Voice', exact=True).click()
    if slow:
        await page.locator('.composer input').fill('Slow typed request')
        await page.locator('.composer').evaluate('(form) => form.requestSubmit()')
    await expect(page.get_by_role('button', name='Finish speaking', exact=True)).to_be_visible(timeout=10000)
    await page.get_by_role('button', name='Finish speaking', exact=True).click()
    if switch:
        await page.wait_for_timeout(200)
        await page.get_by_label('Choose building').select_option('other-building')
        await page.wait_for_timeout(2400)
        assert not messages and not clips, (messages, clips)
        assert await page.locator('.voice-transcript').count() == 0
        assert await page.evaluate('window.voiceContexts.every(context => context.state === "closed")')
    elif fail:
        await expect(page.get_by_role('alert').filter(has_text='Voice service is unavailable')).to_be_visible()
        await expect(page.locator('.voice-transcript')).to_contain_text('Where is the printer?', timeout=10000)
        await page.wait_for_function('document.querySelector(".guide-text") !== null')
        await page.wait_for_timeout(400)
        assert len(transcripts) >= 2 and len(messages) >= 1
    else:
        if slow:
            await expect(page.locator('.voice-pill')).to_have_text('Queued', timeout=4000)
        await expect(page.locator('.voice-transcript')).to_contain_text('Where is the printer?', timeout=10000)
        await expect(page.locator('.guide-text').filter(has_text='Its location is highlighted')).to_be_visible(timeout=10000)
        if name == 'interruption':
            await expect(page.locator('.voice-pill')).to_have_text('Speaking', timeout=5000)
            await expect(page.get_by_role('button', name='Finish speaking', exact=True)).to_be_visible(timeout=8000)
            assert await page.evaluate('window.voiceStops > 0')
        assert len(messages) >= (2 if slow else 1) and maximum == 1, (messages, maximum)
        assert await page.evaluate('window.voiceContexts[0].state === "running"')
        await page.get_by_role('button', name='Text', exact=True).click()
        await page.wait_for_timeout(100)
        assert await page.evaluate('window.voiceContexts.every(context => context.state === "closed")')
    assert not errors, errors
    print(f'PASS {name}: {len(transcripts)} recordings, {len(messages)} messages; maximum concurrent messages={maximum}', flush=True)
    await context.close()


async def main():
    with tempfile.TemporaryDirectory(prefix='synera-voice-') as directory:
        microphone = Path(directory) / 'microphone.wav'
        microphone.write_bytes(wav(30, microphone=True))
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path=CHROME, headless=True, args=[
                '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
                f'--use-file-for-fake-audio-capture={microphone}', '--no-sandbox',
            ])
            try:
                await scenario(browser, 'interruption')
                await scenario(browser, 'typed-and-voice queue', slow=True)
                await scenario(browser, 'transcription recovery', fail=True)
                await scenario(browser, 'session switch', switch=True)
            finally:
                await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
