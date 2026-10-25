"""ElevenLabs client against httpx.MockTransport and the clip cache. No network."""

import json
import threading
import time
import unittest

import httpx

from final_agent.speech import ClipCache, ElevenLabsSpeech, SpeechError

KEY = "sk-secret-key"


def speech(handler, **options) -> ElevenLabsSpeech:
    return ElevenLabsSpeech(KEY, voice_id="voice1", transport=httpx.MockTransport(handler), **options)


class ElevenLabsSpeechTests(unittest.TestCase):
    def test_transcribe_request_and_text(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"text": "  take me to the lab  "})

        self.assertEqual(speech(handler).transcribe(b"RIFFdata", "audio/wav"), "take me to the lab")
        request = seen[0]
        self.assertEqual((str(request.url), request.headers["xi-api-key"]), ("https://api.elevenlabs.io/v1/speech-to-text", KEY))
        body = request.content.decode("latin1")
        for fragment in ("scribe_v2", 'name="language_code"\r\n\r\nen', 'name="tag_audio_events"\r\n\r\nfalse', 'filename="audio.wav"'):
            self.assertIn(fragment, body)

    def test_synthesize_request_and_short_body(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, content=b"x" * 200 if len(seen) == 1 else b"")

        client = speech(handler)
        self.assertEqual(len(client.synthesize("Hello there.")), 200)
        self.assertEqual(str(seen[0].url), "https://api.elevenlabs.io/v1/text-to-speech/voice1/stream?output_format=mp3_44100_64")
        self.assertEqual(json.loads(seen[0].content), {"text": "Hello there.", "model_id": "eleven_flash_v2_5"})
        with self.assertRaises(SpeechError) as raised:
            client.synthesize("Again.")
        self.assertEqual(raised.exception.reason, "provider_error")

    def test_errors_map_to_reasons_and_never_leak_the_key(self):
        for status, reason in ((401, "auth"), (403, "auth"), (429, "rate_limited"), (500, "provider_error")):
            with self.assertRaises(SpeechError) as raised:
                speech(lambda request: httpx.Response(status, text=f"bad key {KEY}")).transcribe(b"a", "audio/wav")
            self.assertEqual(raised.exception.reason, reason)
            self.assertNotIn(KEY, raised.exception.message)

        def timeout(request):
            raise httpx.ReadTimeout(f"timed out {KEY}", request=request)

        def refused(request):
            raise httpx.ConnectError(f"refused {KEY}", request=request)

        for handler, reason in ((timeout, "timeout"), (refused, "provider_error")):
            with self.assertRaises(SpeechError) as raised:
                speech(handler).synthesize("x")
            self.assertEqual(raised.exception.reason, reason)
            self.assertNotIn(KEY, raised.exception.message)


class ClipCacheTests(unittest.TestCase):
    def test_lru_eviction_by_total_bytes(self):
        cache = ClipCache(max_bytes=10)
        cache.get_or_make(("a",), lambda: b"xxxx")
        cache.get_or_make(("b",), lambda: b"xxxx")
        cache.get_or_make(("a",), lambda: b"never")  # refresh a, so b is the oldest
        cache.get_or_make(("c",), lambda: b"xxxx")
        made = []
        cache.get_or_make(("a",), lambda: made.append("a") or b"xxxx")
        cache.get_or_make(("b",), lambda: made.append("b") or b"xxxx")
        self.assertEqual(made, ["b"])

    def test_one_make_per_key_across_threads(self):
        cache, calls = ClipCache(), []

        def make() -> bytes:
            calls.append(1)
            time.sleep(0.1)
            return b"audio"

        results = []
        threads = [threading.Thread(target=lambda: results.append(cache.get_or_make(("k",), make))) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual((len(calls), results), (1, [b"audio", b"audio"]))


if __name__ == "__main__":
    unittest.main()
