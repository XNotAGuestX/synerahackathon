"""Voice guide offline: turns and guidance through VoiceSession, the ElevenLabs client and the HTTP API.

The model is a ScriptedClient and ElevenLabs is faked, so nothing here reaches a paid endpoint.
"""

import contextlib
import http.client
import io
import json
import math
import tempfile
import threading
import unittest
import urllib.error
import wave
from pathlib import Path
from unittest import mock

import anthropic
import httpx2

from final_agent.agent import BuildingAgent, MissingCredentialsError
from final_agent.building_map import BuildingMap
from final_agent.guidance import Guidance, instruction, route_checkpoints
from final_agent.voice import (
    AI_OVERLOADED, AI_UNREACHABLE, FILLERS, NO_AI_SERVICE, ElevenLabs, VoiceHandler, VoiceServiceError, VoiceSession,
    make_server,
)
from test_hull import ScriptedClient, call, reply, say
from voice_launcher import LocalBackendAgent, _paired_input_id, _prepare_wav

BUILDING = Path(__file__).resolve().parents[1] / "data" / "dev" / "proc-factory-dev-003"
P = "proc-factory-dev-003-"
WALKS = {}  # walking lengths of the unchanged building, shared by every map here (as in test_guidance)
ROUTE_SPEECH = "Sure, Kitchen 1.08 is up the Office staircase."
ROUTE_TURN = [
    reply(call("find_route", start=P + "F0-S023", destination=P + "F1-S008")),
    reply(call("start_guidance")),
    reply(say(ROUTE_SPEECH)),
]
CONFIRM_PROMPT = " Tell me when you're there."
ARRIVED = "You've arrived — this is Kitchen 1.08."


def new_map() -> BuildingMap:
    return BuildingMap.load_cached(BUILDING, WALKS)


def start_position() -> dict:
    """A live fix in the room where the route starts."""
    x_m, y_m = new_map().anchor(P + "F0-S023")
    return {"floor_level": 0, "x": x_m, "y": y_m, "accuracy_m": 2.0}


def scripted_factory(*turns: list):
    """An agent factory whose model answers from the given turns, one list per user message."""
    client = ScriptedClient(list(turns))

    def factory(building_map, output_directory, guidance):
        return BuildingAgent(building_map, output_directory, client, guidance=guidance, voice=True)

    return factory, client


class FailingAgent:
    """An agent whose every question fails with the given error, as the model does when it cannot be reached."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def ask(self, text: str) -> str:
        raise self.error


def raising(error: Exception):
    """A request handler that fails with `error`, as a phone that hangs up mid-answer does."""

    def handle() -> None:
        raise error

    return handle


class FakeEleven:
    """Stands in for ElevenLabs: a fixed transcript, two MP3-like chunks per clip, and a count of speech requests."""

    def __init__(self) -> None:
        self.stream_calls = 0

    def transcribe(self, audio: bytes, content_type: str) -> tuple[str, str]:
        return "Where is the coffee machine?", "en"

    def stream_speech(self, text: str, language: str | None):
        self.stream_calls += 1
        yield b"ID3"
        yield b"ID3"


class FakeOpener:
    """Stands in for urllib.request.urlopen: records each request and answers with a fixed body or error."""

    def __init__(self, body: bytes = b"", error: Exception | None = None) -> None:
        self.body, self.error, self.requests = body, error, []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        return io.BytesIO(self.body)


class VoiceSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.output = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.output.cleanup()

    def session(self, *turns: list) -> tuple[VoiceSession, ScriptedClient]:
        factory, client = scripted_factory(*turns)
        return VoiceSession(new_map(), Path(self.output.name), factory), client

    def test_voice_agent_has_the_spoken_interruption_and_fallback_rules(self):
        session, _ = self.session()
        prompt = session.agent.system[0]["text"]
        self.assertIn("usually one or two sentences", prompt)
        self.assertIn("ask whether to stop the navigation", prompt)
        self.assertIn("ask before replacing the current route", prompt)
        self.assertIn("waits for the user to confirm each checkpoint", prompt)
        self.assertIn("never read it out", prompt)
        self.assertTrue(
            {"start_guidance", "stop_guidance", "guidance_next_step", "set_guidance_options"}
            <= {tool.name for tool in session.agent.tools}
        )

    def test_voice_turn_routes_starts_guidance_and_speaks_the_first_step(self):
        session, client = self.session(ROUTE_TURN)
        speech = session.handle_text("Take me to Kitchen 1.08")
        first = route_checkpoints(session.building_map, session.building_map.last_route)[0]
        self.assertEqual(speech, [ROUTE_SPEECH, instruction(first, 0, session.building_map) + CONFIRM_PROMPT])
        sent = session.agent.messages[0]["content"]
        self.assertEqual(sent.split("\n"), [
            "[app: language=en; position=unknown, tracking none; guidance: off]", "Take me to Kitchen 1.08",
        ])
        self.assertEqual(client.turns, [])

    def test_short_answers_during_guidance_skip_the_model(self):
        session, client = self.session(ROUTE_TURN, [reply(say("MODEL"))])
        session.handle_text("Take me to Kitchen 1.08")
        second = route_checkpoints(session.building_map, session.building_map.last_route)[1]
        step = [instruction(second, 1, session.building_map) + CONFIRM_PROMPT]
        self.assertEqual(session.handle_text("Okay!"), step)
        self.assertEqual(session.handle_text("repeat"), step)
        self.assertEqual(session.handle_text("  "), [])
        self.assertEqual(session.handle_text("Stop."), ["Okay, stopping navigation."])
        self.assertFalse(session.guidance.active)
        self.assertEqual(len(client.turns), 1)  # the spare reply was never asked for

    def test_noise_and_silence_say_nothing_and_skip_the_model(self):
        session, client = self.session(ROUTE_TURN, [reply(say("MODEL"))])
        session.handle_text("Take me to Kitchen 1.08")
        second = route_checkpoints(session.building_map, session.building_map.last_route)[1]
        for text in ("(background noise)", "", "[noise] (music)"):
            with self.subTest(text=text):
                self.assertEqual(session.handle_text(text), [])
        self.assertEqual(len(client.turns), 1)  # no model call, and guidance did not move on
        step = [instruction(second, 1, session.building_map) + CONFIRM_PROMPT]
        self.assertEqual(session.handle_text("(music) I'm here [noise]"), step)  # tags go, the command still counts

    def test_a_short_answer_to_an_agent_question_goes_to_the_model(self):
        session, client = self.session(
            ROUTE_TURN, [reply(say("Which lift do you mean?"))], [reply(say("The one by the entrance."))],
        )
        session.handle_text("Take me to Kitchen 1.08")
        self.assertEqual(session.handle_text("Where is the lift?"), ["Which lift do you mean?"])
        self.assertEqual(session.handle_text("ok"), ["The one by the entrance."])
        self.assertTrue(session.agent.messages[-2]["content"].endswith("\nok"))
        self.assertEqual(session.guidance.status()["progress"][0], 0)  # the answer did not advance guidance
        self.assertEqual(client.turns, [])

    def test_ok_and_im_here_after_an_agent_statement_advance_guidance(self):
        session, client = self.session(ROUTE_TURN, [reply(say("The lift is by the entrance."))])
        session.handle_text("Take me to Kitchen 1.08")
        steps = route_checkpoints(session.building_map, session.building_map.last_route)
        session.handle_text("Where is the lift?")
        self.assertEqual(session.handle_text("ok"), [instruction(steps[1], 1, session.building_map) + CONFIRM_PROMPT])
        self.assertEqual(session.handle_text("I'm here."), [instruction(steps[2], 2, session.building_map)])
        self.assertEqual(client.turns, [])

    def test_say_again_repeats_the_last_reply_or_step_without_the_model(self):
        session, client = self.session(ROUTE_TURN, [reply(say("The lift is by the entrance."))])
        session.handle_text("Take me to Kitchen 1.08")
        steps = route_checkpoints(session.building_map, session.building_map.last_route)
        session.handle_text("Where is the lift?")
        self.assertEqual(session.handle_text("say again"), ["The lift is by the entrance."])
        session.handle_text("I'm here")
        # Guidance spoke since the reply, so "say again" repeats the step rather than the older reply.
        step = [instruction(steps[1], 1, session.building_map) + CONFIRM_PROMPT]
        self.assertEqual(session.handle_text("say again"), step)
        self.assertEqual(client.turns, [])

    def test_say_again_without_guidance_repeats_the_last_reply(self):
        session, client = self.session([reply(say("The printer is on floor 1."))])
        session.handle_text("Where is the printer?")
        self.assertEqual(session.handle_text("say again"), ["The printer is on floor 1."])
        self.assertEqual(client.history_lengths, [1])  # only the question reached the model

    def test_positions_advance_guidance_and_bad_positions_are_refused(self):
        session, _ = self.session(ROUTE_TURN)
        session.handle_text("Take me to Kitchen 1.08")
        checkpoints = route_checkpoints(session.building_map, session.building_map.last_route)
        session.update(start_position())  # a starting fix establishes live tracking without skipping the first door
        self.assertEqual(session.state()["position"]["space_id"], P + "F0-S023")
        said = []
        for checkpoint in checkpoints:
            if checkpoint.kind == "connector":  # a connector counts once the user is on its far floor
                level = session.building_map.floor_level(checkpoint.target_floor_id)
                x_m, y_m = session.building_map.anchor(checkpoint.next_space_id)
            else:
                level = session.building_map.floor_level(checkpoint.floor_id)
                x_m, y_m = checkpoint.position
            said += session.update({"floor_level": level, "x": x_m, "y": y_m, "accuracy_m": 1.0})
        self.assertFalse(session.guidance.active)
        self.assertEqual(said[-1], ARRIVED)
        for bad in (
            {"floor_level": "0", "x": 1, "y": 1}, {"floor_level": True, "x": 1, "y": 1},
            {"floor_level": 0, "x": math.nan, "y": 1}, {"floor_level": 0, "x": 1, "y": 1, "accuracy_m": -1},
            {"floor_level": 9, "x": 1, "y": 1}, {"floor_level": 0, "y": 1},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                session.update(bad)

    def test_model_failures_become_one_spoken_sentence(self):
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        failures = [
            (MissingCredentialsError("no key"), NO_AI_SERVICE),
            (anthropic.AuthenticationError("bad key", response=httpx2.Response(401, request=request), body=None),
             NO_AI_SERVICE),
            (anthropic.RateLimitError("busy", response=httpx2.Response(429, request=request), body=None),
             AI_OVERLOADED),
            (anthropic.APIConnectionError(request=request), AI_UNREACHABLE),
        ]
        for error, sentence in failures:
            with self.subTest(error=type(error).__name__):
                session = VoiceSession(new_map(), Path(self.output.name), lambda *_, error=error: FailingAgent(error))
                self.assertEqual(session.handle_text("Where is the printer?"), [sentence])

    def test_without_an_agent_the_session_still_answers(self):
        def broken(*_):
            raise RuntimeError("no profile")

        session = VoiceSession(new_map(), Path(self.output.name), broken)
        self.assertIsNone(session.agent)
        self.assertEqual(session.agent_error, "RuntimeError: no profile")
        self.assertEqual(session.handle_text("Where is the printer?"), [NO_AI_SERVICE])


class LocalBackendAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.map = new_map()
        self.guidance = Guidance(self.map)
        self.agent = LocalBackendAgent(self.map, self.guidance)

    def ask(self, text: str, space_id: str | None = None) -> str:
        position = "unknown" if space_id is None else f"Office 0.23 (space {space_id})"
        return self.agent.ask(f"[app: position={position}; guidance: off]\n{text}")

    def test_local_backend_owns_answers_and_echoes_unknown_text(self):
        self.assertEqual(self.ask("What building is this?"), "Our building data says this is Fertigung Ost 27.")
        self.assertEqual(self.ask("Where is Kitchen 1.08?"), "Kitchen 1.08 is on Floor 1.")
        self.assertEqual(self.ask("round trip test"), "Our backend received: round trip test")

    def test_local_backend_starts_guidance_from_our_position_context(self):
        response = self.ask("Take me to Kitchen 1.08", P + "F0-S023")
        self.assertTrue(response.startswith("Route ready. Kitchen 1.08 is about "))
        self.assertTrue(self.guidance.active)
        self.assertEqual(self.guidance.route.start_space_id, P + "F0-S023")
        self.assertEqual(self.guidance.route.destination_space_id, P + "F1-S008")


class VoiceLauncherAudioTests(unittest.TestCase):
    def test_active_output_pairs_with_its_capture_endpoint(self):
        inputs = [(4, {"name": "Laptop array"}), (7, {"name": "Headset"})]
        devices = [{"name": "unused"}, {"name": "Headset"}]
        self.assertEqual(_paired_input_id(inputs, devices, 4, 1), 7)
        self.assertEqual(_paired_input_id(inputs, devices, 4, -1), 4)

    def test_quiet_pcm_is_normalised_and_wrapped_as_mono_wav(self):
        pcm = ((-1000).to_bytes(2, "little", signed=True) + (1000).to_bytes(2, "little", signed=True)) * 800
        captured = _prepare_wav(pcm, 16000)
        self.assertAlmostEqual(captured.duration_s, 0.1)
        self.assertGreater(captured.gain, 1.0)
        with wave.open(io.BytesIO(captured.wav), "rb") as recording:
            self.assertEqual((recording.getnchannels(), recording.getsampwidth(), recording.getframerate()), (1, 2, 16000))
            self.assertEqual(recording.getnframes(), 1600)

    def test_silent_pcm_is_rejected_before_upload(self):
        with self.assertRaisesRegex(RuntimeError, "returned silence"):
            _prepare_wav(b"\0\0" * 800, 16000)


class ElevenLabsTests(unittest.TestCase):
    def test_transcribe_posts_the_audio_as_multipart_and_normalises_the_language(self):
        opener = FakeOpener(json.dumps({"text": "  Wo ist der Drucker?  ", "language_code": "deu"}).encode())
        text, language = ElevenLabs("secret-key", opener=opener).transcribe(b"WEBM-BYTES", "audio/webm;codecs=opus")
        self.assertEqual((text, language), ("Wo ist der Drucker?", "de"))
        request, timeout = opener.requests[0]
        self.assertEqual(request.full_url, "https://api.elevenlabs.io/v1/speech-to-text")
        self.assertEqual(request.headers["Xi-api-key"], "secret-key")
        self.assertTrue(request.headers["Content-type"].startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="model_id"\r\n\r\nscribe_v2\r\n', request.data)
        self.assertIn(b'name="tag_audio_events"\r\n\r\nfalse\r\n', request.data)
        self.assertIn(b'filename="speech.webm"\r\nContent-Type: audio/webm;codecs=opus\r\n\r\nWEBM-BYTES', request.data)
        self.assertEqual(timeout, 30)

    def test_stream_speech_posts_the_text_and_yields_chunks(self):
        audio = b"ID3" * 5000  # 15000 bytes: one full 8192-byte chunk, then the rest
        opener = FakeOpener(audio)
        chunks = list(ElevenLabs("secret-key", opener=opener).stream_speech("Der Drucker ist in Büro 1.08.", "de"))
        self.assertEqual(b"".join(chunks), audio)
        self.assertEqual([len(chunk) for chunk in chunks], [8192, 6808])
        request, _ = opener.requests[0]
        self.assertEqual(
            request.full_url,
            "https://api.elevenlabs.io/v1/text-to-speech/JBFqnCBsd6RMkjVDRZzb/stream?output_format=mp3_44100_128",
        )
        body = json.loads(request.data)
        self.assertEqual((body["model_id"], body["language_code"]), ("eleven_flash_v2_5", "de"))
        self.assertEqual(request.headers["Accept"], "audio/mpeg")

    def test_failures_name_the_status_or_reason_but_never_the_key(self):
        url = "https://api.elevenlabs.io/v1/speech-to-text"
        http_error = urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b'{"detail": "invalid"}'))
        with self.assertRaisesRegex(VoiceServiceError, r'^ElevenLabs 401: \{"detail": "invalid"\}$'):
            ElevenLabs("secret-key", opener=FakeOpener(error=http_error)).transcribe(b"x", "audio/webm")
        unreachable = urllib.error.URLError("no route to host")
        with self.assertRaisesRegex(VoiceServiceError, "^Cannot reach ElevenLabs: no route to host$"):
            list(ElevenLabs("secret-key", opener=FakeOpener(error=unreachable)).stream_speech("Hallo", "de"))


class VoiceHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.output = tempfile.TemporaryDirectory()
        self.servers = []

    def tearDown(self) -> None:
        for server in self.servers:
            server.shutdown()
            server.server_close()
        self.output.cleanup()

    def start(self, eleven, *turns: list):
        factory, _ = scripted_factory(*turns)
        server = make_server(BUILDING, Path(self.output.name), port=0, eleven=eleven, agent_factory=factory)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.servers.append(server)
        return server

    def send(self, server, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=30)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.headers, response.read()
        finally:
            connection.close()

    def call_json(self, server, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        status, _, data = self.send(server, method, path, body, {"Content-Type": "application/json"})
        return status, json.loads(data)

    def test_phone_flow_over_http(self):
        eleven = FakeEleven()
        server = self.start(eleven, ROUTE_TURN)
        status, _, root = self.send(server, "GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(root)["ui"], False)

        status, started = self.call_json(server, "POST", "/api/session", {})
        sid = started["session"]
        self.assertEqual(status, 200)
        self.assertTrue(started["stt"] and started["tts"] and started["agent"])
        self.assertTrue(started["speak"][0]["text"].startswith("Hi, I'm your guide for "))

        _, _, data = self.send(server, "POST", f"/api/turn?session={sid}", b"WEBM", {"Content-Type": "audio/webm"})
        turn = json.loads(data)
        self.assertEqual((turn["transcript"], turn["language"]), ("Where is the coffee machine?", "en"))
        self.assertEqual(turn["speak"][0]["text"], ROUTE_SPEECH)
        audio_url = turn["speak"][0]["audio"]
        self.assertTrue(audio_url.startswith("/api/speech/"))
        _, _, first = self.send(server, "GET", audio_url)
        _, second_headers, second = self.send(server, "GET", audio_url)
        self.assertEqual((first, second), (b"ID3ID3", b"ID3ID3"))
        self.assertEqual(second_headers["Content-Length"], "6")
        self.assertEqual(eleven.stream_calls, 1)  # the second request came from the cache

        status, state = self.call_json(server, "POST", "/api/update", {"session": sid, "position": start_position()})
        self.assertEqual(state["state"]["position"]["space_id"], P + "F0-S023")
        status, route = self.call_json(server, "GET", f"/api/route?session={sid}")
        next_step = state["state"]["guidance"]["next"]["index"]
        self.assertEqual((route["next_index"], route["checkpoints"][0]["kind"]), (next_step, "door"))
        self.assertEqual(set(route["polylines"][0]), {"floor_id", "points"})

        # Only ROUTE_TURN is scripted, so a model call here would fail the request.
        status, said = self.call_json(server, "POST", "/api/text", {"session": sid, "text": "Okay!"})
        self.assertEqual((status, len(said["speak"]), said["transcript"]), (200, 1, "Okay!"))

        self.assertEqual(self.call_json(server, "GET", "/api/route?session=missing")[0], 404)
        self.assertEqual(self.send(server, "POST", "/api/text", b"{not json")[0], 400)
        empty = self.send(server, "POST", f"/api/turn?session={sid}", b"", {"Content-Type": "audio/webm"})
        self.assertEqual(empty[0], 400)

    def test_api_only_walk_uses_positions_or_spoken_checkpoint_confirmations(self):
        interruption = "The workshop closes at six. Do you want me to stop navigation?"
        live = self.start(None, ROUTE_TURN, [reply(say(interruption))])
        _, started = self.call_json(live, "POST", "/api/session", {})
        live_id = started["session"]
        _, planned = self.call_json(
            live, "POST", "/api/text", {"session": live_id, "text": "Take me to Kitchen 1.08"},
        )
        self.assertTrue(planned["state"]["guidance"]["active"])

        # A question during the walk is answered without cancelling the route.
        _, answered = self.call_json(
            live, "POST", "/api/text", {"session": live_id, "text": "When does the workshop close?"},
        )
        self.assertEqual([item["text"] for item in answered["speak"]], [interruption])
        self.assertTrue(answered["state"]["guidance"]["active"])

        session = live.sessions[live_id]
        checkpoints = route_checkpoints(session.building_map, session.guidance.route)
        live_speech = []
        for checkpoint in checkpoints:
            if checkpoint.kind == "connector":
                floor_level = session.building_map.floor_level(checkpoint.target_floor_id)
                x_m, y_m = session.building_map.anchor(checkpoint.next_space_id)
            else:
                floor_level = session.building_map.floor_level(checkpoint.floor_id)
                x_m, y_m = checkpoint.position
            _, update = self.call_json(live, "POST", "/api/update", {
                "session": live_id,
                "position": {"floor_level": floor_level, "x": x_m, "y": y_m, "accuracy_m": 1.0},
            })
            live_speech += [item["text"] for item in update["speak"]]
        self.assertEqual(live_speech[-1], ARRIVED)
        self.assertFalse(update["state"]["guidance"]["active"])

        # A separate session sends no position. Every "okay" advances exactly one checkpoint.
        manual = self.start(None, ROUTE_TURN)
        _, started = self.call_json(manual, "POST", "/api/session", {})
        manual_id = started["session"]
        _, planned = self.call_json(
            manual, "POST", "/api/text", {"session": manual_id, "text": "Take me to Kitchen 1.08"},
        )
        total = planned["state"]["guidance"]["progress"][1]
        manual_speech = []
        for expected_index in range(1, total + 1):
            _, confirmed = self.call_json(
                manual, "POST", "/api/text", {"session": manual_id, "text": "okay"},
            )
            manual_speech += [item["text"] for item in confirmed["speak"]]
            if expected_index < total:
                self.assertEqual(confirmed["state"]["guidance"]["progress"][0], expected_index)
                self.assertTrue(confirmed["state"]["guidance"]["active"])
        self.assertEqual(manual_speech[-1], ARRIVED)
        self.assertFalse(confirmed["state"]["guidance"]["active"])

    def test_without_elevenlabs_speech_is_text_only(self):
        server = self.start(None, ROUTE_TURN)
        status, started = self.call_json(server, "POST", "/api/session", {})
        self.assertEqual((started["stt"], started["tts"]), (False, False))
        self.assertIsNone(started["speak"][0]["audio"])
        self.assertEqual(started["fillers"]["de"][0], {"text": FILLERS["de"][0], "audio": None})
        sid = started["session"]
        _, turn = self.call_json(server, "POST", "/api/text", {"session": sid, "text": "Take me to Kitchen 1.08"})
        self.assertEqual(turn["speak"][0], {"text": ROUTE_SPEECH, "audio": None})
        status, _, _ = self.send(server, "POST", f"/api/turn?session={sid}", b"WEBM", {"Content-Type": "audio/webm"})
        self.assertEqual(status, 503)

    def test_session_offers_thinking_fillers_in_english_and_german(self):
        eleven = FakeEleven()
        server = self.start(eleven)
        audio_urls = []
        for _ in range(2):  # two phones start sessions with the same filler: ElevenLabs is asked once
            _, started = self.call_json(server, "POST", "/api/session", {})
            self.assertEqual(set(started["fillers"]), {"en", "de"})
            for language, texts in FILLERS.items():
                self.assertEqual([item["text"] for item in started["fillers"][language]], texts)
            audio_urls.append(started["fillers"]["en"][0]["audio"])
        for url in audio_urls:
            self.assertEqual(self.send(server, "GET", url)[2], b"ID3ID3")
        self.assertEqual(eleven.stream_calls, 1)

    def test_filler_urls_are_shared_by_sessions_and_outlive_later_speech(self):
        server = self.start(FakeEleven())
        _, first = self.call_json(server, "POST", "/api/session", {})
        _, second = self.call_json(server, "POST", "/api/session", {})
        self.assertEqual(second["fillers"], first["fillers"])
        for index in range(300):
            server.speech.add(f"Reply {index}", "en")
        status, _, audio = self.send(server, "GET", first["fillers"]["en"][0]["audio"])
        self.assertEqual((status, audio), (200, b"ID3ID3"))

    def test_position_posted_during_a_turn_is_applied_by_the_next_update(self):
        server = self.start(None)
        _, started = self.call_json(server, "POST", "/api/session", {})
        sid = started["session"]
        with server.sessions[sid].lock:  # an agent turn is running
            status, busy = self.call_json(server, "POST", "/api/update", {"session": sid, "position": start_position()})
        self.assertEqual((status, busy["speak"], busy["state"]["position"]), (200, [], None))
        _, later = self.call_json(server, "POST", "/api/update", {"session": sid})
        self.assertEqual(later["state"]["position"]["space_id"], P + "F0-S023")


class VoiceHandlerTests(unittest.TestCase):
    def test_a_phone_that_hangs_up_mid_answer_gets_no_error_page_or_traceback(self):
        handler = VoiceHandler.__new__(VoiceHandler)  # no socket: only _respond and _send_json run
        handler._send_json = mock.Mock()
        for error in (ConnectionAbortedError("aborted"), ConnectionResetError("reset"), BrokenPipeError("pipe")):
            with self.subTest(error=type(error).__name__), contextlib.redirect_stderr(io.StringIO()) as printed:
                handler._respond(raising(error))
                self.assertEqual(printed.getvalue(), "")  # no traceback
        handler._send_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
