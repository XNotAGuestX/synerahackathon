# Voice control handoff

Client-neutral voice conversation on top of the existing agent, map and routing. ElevenLabs does speech-to-text (Scribe) and text-to-speech only. Turn-by-turn guidance and all building data remain in our backend. No production UI is bundled.

## Decisions

- **Audio boundary.** A client records an utterance and uploads it. ElevenLabs Scribe returns text and a language code; our backend chooses and computes the response; ElevenLabs TTS only voices that response. ElevenLabs Agents or other hosted intelligence are not used. No separate translation step exists. Deterministic guidance phrases have English and German templates; other languages fall back to English.
- **Position.** A client posts its current position to `/api/update`. The console tester exposes `/position ROOM` as an explicit oracle. A real indoor-positioning source can post the same metre-coordinate payload later.
- **No position.** Without a live position (none, or older than 15 s) guidance waits at each checkpoint for a spoken confirmation ("ok", "next", "weiter", ...). If guidance starts with confirmations off and there is no live position, all directions are read in one go.
- **No keys.** Without `ELEVENLABS_API_KEY`, `/api/text` and all deterministic guidance remain usable while speech URLs are null and `/api/turn` returns 503. Without Anthropic credentials, the production API reports that intelligence is unavailable; the separate console tester deliberately uses a labelled local deterministic responder so the audio/text round trip can still be tested.
- The production HTTP backend uses the standard library (`http.server`, `urllib`) plus the existing `anthropic` package. Only the disposable Windows console harness adds `sounddevice`, guarded by a Windows dependency marker; the backend and non-Windows test imports do not require PortAudio.

## Files and owners

| File | Responsibility |
|---|---|
| `final_agent/building_map.py` | `space_at` (point → space) |
| `final_agent/guidance.py` | Checkpoints from a route, spoken phrasing (en/de), `Guidance` state machine |
| `final_agent/tools.py` | Guidance tools, registered only when a `Guidance` is passed |
| `final_agent/agent.py` | `VOICE_PROMPT`, `BuildingAgent(..., guidance=None, voice=False)` |
| `final_agent/voice.py` | ElevenLabs client, `VoiceSession`, HTTP server, CLI `python -m final_agent.voice` |
| `voice_launcher.py` | UI-free Windows console tester, local deterministic responder, microphone capture and playback |
| `TalkToYourBuilding.spec` | Reproducible single-file Windows test executable |
| `tests/test_guidance.py`, `tests/test_voice.py` | Offline tests with fakes |

## 1. `BuildingMap.space_at`

```python
def space_at(self, floor_level: int, x_m: float, y_m: float) -> str | None:
    """Id of the space containing the point; else the nearest space within 1.5 m (standing in a doorway); else None."""
```
Uses the existing spatial index (`self._spatial_index`, built lazily like `spatial_search`) with `kind="space"`. Raises `MapError` for an unknown level or non-finite coordinates.

## 2. `final_agent/guidance.py`

Coordinates are plan metres with y up, so a counter-clockwise bend is a left turn. Everything here is deterministic. The voice session speaks the text that `drain()` returns.

```python
CHECKPOINT_RADIUS_M = 2.5      # reached this close on the same floor; a worse accuracy_m widens it, to at most MAX_ACCURACY_RADIUS_M = 6.0
DOOR_REACHED_M = 1.0           # a door is reached only in the next space or this close; accuracy does not widen this
STALE_POSITION_S = 15.0        # older position → tracking "lost"
TURN_MIN_DEGREES = 35.0        # smaller bends are not announced
TURN_MIN_SEGMENT_M = 1.5       # a bend after a shorter walk is not announced
MERGE_RADIUS_M = 2.0           # a turn this close to a neighbouring checkpoint on the same floor is dropped
OFF_ROUTE_UPDATES = 2          # consecutive fixes in a space the rest of the route does not use → reroute
DEPARTURE_WINDOW_M = 2.0       # heading changes are measured over this much path on each side
DEPARTURE_MIN_PATH_M = 0.5     # a departure turn needs this much path on both sides of the checkpoint
```

```python
@dataclass
class Checkpoint:
    kind: str                  # "turn" | "door" | "connector" | "arrival"
    floor_id: str
    position: tuple[float, float]
    space_id: str              # space walked through while approaching it
    distance_m: float          # walking distance from the previous checkpoint (or the start)
    name: str                  # door: next space; connector: its name; arrival: destination; turn: ""
    next_space_id: str | None = None    # door/connector: space entered after it
    turn: str | None = None             # turn: "left", "right", "slight left", "sharp right", ...
    connector_kind: str | None = None   # connector: "stairs" | "lift"
    target_floor_id: str | None = None  # connector: floor reached
    departure: str | None = None        # door/arrival: turn made at the previous checkpoint to head here

def route_checkpoints(building_map: BuildingMap, route: RouteResult) -> list[Checkpoint]
```
Walks are computed exactly as `viewer.route_polylines` draws them, so spoken turns match the map.
- Connector edge → `connector` at the boarding point. It is reached on the target floor.
- Space edge → `turn` at each announced bend, then `door` at the door node (never after the last node).
- `outside` nodes have no location and are skipped. `arrival` at the destination is always last.
- Turns within `MERGE_RADIUS_M` of a neighbouring checkpoint on the same floor are dropped. `distance_m` is the real polyline length from the previous checkpoint.
- Bends: 35–60° slight, 60–135° plain, over 135° sharp. Smaller bends are not announced.
- **Departure turn.** A door or arrival that directly follows a door gets `departure` when the walk bends at that previous door. There is none after the start, after a connector (orientation unknown), or after a turn checkpoint (its bend is already announced).

Phrasing (pure functions):
```python
def spoken_distance(metres: float, language: str = "en") -> str
def instruction(checkpoint: Checkpoint, index: int, building_map: BuildingMap, language: str = "en") -> str
```
- `spoken_distance`: under 4 m "a few metres"; under 20 m whole metres ("12 metres"); otherwise the nearest 5 m ("about 45 metres").
- `instruction`: `index` picks the opener (en: "", "Okay, ", "Now, ", "Next, "; de: "", "Okay, ", "Jetzt ", "Als Nächstes ") and the wording variant, so repeats vary. Text never contains IDs or coordinates.
- Turn words are spoken word by word: "slight left" is "slightly left".
- **Article rule** (connectors only): English puts "the" before a connector name and before a floor name, but not when the name ends in a digit ("Take Lift 2 up to Floor 1."). A floor name without "floor" gets it added ("First" → "First floor").

Examples (English; German in brackets; openers such as "Okay, " left out):
- turn: "Go straight for 12 metres, then turn left." / "In 8 metres, turn slightly right." (de: "Geh 12 Meter geradeaus und dann links.")
- door: "Walk 8 metres and go through the door into Assembly hall." / "In 8 metres, head into Assembly hall through the door."
- departure: "Turn left, then walk 8 metres to the door into Assembly hall." Arrival after a departure: "Turn left — Office 1.08 is 6 metres ahead."
- connector: "Take the Office staircase up to the First floor." / "Take the lift down to the Ground floor."
- arrival: "It's 6 metres to Office 1.08 — you'll be there."
- arrived: "You've arrived — this is Office 1.08." (de: "Du bist da — das ist Büro 1.08.")

```python
class Guidance:
    def __init__(self, building_map: BuildingMap, clock: Callable[[], float] = time.monotonic) -> None
    language: str                       # "en" default; set by the voice session
    confirm_each_step: bool = True      # only matters while tracking is not live
    route: RouteResult | None
    active: bool                        # property
    def start(self, route: RouteResult) -> None     # replaces running guidance; queues the first instruction
    def stop(self) -> bool                          # False if nothing was active; queues "Okay, stopping navigation."
    def confirm(self) -> None                       # the user reached the next checkpoint: advance; finish after the last
    def repeat(self) -> None                        # re-queue the current instruction
    def update_position(self, floor_level: int, x_m: float, y_m: float, accuracy_m: float | None = None) -> None
    def tick(self) -> None                          # called on every poll; detects tracking loss
    def adopt(self, route: RouteResult | None) -> None   # the map's active route changed; None = now unreachable
    def tracking(self) -> str                       # "live" | "lost" | "none"
    def status(self) -> dict
    def drain(self) -> list[str]                    # speech queued since the last drain, in order
```
Rules:
- **start.** While tracking is not live and `confirm_each_step` is set, " Tell me when you're there." is added to the first two instructions only. If confirmations are off and tracking is not live, all directions are queued as one utterance followed by " I'll be here if you need me."; guidance then waits at the last step, so `confirm` ends it.
- **Reached.** Checkpoint *i* is reached when: a turn is within the radius on its floor; a door is in its next space or within `DOOR_REACHED_M` on its floor (the radius does not apply); a connector only on its target floor (standing at the boarding point is not taking it); the arrival in the destination space or within the radius. Reaching *i* queues instruction *i+1*. If the user is in a space the route enters later, the checkpoints before it count as passed. Reaching the arrival queues the arrived phrase and ends guidance.
- **confirm / repeat / stop.** `confirm` moves on one checkpoint and finishes after the last. `repeat` re-queues the current instruction. `stop` queues the stop phrase and clears guidance.
- **Off route.** `OFF_ROUTE_UPDATES` fixes in a row in a space the rest of the route does not use reroute from that space to the same destination, keeping the step-free and width settings. The queue gets "No problem, let me reroute you. " plus the first new instruction. A fix outside every space resets the count. If no route exists, it queues "Sorry, I can't find another way to <destination> from here, so I'm stopping navigation." and stops.
- **tick.** When a live position goes stale during guidance, queues once "I've lost your position for a moment — just tell me when you get there." A new fix re-arms it.
- **adopt.** Same destination: restarts from the first checkpoint and queues "The route changed — " plus the first instruction (first letter lowercased). Other destination: ignored. `None`: queues "That way is blocked now and I can't find another route." and stops.
- **status()** returns `{"active", "destination": {"id","name"}|None, "next": {"index","kind","name","floor_level","position","instruction"}|None, "progress": [index, total], "remaining_m", "tracking", "confirm_each_step", "language"}`.

## 3. Tools and prompt

`make_tools(building_map, output_directory, guidance: Guidance | None = None)` registers these only when `guidance` is given:
- `start_guidance()`: starts spoken directions for the active route (`building_map.last_route`), replacing any running guidance. ToolError "No active route. Call find_route first." if there is none. Returns the status and a note: give only a one-sentence lead-in.
- `stop_guidance()` → `{"stopped": bool}`.
- `guidance_status()` → `guidance.status()`. `tracking` is "live", "lost" or "none".
- `set_guidance_options(confirm_each_step: bool)` → status. Only matters while tracking is not live.
- `guidance_next_step()`: the user says in their own words that they reached the next point ("I'm at the stairs now"); moves guidance on. ToolError "No guidance is running." when inactive.

`BuildingAgent(building_map, output_directory, client=None, guidance=None, voice=False)` passes `guidance` to `make_tools`. When `voice`, it appends `VOICE_PROMPT` to the system prompt and uses `VOICE_EFFORT = "low"` for latency. The prompt asks for one or two short spoken sentences (under about 35 words), no lists, markdown, IDs or coordinates, rounded numbers, the user's language, and never reading out the app context line.

## 4. HTTP API and turn handling (`final_agent/voice.py`)

`python -m final_agent.voice BUILDING [--host 127.0.0.1] [--port 8765] [--output agent_output/voice] [--cert C --key K]`. This starts an API only. A remote client needs HTTPS for microphone access; pass `--cert/--key` (PEM) with `--host 0.0.0.0`, or put a tunnel in front.

Env: `ELEVENLABS_API_KEY` (unset → text-only API), `ELEVENLABS_VOICE_ID` (default `JBFqnCBsd6RMkjVDRZzb`), `ELEVENLABS_TTS_MODEL` (default `eleven_flash_v2_5`), `ELEVENLABS_STT_MODEL` (default `scribe_v2`). Anthropic credentials are read as for the CLI (`ANTHROPIC_API_KEY`). The server reads the process environment only, not a `.env` file.

Each client gets its own session: its own loaded map, guidance, agent and position. At most 50 sessions are kept; the oldest is dropped.

Responses are JSON unless stated. Errors are `{"error": "..."}`. A speech item is `{"text": str, "audio": "/api/speech/<id>" | null}`; `audio` is null when ElevenLabs is off.

| Method, path | Body | Response |
|---|---|---|
| `GET /` | | JSON service metadata, including `"ui": false` and the main endpoint names |
| `GET /api/building` | | `{"name", "floors": [{"id","level","name"}], "spaces": [{"id","floor_id","name","type","polygon"}], "openings": [{"id","floor_id","position","kind"}]}` |
| `POST /api/session` | `{}` | `{"session", "building", "stt": bool, "tts": bool, "agent": bool, "speak": [greeting], "fillers": {"en": [item, ...], "de": [item, ...]}}` |
| `POST /api/turn?session=ID` | raw audio, `Content-Type: audio/webm`, `audio/mp4`, ... | `{"transcript", "language", "speak": [...], "state"}` |
| `POST /api/text` | `{"session", "text", "language"?}` | same as `/api/turn` |
| `POST /api/update` | `{"session", "position"?: {"floor_level","x","y","accuracy_m"?}}` | `{"speak": [...], "state"}` |
| `GET /api/route?session=ID` | | `{"polylines": [{"floor_id","points"}], "checkpoints": [{"floor_id","position","kind"}], "next_index"}`: the guided route while guidance runs, else the last planned route; empty lists and `next_index: null` without a route |
| `GET /api/speech/<id>` | | `audio/mpeg` |

`state` = `{"guidance": guidance.status(), "position": {"floor_level","x","y","space_id","space_name"} | null}`.

- **Fillers** are pinned: their speech ids stay valid for the whole server run and are not evicted with other speech.
- **Speech audio.** A cached clip is served in one piece. Otherwise ElevenLabs audio streams through as it arrives and is cached only when complete. Cache key: (text, language), 20 MB budget. The newest 256 speech texts are kept, plus the pinned fillers.
- **Position.** `/api/update` checks the position at once (400 if bad). If a turn holds the session, the update returns `"speak": []` after 0.1 s and keeps its fix; the next update that gets the session applies it.
- **Transcription.** Scribe is asked not to tag audio events (`tag_audio_events=false`). Any tag that still arrives, such as "(music)", is stripped before handling.

Statuses:

| Status | When |
|---|---|
| 400 | Body not JSON or not an object; bad `text`, `language` or position; empty audio |
| 404 | Unknown session, speech id or path |
| 409 | `GET /api/route`: the route cannot be given as directions (for example no walkable path through a space) |
| 413 | Body over 64 KB (JSON) or 10 MB (audio) |
| 415 | `/api/turn` body is not `audio/*` |
| 500 | Unexpected error; the traceback goes to the server console |
| 502 | ElevenLabs refused or could not be reached |
| 503 | `/api/turn` while ElevenLabs is not configured; the client can send recognised or typed text to `/api/text` |

**Turn handling** (`VoiceSession.handle_text`), one user turn:
1. Remove audio-event tags such as `(music)` or `[noise]`; a span with digits, such as `(1.08)`, stays. If nothing alphanumeric is left, the turn is silent: nothing is spoken, and the language and guidance state do not change.
2. A language on the turn sets the session language and the guidance phrasing language.
3. Short commands skip the model. The whole utterance, lower-cased with punctuation removed, must match a phrase:
   - **stop**: while guidance is active.
   - **confirm**: while guidance is active, unless the last thing said was an agent reply ending in "?". Then the words go to the agent as an answer.
   - **repeat**: repeats the current instruction if guidance is active and the last thing said was guidance. Otherwise it replays the agent's last reply when the last thing said was that reply. Otherwise it goes to the agent.
   - Phrase sets (`COMMANDS` in `voice.py`):
     - confirm: ok, okay, ok next, next, next step, done, got it, yes, yep, alright, all right, i'm there, im there, i am there, i'm here, im here, here, made it, continue, go on, and now, what now, now what, weiter, ok weiter, okay weiter, ja, erledigt, bin da, ich bin da, da bin ich, bin hier, geschafft, passt, nächster schritt, und jetzt, weiter gehts
     - repeat: repeat, again, say again, say that again, what, pardon, sorry, come again, nochmal, noch mal, wiederholen, wie bitte, was
     - stop: stop, cancel, stop navigation, end navigation, abbrechen, stopp, beenden, navigation beenden
4. Anything else goes to the agent with a context line in brackets, for example `[app: language=en; position=…, tracking live; guidance: …]`, which the user never hears. The agent's reply is spoken first, then the guidance speech the turn produced.
5. If the map's active route changed during the turn and still goes to the guidance destination (for example after a closure), guidance adopts it. If no route is left, guidance says so and stops.

If the agent cannot answer, the reply is one spoken sentence: missing or rejected Anthropic credentials give "I can't answer questions right now because the AI service isn't set up on the server."; a rate limit gives an "overloaded" message; a connection error gives "I can't reach the AI service right now."; other API errors give a generic failure. If the agent could not start, the session still runs guidance and the reason is printed on the server console.

## 5. UI-free console tester (`voice_launcher.py`)

The production backend deliberately serves no HTML. `voice_launcher.py` is a disposable Windows console harness for testing the boundary before another engineer's client is connected:

- ordinary input lines exercise the text → backend → printed/spoken-answer round trip;
- `/talk` records mono WAV from a Windows WASAPI microphone until Enter. Automatic selection pairs an input with the current output endpoint by name when possible, so a connected headset does not leave recording on the laptop array. It then removes DC offset, boosts quiet input, reports duration/level, sends the audio to Scribe v2 and passes the transcript into the same backend path;
- `/mics` lists the real WASAPI capture endpoints and `/mic NUMBER` switches inputs without restarting; dead inputs and recordings shorter than 0.4 seconds fail locally with an actionable message;
- ElevenLabs voices backend response text, which the tester plays through the default Windows output using native Windows APIs;
- `/position ROOM` supplies an explicit local position oracle; `/state`, `/help` and `/quit` are diagnostic commands;
- with `ANTHROPIC_API_KEY`, it constructs the normal `BuildingAgent`; without it, `LocalBackendAgent` answers a few deterministic map queries, can start a named route and otherwise echoes exactly what our backend received.

Build the self-contained tester with `uv run --group voice-build pyinstaller --noconfirm --clean TalkToYourBuilding.spec`. The key is read from `ELEVENLABS_API_KEY` or the current user's Windows Credential Manager target `TalkToYourBuilding.ElevenLabs`; it is not embedded in the executable.

## 6. Checks

- Offline, no keys: `uv run python -m unittest discover -s tests -v` (or the `.venv` Python). On 25 October 2026 all 307 tests passed; 44 are in `tests/test_guidance.py` and `tests/test_voice.py`. The HTTP test walks one route through positions and another through confirmations; local-backend tests pin owned-data answers, echo behavior and route activation; launcher tests cover endpoint pairing, WAV normalisation and dead-input rejection.
- Live ElevenLabs: Flash v2.5 streamed MP3 and Scribe v2 transcribed it back in English. A generated spoken sentence also survived the console launcher's WAV-normalisation path and was recognised by Scribe. Both source and packaged testers enumerated the real WASAPI endpoints, captured measurable microphone input and completed a Scribe upload; typed data and route requests produced audible backend responses, and "okay" advanced guidance. Recognition of a human utterance through the newly paired headset and live Anthropic behavior remain manual demo checks.
- Manual flow: open `dist/TalkToYourBuilding.exe`, type a message, then use `/talk`. If needed, use `/mics` followed by `/mic NUMBER`. For routing, enter `/position Office 0.23`, ask for Kitchen 1.08 and say or type `okay` at checkpoints.
