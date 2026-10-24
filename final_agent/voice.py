"""Voice backend: ElevenLabs speech in and out, isolated sessions, and a client-neutral HTTP API.

Run:  uv run python -m final_agent.voice data/dev/<building_id> [--cert CERT --key KEY]
Standard library only. Without ELEVENLABS_API_KEY the HTTP API remains available with text-only speech items.
Without Anthropic credentials guidance still works; agent answers become one clear spoken sentence.
"""

import argparse
import contextlib
import itertools
import json
import math
import os
import re
import ssl
import sys
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import anthropic

from .agent import BuildingAgent, MissingCredentialsError
from .building_map import BuildingMap, MapError, RouteResult
from .guidance import Guidance, route_checkpoints
from .viewer import route_polylines

DEFAULT_OUTPUT_DIRECTORY = Path("agent_output") / "voice"
API_ROOT = "https://api.elevenlabs.io/v1"
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
DEFAULT_TTS_MODEL = "eleven_flash_v2_5"
DEFAULT_STT_MODEL = "scribe_v2"
REQUEST_TIMEOUT_S = 30
CHUNK_BYTES = 8192
AUDIO_FILE_NAMES = (
    ("webm", "speech.webm"), ("mp4", "speech.m4a"), ("m4a", "speech.m4a"), ("aac", "speech.m4a"),
    ("ogg", "speech.ogg"), ("wav", "speech.wav"), ("mpeg", "speech.mp3"), ("mp3", "speech.mp3"),
)
# ElevenLabs may report ISO 639-1 or ISO 639-3 codes; normalize the common three-letter forms.
LANGUAGE_CODES = {
    "eng": "en", "deu": "de", "fra": "fr", "spa": "es", "ita": "it", "pol": "pl",
    "nld": "nl", "por": "pt", "tur": "tr", "rus": "ru", "ukr": "uk",
}
MAX_SESSIONS = 50
MAX_SPEECH_ITEMS = 256
MAX_AUDIO_CACHE_BYTES = 20 * 1024 * 1024
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024
UPDATE_WAIT_S = 0.1  # a position update waits this long for a running agent turn, then stays pending

GREETING = "Hi, I'm your guide for {building}. Where would you like to go?"
NO_AI_SERVICE = "I can't answer questions right now because the AI service isn't set up on the server."
AI_OVERLOADED = "I'm a bit overloaded, give me a moment and ask again."
AI_UNREACHABLE = "I can't reach the AI service right now."
AI_FAILED = "Something went wrong on my side, please try again."
# Short replies that need no model call. Confirm and stop act on guidance; repeat also replays the last agent reply.
COMMANDS = {
    "confirm": (
        "ok", "okay", "ok next", "next", "next step", "done", "got it", "yes", "yep", "alright", "all right",
        "i'm there", "im there", "i am there", "i'm here", "im here", "here", "made it", "continue", "go on",
        "and now", "what now", "now what", "weiter", "ok weiter", "okay weiter", "ja", "erledigt", "bin da",
        "ich bin da", "da bin ich", "bin hier", "geschafft", "passt", "nächster schritt", "und jetzt", "weiter gehts",
    ),
    "repeat": (
        "repeat", "again", "say again", "say that again", "what", "pardon", "sorry", "come again", "nochmal",
        "noch mal", "wiederholen", "wie bitte", "was",
    ),
    "stop": (
        "stop", "cancel", "stop navigation", "end navigation", "abbrechen", "stopp", "beenden", "navigation beenden",
    ),
}
# Spoken while the agent thinks, so a slow answer does not leave the phone silent. Audio is cached by text.
FILLERS = {
    "en": ["One sec.", "Let me check.", "Hmm, let me look.", "Okay, give me a second."],
    "de": ["Moment.", "Ich schau mal kurz.", "Hmm, Sekunde.", "Okay, einen Moment."],
}
# Audio-event tags the transcriber writes for non-speech, such as "(music)" or "[noise]". A span with digits is
# not a tag, so a room number such as "(1.08)" still reaches the agent.
NOISE_TAG = re.compile(r"\([^()\d]*\)|\[[^\[\]\d]*\]")

AgentFactory = Callable[[BuildingMap, Path, Guidance], BuildingAgent]
Opener = Callable[..., Any]


class VoiceServiceError(RuntimeError):
    """ElevenLabs failed or refused a request. The message is shown to the user and never contains the API key."""


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _env_setting(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def _audio_file_name(content_type: str) -> str:
    lowered = content_type.lower()
    return next((name for marker, name in AUDIO_FILE_NAMES if marker in lowered), "speech.bin")


def _json_object(raw: bytes) -> dict:
    try:
        data = json.loads(raw)
    except ValueError as error:
        raise VoiceServiceError("ElevenLabs sent a reply that is not JSON.") from error
    if not isinstance(data, dict):
        raise VoiceServiceError("ElevenLabs sent a reply in an unexpected shape.")
    return data


def _normalise(text: str) -> str:
    """Lower case, no punctuation, single spaces, so 'Okay!' matches 'okay' and 'I'm there.' matches 'im there'."""
    return " ".join(re.sub(r"[^\w\s]", "", text.lower()).split())


def _without_noise(text: str) -> str:
    """The transcript with audio-event tags removed and runs of spaces collapsed."""
    return " ".join(NOISE_TAG.sub(" ", text).split())


COMMAND_PHRASES = {_normalise(phrase): command for command, phrases in COMMANDS.items() for phrase in phrases}


class ElevenLabs:
    """The two ElevenLabs calls the phone needs: speech-to-text for an utterance and streamed text-to-speech."""

    def __init__(
        self, api_key: str, voice_id: str = DEFAULT_VOICE_ID, tts_model: str = DEFAULT_TTS_MODEL,
        stt_model: str = DEFAULT_STT_MODEL, opener: Opener = urllib.request.urlopen,
    ) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.tts_model = tts_model
        self.stt_model = stt_model
        self.opener = opener

    @classmethod
    def from_env(cls) -> "ElevenLabs | None":
        api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        if not api_key:
            return None
        return cls(
            api_key,
            voice_id=_env_setting("ELEVENLABS_VOICE_ID", DEFAULT_VOICE_ID),
            tts_model=_env_setting("ELEVENLABS_TTS_MODEL", DEFAULT_TTS_MODEL),
            stt_model=_env_setting("ELEVENLABS_STT_MODEL", DEFAULT_STT_MODEL),
        )

    def transcribe(self, audio: bytes, content_type: str) -> tuple[str, str | None]:
        """The words and two-letter language of one utterance; language is None when ElevenLabs gives none."""
        boundary = uuid.uuid4().hex
        # No "(music)"-style tags for non-speech sounds; handle_text drops any that still arrive.
        head = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="model_id"\r\n\r\n{self.stt_model}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="tag_audio_events"\r\n\r\nfalse\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{_audio_file_name(content_type)}"\r\nContent-Type: {content_type}\r\n\r\n'
        )
        body = head.encode("utf-8") + audio + f"\r\n--{boundary}--\r\n".encode("utf-8")
        request = urllib.request.Request(
            f"{API_ROOT}/speech-to-text", data=body, method="POST",
            headers={"xi-api-key": self.api_key, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with self._open(request) as response:
            data = _json_object(response.read())
        code = data.get("language_code")
        language = LANGUAGE_CODES.get(code, code) if isinstance(code, str) and code else None
        return str(data.get("text") or "").strip(), language

    def stream_speech(self, text: str, language: str | None) -> Iterator[bytes]:
        """MP3 audio for `text`, yielded in chunks as ElevenLabs produces them."""
        body: dict = {
            "text": text, "model_id": self.tts_model,
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.8},
        }
        if "v2_5" in self.tts_model and language and len(language) == 2:
            body["language_code"] = language  # only the v2.5 models accept a language hint
        request = urllib.request.Request(
            f"{API_ROOT}/text-to-speech/{self.voice_id}/stream?output_format=mp3_44100_128",
            data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"xi-api-key": self.api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        )
        with self._open(request) as response:
            while chunk := response.read(CHUNK_BYTES):
                yield chunk

    @contextlib.contextmanager
    def _open(self, request: urllib.request.Request) -> Iterator[Any]:
        """Open a request. Any failure, including while reading the body, becomes a VoiceServiceError."""
        try:
            with self.opener(request, timeout=REQUEST_TIMEOUT_S) as response:
                yield response
        except urllib.error.HTTPError as error:
            detail = " ".join(error.read().decode("utf-8", "replace").split())[:200]
            raise VoiceServiceError(self._scrub(f"ElevenLabs {error.code}: {detail}")) from error
        except OSError as error:
            reason = error.reason if isinstance(error, urllib.error.URLError) else error
            raise VoiceServiceError(self._scrub(f"Cannot reach ElevenLabs: {reason}")) from error

    def _scrub(self, message: str) -> str:
        return message.replace(self.api_key, "[key]") if self.api_key else message


class SpeechStore:
    """Speech texts handed to clients by id, and finished audio cached by (text, language) within a size budget."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._texts: OrderedDict[str, tuple[str, str | None]] = OrderedDict()
        self._pinned: dict[str, tuple[str, str | None]] = {}
        self._audio: OrderedDict[tuple[str, str | None], bytes] = OrderedDict()
        self._audio_bytes = 0

    def add(self, text: str, language: str | None, pinned: bool = False) -> str:
        speech_id = uuid.uuid4().hex
        with self._lock:
            if pinned:
                self._pinned[speech_id] = (text, language)
            else:
                self._texts[speech_id] = (text, language)
                while len(self._texts) > MAX_SPEECH_ITEMS:
                    self._texts.popitem(last=False)
        return speech_id

    def get(self, speech_id: str) -> tuple[str, str | None] | None:
        with self._lock:
            return self._pinned.get(speech_id) or self._texts.get(speech_id)

    def cached_audio(self, text: str, language: str | None) -> bytes | None:
        with self._lock:
            return self._audio.get((text, language))

    def store_audio(self, text: str, language: str | None, audio: bytes) -> None:
        """Keep a complete clip. The oldest clips are dropped first when the budget is exceeded."""
        key = (text, language)
        with self._lock:
            if key in self._audio:
                self._audio_bytes -= len(self._audio.pop(key))
            self._audio[key] = audio
            self._audio_bytes += len(audio)
            while self._audio_bytes > MAX_AUDIO_CACHE_BYTES:
                _, evicted = self._audio.popitem(last=False)
                self._audio_bytes -= len(evicted)


def default_agent(building_map: BuildingMap, output_directory: Path, guidance: Guidance) -> BuildingAgent:
    return BuildingAgent(building_map, output_directory, guidance=guidance, voice=True)


class VoiceSession:
    """One phone's conversation: its own map, guidance, agent and last position.

    The caller holds `lock` for each turn or position update, so the map and the agent never see two requests at once.
    """

    def __init__(
        self, building_map: BuildingMap, output_directory: Path, agent_factory: AgentFactory = default_agent,
    ) -> None:
        self.building_map = building_map
        self.guidance = Guidance(building_map)
        self.language = "en"
        self.position: dict | None = None
        self.pending_position: dict | None = None  # newest fix posted while a turn held the lock
        self.last_was_guidance = False  # the last thing said was a guidance instruction
        self.last_reply: str | None = None  # the agent's last reply, repeated by "say again" until guidance speaks
        self.lock = threading.Lock()
        self.agent: BuildingAgent | None = None
        self.agent_error: str | None = None
        try:
            self.agent = agent_factory(building_map, output_directory, self.guidance)
        except Exception as error:  # a broken local Anthropic setup must not stop guidance; the reason is kept
            self.agent_error = f"{type(error).__name__}: {error}"

    def handle_text(self, text: str, language: str | None = None) -> list[str]:
        """What to say for one user turn. Silence and noise say nothing; short replies may skip the model."""
        text = _without_noise(text)
        if not any(char.isalnum() for char in text):
            return []  # nothing was said, so the language and the guidance state stay as they were
        if language:
            self.language = language
            self.guidance.language = language
        command = COMMAND_PHRASES.get(_normalise(text))
        if command == "stop" and self.guidance.active:
            return self._guidance_command("stop")
        if command == "confirm" and self.guidance.active and not self._asked_question():
            return self._guidance_command("confirm")
        if command == "repeat" and self.guidance.active and self.last_was_guidance:
            return self._guidance_command("repeat")
        if command == "repeat" and self.last_reply and not self.last_was_guidance:
            return [self.last_reply]
        before = self.building_map.last_route
        reply = self._ask_agent(text)
        self._adopt_changed_route(before)
        said = self.guidance.drain()
        self.last_was_guidance = bool(said)
        self.last_reply = reply or None
        return [reply, *said] if reply else said

    def update(self, position: dict | None) -> list[str]:
        """Apply a position fix (None keeps the last one) and speak any guidance it triggers."""
        if position is not None:
            floor_level, x_m, y_m, accuracy_m = self.validate_position(position)
            space_id = self.building_map.space_at(floor_level, x_m, y_m)
            self.position = {
                "floor_level": floor_level, "x": x_m, "y": y_m, "space_id": space_id,
                "space_name": self.building_map.spaces[space_id]["name"] if space_id else None,
            }
            self.guidance.update_position(floor_level, x_m, y_m, accuracy_m)
        self.guidance.tick()
        said = self.guidance.drain()
        if said:
            self.last_was_guidance = True
        return said

    def validate_position(self, position: object) -> tuple[int, float, float, float | None]:
        """floor_level as a whole number, x and y in metres, optional accuracy_m >= 0. Raises ValueError otherwise."""
        if not isinstance(position, dict):
            raise ValueError("position must be an object with floor_level, x and y.")
        floor_level, x_m, y_m = position.get("floor_level"), position.get("x"), position.get("y")
        accuracy_m = position.get("accuracy_m")
        if not isinstance(floor_level, int) or isinstance(floor_level, bool):
            raise ValueError("floor_level must be a whole number.")
        if not (_finite(x_m) and _finite(y_m)):
            raise ValueError("x and y must be finite numbers in metres.")
        if accuracy_m is not None and not (_finite(accuracy_m) and accuracy_m >= 0):
            raise ValueError("accuracy_m must be a non-negative number.")
        self.building_map.floor_by_level(floor_level)  # MapError, a ValueError, for an unknown level
        return floor_level, float(x_m), float(y_m), None if accuracy_m is None else float(accuracy_m)

    def state(self) -> dict:
        return {"guidance": self.guidance.status(), "position": self.position}

    def context_line(self) -> str:
        """The app context sent with each user message: where the user is and what guidance runs."""
        status = self.guidance.status()
        guidance = "off"
        if status["active"]:
            step, total = status["progress"][0] + 1, status["progress"][1]
            guidance = (
                f"heading to {status['destination']['name']}, next: {_next_words(status['next'])}, "
                f"step {step} of {total}"
            )
        return (
            f"[app: language={self.language}; position={self._position_words()}, "
            f"tracking {status['tracking']}; guidance: {guidance}]"
        )

    def _position_words(self) -> str:
        if self.position is None:
            return "unknown"
        floor = self.building_map.floor_by_level(self.position["floor_level"])["name"]
        if self.position["space_id"] is None:
            return f"between rooms on {floor}"
        return f"{self.position['space_name']} on {floor} (space {self.position['space_id']})"

    def _guidance_command(self, command: str) -> list[str]:
        actions = {"confirm": self.guidance.confirm, "repeat": self.guidance.repeat, "stop": self.guidance.stop}
        actions[command]()
        said = self.guidance.drain()
        self.last_was_guidance = bool(said)
        return said

    def _asked_question(self) -> bool:
        """The last thing said was an agent reply with a question, so a short reply answers that question instead."""
        return not self.last_was_guidance and (self.last_reply or "").rstrip().endswith("?")

    def _ask_agent(self, text: str) -> str:
        """The agent's reply, or one honest sentence when it cannot answer."""
        if self.agent is None:
            return NO_AI_SERVICE
        try:
            return self.agent.ask(f"{self.context_line()}\n{text}")
        except (MissingCredentialsError, anthropic.AuthenticationError):
            return NO_AI_SERVICE
        except anthropic.RateLimitError:
            return AI_OVERLOADED
        except anthropic.APIConnectionError:
            return AI_UNREACHABLE
        except anthropic.APIStatusError:
            return AI_FAILED

    def _adopt_changed_route(self, before: RouteResult | None) -> None:
        """Guidance walks a re-planned or blocked trip to the same destination, for example after a closure."""
        request = self.building_map.active_request
        route = self.building_map.last_route
        if not self.guidance.active or route is before or request is None:
            return
        if self.building_map.resolve_space(request["destination"]) == self.guidance.route.destination_space_id:
            self.guidance.adopt(route)


def _next_words(step: dict) -> str:
    if step["kind"] == "door":
        return f"door into {step['name']}"
    if step["kind"] == "connector":
        return f"take {step['name']}"
    if step["kind"] == "arrival":
        return f"arrival at {step['name']}"
    return "turn"


class RequestError(Exception):
    """A request the server refuses, with the HTTP status to answer with."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def building_payload(building_map: BuildingMap) -> dict:
    """The plan for API clients: floors, rooms and openings with ids, names, types and geometry."""
    data = building_map.data
    return {
        "name": data["building"]["name"],
        "floors": [{"id": f["id"], "level": f["level"], "name": f["name"]} for f in data["floors"]],
        "spaces": [
            {"id": s["id"], "floor_id": s["floor_id"], "name": s["name"], "type": s["type"], "polygon": s["polygon"]}
            for s in data["spaces"]
        ],
        "openings": [
            {"id": o["id"], "floor_id": o["floor_id"], "position": o["position"], "kind": o["kind"]}
            for o in data["openings"]
        ],
    }


class VoiceServer(ThreadingHTTPServer):
    """State shared by the request handlers: the building, the sessions, the speech store and the ElevenLabs client."""

    def __init__(
        self, address: tuple[str, int], building_path: Path, output_directory: Path, building: dict,
        eleven: ElevenLabs | None, agent_factory: AgentFactory,
    ) -> None:
        super().__init__(address, VoiceHandler)
        self.building_path = building_path
        self.output_directory = output_directory
        self.building = building
        self.eleven = eleven
        self.agent_factory = agent_factory
        self.sessions: dict[str, VoiceSession] = {}
        self.sessions_lock = threading.Lock()
        self.speech = SpeechStore()
        self.fillers: dict[str, list[dict]] = {}
        self.fillers_lock = threading.Lock()


class VoiceHandler(BaseHTTPRequestHandler):
    """The API in VOICE_HANDOFF section 4. Answers are JSON; failures are {"error": "..."} with a 4xx or 5xx status."""

    server: VoiceServer

    def log_message(self, format: str, *args: Any) -> None:
        """Request lines stay off the console; failures are printed where they happen."""

    def do_GET(self) -> None:
        self._respond(self._get)

    def do_POST(self) -> None:
        self._respond(self._post)

    def _respond(self, handle: Callable[[], None]) -> None:
        try:
            handle()
        except ConnectionError:
            pass  # the phone hung up before the answer was read (broken pipe, reset or, on Windows, aborted)
        except RequestError as error:
            self._send_json(error.status, {"error": str(error)})
        except ValueError as error:
            self._send_json(400, {"error": str(error)})
        except VoiceServiceError as error:
            self._send_json(502, {"error": str(error)})
        except Exception:
            traceback.print_exc()
            self._send_json(500, {"error": "Something went wrong on the server."})

    def _get(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path == "/":
            self._send_json(200, {
                "service": "Talk to Your Building voice backend",
                "ui": False,
                "endpoints": ["/api/session", "/api/text", "/api/turn", "/api/update", "/api/route"],
            })
        elif path == "/api/building":
            self._send_json(200, self.server.building)
        elif path == "/api/route":
            self._send_json(200, self._route(self._find_session(self._query("session"))))
        elif path.startswith("/api/speech/"):
            self._speech(path.removeprefix("/api/speech/"))
        else:
            raise RequestError(404, "Not found.")

    def _post(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/session":
            self._send_json(200, self._new_session())
        elif path == "/api/turn":
            self._turn()
        elif path == "/api/text":
            self._text()
        elif path == "/api/update":
            self._update()
        else:
            raise RequestError(404, "Not found.")

    def _new_session(self) -> dict:
        self._json_body()  # no fields are needed; reading the body keeps the connection in step
        session_id = uuid.uuid4().hex
        session = VoiceSession(
            BuildingMap.load(self.server.building_path), self.server.output_directory / session_id,
            self.server.agent_factory,
        )
        if session.agent_error:
            print(f"Voice agent unavailable: {session.agent_error}", file=sys.stderr, flush=True)
        with self.server.sessions_lock:
            sessions = self.server.sessions
            while len(sessions) >= MAX_SESSIONS:
                del sessions[next(iter(sessions))]
            sessions[session_id] = session
        name = self.server.building["name"]
        return {
            "session": session_id, "building": name, "stt": self.server.eleven is not None,
            "tts": self.server.eleven is not None, "agent": session.agent is not None,
            "speak": self._speech_items([GREETING.format(building=name)], session.language),
            "fillers": self._filler_items(),
        }

    def _turn(self) -> None:
        audio = self._body(MAX_UPLOAD_BYTES)  # read first: an early reply over unread bytes can be reset on Windows
        session = self._find_session(self._query("session"))
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("audio/"):
            raise RequestError(415, "Send the recording as audio, for example with Content-Type audio/webm.")
        if self.server.eleven is None:
            raise RequestError(503, "Speech-to-text is off on the server; send recognised text to /api/text instead.")
        if not audio:
            raise RequestError(400, "No audio received.")
        text, language = self.server.eleven.transcribe(audio, content_type)
        self._send_json(200, self._answer(session, text, language))

    def _text(self) -> None:
        body = self._json_body()
        session = self._find_session(body.get("session"))
        text, language = body.get("text"), body.get("language")
        if not isinstance(text, str):
            raise RequestError(400, "text must be a string.")
        if language is not None and not isinstance(language, str):
            raise RequestError(400, "language must be a string such as en or de.")
        self._send_json(200, self._answer(session, text, language or None))

    def _answer(self, session: VoiceSession, text: str, language: str | None) -> dict:
        """One user turn under the session lock. The transcript is echoed back for the caption."""
        with session.lock:
            said = session.handle_text(text, language)
            return {
                "transcript": text, "language": session.language,
                "speak": self._speech_items(said, session.language), "state": session.state(),
            }

    def _update(self) -> None:
        body = self._json_body()
        session = self._find_session(body.get("session"))
        position = body.get("position")
        if position is not None:
            session.validate_position(position)  # reject a bad fix now, not when it is applied later
        if not session.lock.acquire(timeout=UPDATE_WAIT_S):
            # An agent turn is running. Keep the newest fix; the next update that gets the lock applies it.
            if position is not None:
                session.pending_position = position
            self._send_json(200, {"speak": [], "state": session.state()})
            return
        try:
            latest = position if position is not None else session.pending_position
            session.pending_position = None
            said = session.update(latest)
            self._send_json(200, {"speak": self._speech_items(said, session.language), "state": session.state()})
        finally:
            session.lock.release()

    def _route(self, session: VoiceSession) -> dict:
        """The walk on the map: the guided route while guidance runs, otherwise the last planned route."""
        with session.lock:
            guidance = session.guidance
            route = guidance.route if guidance.active else session.building_map.last_route
            if route is None:
                return {"polylines": [], "checkpoints": [], "next_index": None}
            try:
                checkpoints = route_checkpoints(session.building_map, route)
            except MapError as error:
                raise RequestError(409, str(error)) from error
            polylines = route_polylines(session.building_map, route)
            next_index = guidance.status()["next"]["index"] if guidance.active else None
        return {
            "polylines": [
                {"floor_id": floor_id, "points": [list(point) for point in points]} for floor_id, points in polylines
            ],
            "checkpoints": [
                {"floor_id": cp.floor_id, "position": list(cp.position), "kind": cp.kind} for cp in checkpoints
            ],
            "next_index": next_index,
        }

    def _speech(self, speech_id: str) -> None:
        """Cached audio in one piece, or ElevenLabs audio passed through as it arrives (cached only when complete)."""
        entry = self.server.speech.get(speech_id)
        eleven = self.server.eleven
        if entry is None or eleven is None:
            raise RequestError(404, "Unknown speech id.")
        text, language = entry
        cached = self.server.speech.cached_audio(text, language)
        if cached is not None:
            self._send_bytes(200, cached, "audio/mpeg")
            return
        stream = eleven.stream_speech(text, language)
        try:
            first = next(stream, b"")
        except VoiceServiceError as error:
            raise RequestError(502, str(error)) from error
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Connection", "close")  # no Content-Length: the client reads until the stream ends
        self.end_headers()
        audio = bytearray()
        try:
            for chunk in itertools.chain([first], stream):
                audio += chunk
                self.wfile.write(chunk)
                self.wfile.flush()
        except VoiceServiceError as error:  # the clip stops early; the client may retry or use another output
            print(f"Speech stream stopped: {error}", file=sys.stderr, flush=True)
            return
        finally:
            stream.close()
        self.server.speech.store_audio(text, language, bytes(audio))

    def _speech_items(self, texts: list[str], language: str | None, pinned: bool = False) -> list[dict]:
        """Each text with the URL of its audio, or a null audio URL when ElevenLabs is off."""
        if self.server.eleven is None:
            return [{"text": text, "audio": None} for text in texts]
        return [
            {"text": text, "audio": f"/api/speech/{self.server.speech.add(text, language, pinned)}"} for text in texts
        ]

    def _filler_items(self) -> dict[str, list[dict]]:
        with self.server.fillers_lock:
            if not self.server.fillers:
                self.server.fillers = {
                    language: self._speech_items(texts, language, pinned=True) for language, texts in FILLERS.items()
                }
            return self.server.fillers

    def _find_session(self, session_id: object) -> VoiceSession:
        with self.server.sessions_lock:
            session = self.server.sessions.get(session_id) if isinstance(session_id, str) else None
        if session is None:
            raise RequestError(404, "Unknown session. Start one with POST /api/session.")
        return session

    def _query(self, name: str) -> str | None:
        values = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get(name)
        return values[0] if values else None

    def _body(self, limit: int) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as error:
            raise RequestError(400, "Content-Length must be a number.") from error
        if length > limit:
            raise RequestError(413, f"The request body is larger than {limit} bytes.")
        return self.rfile.read(max(length, 0))

    def _json_body(self) -> dict:
        raw = self._body(MAX_JSON_BYTES)
        if not raw.strip():
            return {}
        try:
            body = json.loads(raw)
        except ValueError as error:
            raise RequestError(400, "The body must be JSON.") from error
        if not isinstance(body, dict):
            raise RequestError(400, "The body must be a JSON object.")
        return body

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _send_bytes(self, status: int, body: bytes, content_type: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)


def make_server(
    building_path: Path, output_directory: Path, host: str = "127.0.0.1", port: int = 8765,
    eleven: ElevenLabs | None = None, agent_factory: AgentFactory = default_agent,
) -> VoiceServer:
    """A bound server for one building, not yet serving. Port 0 picks a free port; a bad building fails here."""
    building = building_payload(BuildingMap.load(building_path))
    return VoiceServer((host, port), building_path, output_directory, building, eleven, agent_factory)


def main() -> None:
    parser = argparse.ArgumentParser(prog="final_agent.voice", description="Voice backend API for one building.")
    parser.add_argument("building", type=Path, help="building directory (with building.json) or a building.json file")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIRECTORY, help="where route images and edits go")
    parser.add_argument("--cert", type=Path, help="TLS certificate (PEM); phones need HTTPS for the microphone")
    parser.add_argument("--key", type=Path, help="TLS private key (PEM)")
    arguments = parser.parse_args()
    if bool(arguments.cert) != bool(arguments.key):
        parser.error("--cert and --key must be given together")
    eleven = ElevenLabs.from_env()
    try:
        server = make_server(arguments.building, arguments.output, arguments.host, arguments.port, eleven=eleven)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit(f"Cannot start the voice guide: {error}") from error
    scheme = "http"
    if arguments.cert:
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(arguments.cert, arguments.key)
        except OSError as error:  # ssl.SSLError is an OSError too
            raise SystemExit(f"Cannot load the TLS certificate: {error}") from error
        server.socket = context.wrap_socket(server.socket, server_side=True)
        scheme = "https"
    print(f"Talk to your building: {scheme}://{arguments.host}:{server.server_address[1]}/", flush=True)
    print("ElevenLabs: on" if eleven else "ElevenLabs: off (text-only API)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
