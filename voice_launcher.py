"""Console round-trip tester for the voice backend.

ElevenLabs is deliberately only an audio boundary here: speech-to-text and
text-to-speech. Building data, navigation state, and test responses stay local.
When Anthropic credentials are configured, the same console uses BuildingAgent.
"""

from __future__ import annotations

import ctypes
import io
import json
import os
import re
import sys
import tempfile
import uuid
import wave
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

import numpy as np

if os.name == "nt":
    try:
        import sounddevice as sd
    except (ImportError, OSError):
        sd = None
else:
    sd = None

from final_agent.building_map import BuildingMap, MapError
from final_agent.guidance import Guidance
from final_agent.voice import ElevenLabs, VoiceServiceError, VoiceSession, default_agent

CREDENTIAL_TARGET = "TalkToYourBuilding.ElevenLabs"
DEMO_BUILDING = Path("data/dev/proc-factory-dev-003")
YES = {"yes", "yep", "yeah", "ja"}
NO = {"no", "nope", "nein"}
ROUTE_WORDS = ("take me", "guide me", "route", "navigate", "bring me", "bring mich", "führ mich")


class _Credential(ctypes.Structure):
    _fields_ = [
        ("flags", wintypes.DWORD),
        ("type", wintypes.DWORD),
        ("target_name", wintypes.LPWSTR),
        ("comment", wintypes.LPWSTR),
        ("last_written", wintypes.FILETIME),
        ("blob_size", wintypes.DWORD),
        ("blob", ctypes.POINTER(ctypes.c_ubyte)),
        ("persist", wintypes.DWORD),
        ("attribute_count", wintypes.DWORD),
        ("attributes", ctypes.c_void_p),
        ("target_alias", wintypes.LPWSTR),
        ("user_name", wintypes.LPWSTR),
    ]


def _windows_credential(target: str) -> str | None:
    """Read a generic credential stored for the current Windows user."""
    if os.name != "nt":
        return None
    credential_pointer = ctypes.POINTER(_Credential)()
    read = ctypes.windll.advapi32.CredReadW
    read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    read.restype = wintypes.BOOL
    if not read(target, 1, 0, ctypes.byref(credential_pointer)):  # CRED_TYPE_GENERIC
        return None
    try:
        credential = credential_pointer.contents
        raw = ctypes.string_at(credential.blob, credential.blob_size)
        return raw.decode("utf-16-le").rstrip("\x00")
    finally:
        ctypes.windll.advapi32.CredFree(credential_pointer)


def _resource(relative: Path) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / relative


def _output_directory() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.cwd())
    output = base / "TalkToYourBuilding" / "voice-output"
    output.mkdir(parents=True, exist_ok=True)
    return output


def _mci(command: str) -> str:
    """Run one Windows Media Control Interface command or raise a readable error."""
    result = ctypes.create_unicode_buffer(512)
    code = ctypes.windll.winmm.mciSendStringW(command, result, len(result), None)
    if code:
        message = ctypes.create_unicode_buffer(512)
        ctypes.windll.winmm.mciGetErrorStringW(code, message, len(message))
        raise RuntimeError(message.value or f"Windows audio error {code}")
    return result.value


def _temporary_path(suffix: str) -> Path:
    descriptor, name = tempfile.mkstemp(prefix="talk-building-", suffix=suffix)
    os.close(descriptor)
    path = Path(name)
    path.unlink(missing_ok=True)
    return path


@dataclass(frozen=True)
class CapturedAudio:
    wav: bytes
    duration_s: float
    peak_percent: float
    gain: float


def _prepare_wav(pcm: bytes, sample_rate: int) -> CapturedAudio:
    """Remove DC offset and raise quiet signed-16-bit mono input to a useful STT level."""
    if not pcm or len(pcm) % 2:
        raise RuntimeError("The microphone recording was empty.")
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    samples -= float(samples.mean())
    peak = float(np.max(np.abs(samples)))
    if peak < 32:
        raise RuntimeError(
            "The selected microphone returned silence. Use /mics and /mic NUMBER to choose another input."
        )
    gain = min(12.0, 28000.0 / peak)
    prepared = np.clip(np.rint(samples * gain), -32768, 32767).astype("<i2").tobytes()
    output = io.BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(sample_rate)
        recording.writeframes(prepared)
    return CapturedAudio(output.getvalue(), len(samples) / sample_rate, peak / 32767.0 * 100.0, gain)


def _paired_input_id(
    inputs: list[tuple[int, dict]], devices: list, preferred: int, output_id: object,
) -> int:
    """Prefer the capture endpoint whose name matches the active output; otherwise keep the default input."""
    if not isinstance(output_id, int) or not 0 <= output_id < len(devices):
        return preferred
    output_name = str(devices[output_id]["name"]).casefold()
    return next(
        (device_id for device_id, device in inputs if str(device["name"]).casefold() == output_name), preferred
    )


class MicrophoneRecorder:
    """Selectable push-to-talk input using PortAudio's modern Windows WASAPI backend."""

    def __init__(self) -> None:
        if sd is None:
            raise RuntimeError("Microphone recording requires Windows and the sounddevice package.")
        try:
            host_apis = list(sd.query_hostapis())
            devices = list(sd.query_devices())
        except Exception as error:
            raise RuntimeError(f"Windows audio devices could not be enumerated: {error}") from error
        wasapi = next((index for index, item in enumerate(host_apis) if "WASAPI" in item["name"]), None)
        all_inputs = [
            (index, dict(device))
            for index, device in enumerate(devices)
            if int(device["max_input_channels"]) > 0
        ]
        self.devices = [item for item in all_inputs if wasapi is not None and item[1]["hostapi"] == wasapi]
        if not self.devices:
            self.devices = all_inputs
        if not self.devices:
            raise RuntimeError("Windows reports no recording devices.")
        preferred = host_apis[wasapi]["default_input_device"] if wasapi is not None else sd.default.device[0]
        # Windows often keeps the laptop array as its default input even while a Bluetooth headset is in use.
        # Pair an input with the active output by endpoint name so speech follows the device the user is wearing.
        output_id = host_apis[wasapi]["default_output_device"] if wasapi is not None else sd.default.device[1]
        preferred = _paired_input_id(self.devices, devices, preferred, output_id)
        self.default_selected = next(
            (position for position, (device_id, _) in enumerate(self.devices) if device_id == preferred), 0
        )
        self.selected = self.default_selected

    @property
    def name(self) -> str:
        return str(self.devices[self.selected][1]["name"])

    def describe(self) -> list[str]:
        lines = []
        for position, (_, device) in enumerate(self.devices, 1):
            active = " [active]" if position - 1 == self.selected else ""
            lines.append(f"  {position}. {device['name']}{active}")
        return lines

    def select(self, reference: str) -> str:
        if reference.casefold() == "auto":
            self.selected = self.default_selected
            return self.name
        if reference.isdigit() and 1 <= int(reference) <= len(self.devices):
            self.selected = int(reference) - 1
            return self.name
        matches = [
            position for position, (_, device) in enumerate(self.devices)
            if reference.casefold() in str(device["name"]).casefold()
        ]
        if len(matches) != 1:
            raise ValueError("Choose one of the numbers shown by /mics.")
        self.selected = matches[0]
        return self.name

    def record(self) -> CapturedAudio:
        device_id, device = self.devices[self.selected]
        sample_rate = int(device["default_samplerate"])
        chunks: list[bytes] = []
        warnings: list[str] = []

        def receive(indata, frames, time_info, status) -> None:
            del frames, time_info
            chunks.append(bytes(indata))
            if status:
                warnings.append(str(status))

        try:
            with sd.RawInputStream(
                samplerate=sample_rate, device=device_id, channels=1, dtype="int16", callback=receive
            ):
                input(f"recording from {self.name}... speak now, then press Enter to stop ")
        except sd.PortAudioError as error:
            raise RuntimeError(
                f"Windows could not open {self.name}. Check Settings > Privacy & security > Microphone, "
                "then use /mics to choose an available input."
            ) from error
        recording = _prepare_wav(b"".join(chunks), sample_rate)
        if recording.duration_s < 0.4:
            raise RuntimeError("The recording was too short. Use /talk and speak before pressing Enter.")
        if warnings:
            print(f"[microphone warning: {warnings[-1]}]")
        return recording


def _play_mp3(audio: bytes) -> None:
    """Play a complete MP3 response through the default Windows output device."""
    path = _temporary_path(".mp3")
    path.write_bytes(audio)
    alias = f"speech{uuid.uuid4().hex}"
    try:
        _mci(f'open "{path}" type mpegvideo alias {alias}')
        _mci(f"play {alias} wait")
    finally:
        try:
            _mci(f"close {alias}")
        finally:
            path.unlink(missing_ok=True)


def _current_space(context: str) -> str | None:
    match = re.search(r"\(space ([^)]+)\)", context)
    return match.group(1) if match else None


class LocalBackendAgent:
    """Deterministic test intelligence that proves all text and data stay in our backend."""

    def __init__(self, building_map: BuildingMap, guidance: Guidance) -> None:
        self.building_map = building_map
        self.guidance = guidance

    def ask(self, text: str) -> str:
        context, _, request = text.partition("\n")
        request = request.strip()
        lowered = request.casefold().rstrip(".?!")
        if self.guidance.active and lowered in YES:
            self.guidance.stop()
            return ""
        if self.guidance.active and lowered in NO:
            return "Okay, I'll keep the navigation running."

        destination = self._named_space(request)
        if destination is not None and any(word in lowered for word in ROUTE_WORDS):
            return self._start_route(context, destination)
        if destination is not None:
            floor = self.building_map.floor_name(destination["floor_id"])
            return f"{destination['name']} is on {floor}."
        if "how many floors" in lowered:
            return f"Our building data contains {len(self.building_map.floors)} floors."
        if "building name" in lowered or lowered == "what building is this":
            return f"Our building data says this is {self.building_map.data['building']['name']}."
        if self.guidance.active:
            return f"Our backend received: {request}. Do you want me to stop navigation?"
        return f"Our backend received: {request}"

    def _named_space(self, request: str) -> dict | None:
        lowered = request.casefold()
        matches = [space for space in self.building_map.spaces.values() if space["name"].casefold() in lowered]
        return max(matches, key=lambda space: len(space["name"])) if matches else None

    def _start_route(self, context: str, destination: dict) -> str:
        start = _current_space(context)
        if start is None:
            return "Set a test position first with slash position and a room name."
        try:
            route = self.building_map.route(start, destination["id"])
            self.guidance.start(route)
        except MapError as error:
            return str(error)
        distance = max(5, 5 * round(route.length_m / 5))
        return f"Route ready. {destination['name']} is about {distance} metres away."


def _local_agent(building_map: BuildingMap, output_directory: Path, guidance: Guidance) -> LocalBackendAgent:
    del output_directory
    return LocalBackendAgent(building_map, guidance)


def _emit(session: VoiceSession, eleven: ElevenLabs | None, texts: list[str]) -> None:
    for text in texts:
        print(f"backend> {text}")
        if eleven is None:
            continue
        try:
            _play_mp3(b"".join(eleven.stream_speech(text, session.language)))
        except (OSError, RuntimeError, VoiceServiceError) as error:
            print(f"[speech playback failed: {error}]")


def _set_position(session: VoiceSession, reference: str, eleven: ElevenLabs | None) -> None:
    try:
        space_id = session.building_map.resolve_space(reference)
        space = session.building_map.spaces[space_id]
        floor_level = session.building_map.floor_level(space["floor_id"])
        x_m, y_m = session.building_map.anchor(space_id)
        queued = session.update({"floor_level": floor_level, "x": x_m, "y": y_m, "accuracy_m": 1.0})
    except (MapError, ValueError) as error:
        print(f"[position rejected: {error}]")
        return
    print(f"[position: {space['name']} on {session.building_map.floor_name(space['floor_id'])}]")
    _emit(session, eleven, queued)


def _help() -> None:
    print(
        "Commands:\n"
        "  /talk                 record from the microphone; press Enter to stop\n"
        "  /mics                 list microphone inputs and show the active one\n"
        "  /mic NUMBER           select a microphone shown by /mics\n"
        "  /position ROOM        set the local position oracle, for example /position Office 0.23\n"
        "  /state                print backend session state\n"
        "  /help                 show this help\n"
        "  /quit                 exit\n"
        "Anything else is sent as typed text. Responses are printed and spoken."
    )


def main() -> None:
    secret = os.environ.get("ELEVENLABS_API_KEY", "").strip() or _windows_credential(CREDENTIAL_TARGET)
    eleven = ElevenLabs(secret) if secret else None
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    factory = default_agent if has_anthropic else _local_agent
    try:
        microphone = MicrophoneRecorder()
        microphone_error = None
    except (OSError, RuntimeError) as error:
        microphone = None
        microphone_error = str(error)
    try:
        session = VoiceSession(BuildingMap.load(_resource(DEMO_BUILDING)), _output_directory(), factory)
    except Exception as error:
        print(f"Cannot start the backend tester: {error}")
        input("Press Enter to close.")
        raise SystemExit(1) from error

    print("Talk to Your Building — backend round-trip tester")
    print(f"ElevenLabs STT/TTS: {'on' if eleven else 'off (typed text only)'}")
    print(f"Intelligence: {'Anthropic' if has_anthropic else 'local deterministic test backend'}")
    print(f"Microphone: {microphone.name if microphone else 'unavailable'}")
    if microphone_error:
        print(f"[microphone error: {microphone_error}]")
    print("No browser UI is bundled. Type /help for commands.\n")
    while True:
        try:
            entered = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not entered:
            continue
        if entered.casefold() in {"/quit", "/exit"}:
            break
        if entered.casefold() == "/help":
            _help()
            continue
        if entered.casefold() == "/state":
            print(json.dumps(session.state(), ensure_ascii=False, indent=2))
            continue
        if entered.casefold() in {"/mic", "/mics"}:
            if microphone is None:
                print(f"[microphone unavailable: {microphone_error}]")
            else:
                print("Microphone inputs:")
                print("\n".join(microphone.describe()))
                print("Select one with /mic NUMBER.")
            continue
        if entered.casefold().startswith("/mic "):
            if microphone is None:
                print(f"[microphone unavailable: {microphone_error}]")
                continue
            try:
                print(f"[microphone: {microphone.select(entered.partition(' ')[2].strip())}]")
            except ValueError as error:
                print(f"[microphone selection failed: {error}]")
            continue
        if entered.casefold().startswith("/position "):
            _set_position(session, entered.partition(" ")[2].strip(), eleven)
            continue
        language = None
        text = entered
        if entered.casefold() == "/talk":
            if eleven is None:
                print("[voice is unavailable: configure the ElevenLabs credential]")
                continue
            if microphone is None:
                print(f"[microphone unavailable: {microphone_error}]")
                continue
            try:
                recording = microphone.record()
                print(
                    f"[captured {recording.duration_s:.1f}s; input peak {recording.peak_percent:.1f}%; "
                    f"gain {recording.gain:.1f}x]"
                )
                text, language = eleven.transcribe(recording.wav, "audio/wav")
            except (OSError, RuntimeError, VoiceServiceError) as error:
                print(f"[transcription failed: {error}]")
                continue
            if not text:
                print(
                    "[no words recognized. Speak while the recording message is visible; if the input peak "
                    "is very low, use /mics and /mic NUMBER.]"
                )
                continue
            print(f"heard[{language or '?'}]> {text}")
        _emit(session, eleven, session.handle_text(text, language))
    print("Backend tester stopped.")


if __name__ == "__main__":
    main()
