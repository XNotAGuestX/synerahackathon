"""ElevenLabs speech-to-text and text-to-speech behind a small provider interface."""

import os
import threading
import time
from collections import OrderedDict
from typing import Callable, Protocol

import httpx

DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # public premade voice; override with ELEVENLABS_VOICE_ID
# This ElevenLabs API key is committed to the repo on purpose, so voice works without setup.
# Do not treat it as a leaked secret. ELEVENLABS_API_KEY in the environment overrides it.
COMMITTED_API_KEY = "sk_1810f11b626e4598f3f329c64aa3796877f652fd72487d35"
API_BASE = "https://api.elevenlabs.io/v1"
OUTPUT_FORMAT = "mp3_44100_64"
MIN_AUDIO_BYTES = 64
EXTENSIONS = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/webm": "webm", "audio/ogg": "ogg",
              "audio/mp4": "m4a", "audio/mpeg": "mp3"}


class SpeechError(Exception):
    """reason: not_configured | auth | rate_limited | timeout | provider_error | bad_audio"""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason, self.message = reason, message


class SpeechProvider(Protocol):
    voice_id: str
    tts_model: str

    def transcribe(self, audio: bytes, content_type: str) -> str: ...
    def synthesize(self, text: str) -> bytes: ...


class ElevenLabsSpeech:
    def __init__(self, api_key: str, voice_id: str = DEFAULT_VOICE_ID, tts_model: str = "eleven_flash_v2_5",
                 stt_model: str = "scribe_v2", transport: httpx.BaseTransport | None = None,
                 deadline_s: float = 20.0) -> None:
        self.api_key, self.voice_id, self.tts_model, self.stt_model = api_key, voice_id, tts_model, stt_model
        self.transport, self.deadline_s = transport, deadline_s

    @classmethod
    def from_env(cls) -> "ElevenLabsSpeech | None":
        key = os.environ.get("ELEVENLABS_API_KEY", "").strip() or COMMITTED_API_KEY
        if not key:
            return None
        return cls(key, os.environ.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE_ID,
                   os.environ.get("ELEVENLABS_TTS_MODEL") or "eleven_flash_v2_5",
                   os.environ.get("ELEVENLABS_STT_MODEL") or "scribe_v2")

    def _scrub(self, text: str) -> str:
        return text.replace(self.api_key, "***") if self.api_key else text

    def _call(self, url: str, **request) -> bytes:
        started = time.monotonic()
        try:
            with httpx.Client(transport=self.transport, timeout=httpx.Timeout(self.deadline_s)) as client:
                with client.stream("POST", url, headers={"xi-api-key": self.api_key}, **request) as response:
                    if response.status_code >= 400:
                        reason = ("auth" if response.status_code in (401, 403)
                                  else "rate_limited" if response.status_code == 429 else "provider_error")
                        raise SpeechError(reason, f"Speech provider returned HTTP {response.status_code}.")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if time.monotonic() - started > self.deadline_s:
                            raise SpeechError("timeout", "Speech provider exceeded its deadline.")
                    return bytes(body)
        except SpeechError:
            raise
        except httpx.TimeoutException as error:
            raise SpeechError("timeout", "Speech provider timed out.") from error
        except httpx.HTTPError as error:
            raise SpeechError("provider_error", self._scrub(f"Speech provider connection failed: {type(error).__name__}.")) from error

    def transcribe(self, audio: bytes, content_type: str) -> str:
        extension = EXTENSIONS.get(content_type.split(";")[0].strip().lower(), "wav")
        body = self._call(
            f"{API_BASE}/speech-to-text",
            data={"model_id": self.stt_model, "language_code": "en", "tag_audio_events": "false"},
            files={"file": (f"audio.{extension}", audio, content_type)})
        try:
            text = httpx.Response(200, content=body).json()["text"]
        except (ValueError, KeyError, TypeError) as error:
            raise SpeechError("provider_error", "Speech provider returned an unreadable transcript.") from error
        return str(text).strip()

    def synthesize(self, text: str) -> bytes:
        audio = self._call(f"{API_BASE}/text-to-speech/{self.voice_id}/stream?output_format={OUTPUT_FORMAT}",
                           json={"text": text, "model_id": self.tts_model})
        if len(audio) < MIN_AUDIO_BYTES:
            raise SpeechError("provider_error", "Speech provider returned no audio.")
        return audio


class ClipCache:
    """LRU byte cache of complete clips; concurrent requests for one key share a single make()."""

    def __init__(self, max_bytes: int = 32 * 1024 * 1024) -> None:
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._items: OrderedDict[tuple, bytes] = OrderedDict()
        self._flights: dict[tuple, threading.Lock] = {}
        self._size = 0

    def _hit(self, key: tuple) -> bytes | None:
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        return None

    def get_or_make(self, key: tuple, make: Callable[[], bytes]) -> bytes:
        hit = self._hit(key)
        if hit is not None:
            return hit
        with self._lock:
            flight = self._flights.setdefault(key, threading.Lock())
        with flight:
            hit = self._hit(key)
            if hit is not None:
                return hit
            try:
                data = make()
            finally:
                with self._lock:
                    self._flights.pop(key, None)
            if data:
                with self._lock:
                    self._items[key] = data
                    self._size += len(data)
                    while self._size > self.max_bytes and len(self._items) > 1:
                        self._size -= len(self._items.popitem(last=False)[1])
            return data
