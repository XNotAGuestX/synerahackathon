# Voice mode handoff — 25 October 2026

Implemented on `max_branch` from refreshed `origin/main` (`3086b64`). The previous
branch head is preserved as `backup/max-branch-before-voice-20261025`. Local `main`
and remote `main` were not changed. Branch-only changes were excluded.

## Current behavior

- Voice tap activates a reusable native-rate AudioContext before asynchronous work.
  An AudioWorklet supplies 16 kHz mono audio. Silence detection ends a recording;
  **Finish speaking** ends it manually, exactly once. The existing 15 s limit remains.
- Each WAV goes through our own `POST /sessions/{id}/transcriptions`. The browser
  no longer opens an ElevenLabs socket or fetches realtime tokens. The existing
  token endpoint remains for API compatibility.
- Recording, transcription, queued requests, thinking and playback are visible.
  The recognized transcript appears immediately after transcription. Typed and
  spoken messages share one FIFO dispatcher instead of dropping input while busy.
- Session changes abort transcription/playback and discard stale UI results and
  queued recordings. Leaving voice closes its audio context and microphone tracks.
  An already-dispatched model request finishes before another request to that same
  session is sent: aborting browser fetch cannot undo server-side tool work.
- Transcription errors leave the next utterance usable. Empty transcripts show
  “Didn't catch that.” Audio failures retain the clip for **Resume voice** to retry.
- The written answer stays in `guide_message.text`. Voice responses also return
  `speech_text` and `speech_clip_id`. Only the short summary is synthesized: roughly
  30 words/two sentences by default, with essential warnings and clarification kept.
  Longer spoken detail is permitted when requested. Text turns return null speech fields.
- For active routes, the application builds the spoken destination, rounded distance
  and step-free introduction from the computed route. The structured internal
  `speech_warning` keeps essential warnings in front of it, so the model cannot ask
  to start guidance after it has already begun. Stop-only requests acknowledge the
  committed stop without replaying the previous route.
- Completed-turn thinking blocks are removed before a new user turn; current tool
  loops keep theirs intact. This fixes live 400 signature errors when position or
  input mode changes the system prefix. [Provider explanation](https://platform.claude.com/docs/en/build-with-claude/thinking-troubleshooting).
- Valid voice route requests still start automatic walking guidance. The summary
  introduces the destination/distance; the guidance feed speaks waypoint directions.
  Pending replies precede queued directions; newer speech interrupts stale audio.
- Backgrounding the page pauses voice. Tap **Resume voice** after returning.
  This is a foreground browser feature, not lock-screen/background navigation.

## Object edits and reports — follow-up

Explicit add/remove/update requests use the object editor and require only the
requesting user's Confirm button (or editor Save). A ghost on the map is a preview,
not a saved object. Pure edit acknowledgements now come from the actual pending
action in both written and spoken output, and the corrected wording is retained
in conversation history. Existing unrelated pending reports cannot add a second
user requirement to that acknowledgement. Independently requested answers and
essential warnings are preserved.

The prompts/tool descriptions prohibit saving a duplicate report merely recording
an object addition/removal or a missing map object. A separately stated condition
can still be reported alongside an edit. General facts/conditions need two distinct
chats; concrete hazards become active immediately. The API's public shapes are
unchanged.

The requested local cleanup removed `Coffee table H-C2` through the normal shared
edit mechanism and archived its obsolete missing-map report. A fresh session
confirmed absence and all 505 other objects were unchanged. Historical exports
were left intact.

Focused checks (25 October 2026): 48 API tests and 12 room-report tests pass.
Regression cases inject incorrect second-user wording with an existing pending
report and cover add/update/remove, preview-only state, one confirmation,
new-session persistence, mixed general/safety reports, retained independent answers
and corrected conversation history. Real Chrome chat add/remove passed with one
Confirm each; a second session saw the saved changes. Live STT/voice samples passed
add/locate/remove without duplicate report/vote calls, general report activation
only after two chats, and an immediate wet-floor safety report alongside an edit
preview. All verification edits/reports used temporary data, apart from the
explicitly requested H-C2 cleanup. These are sampled flows, not a speech benchmark.

## Run

```bash
uv run python -m final_agent.api
# In another terminal:
cd frontend
npm ci
npm run dev
```

Use the existing Anthropic and ElevenLabs configuration. On desktop, open
`http://localhost:5173`, load a connected building and tap **Voice**. Speech is
English. For automatic guidance, the live-position marker must be in a known room;
otherwise the guide should clarify the start. Selected map objects are not location.
If credentials are in `.env`, use `uv run --env-file .env python -m final_agent.api`.

For iPhone, use trusted HTTPS; a plain LAN HTTP address cannot capture the mic.
Optional Vite `VOICE_TLS_CERT`/`VOICE_TLS_KEY` configuration and a local certificate
recipe are in [API setup](docs/api/README.md#voice-mode).

## Verification performed

Focused checks only; no broad benchmark or full-suite run for this change:

- API/session tests: **40 passed**, including separate written/spoken answers,
  preserved warnings, spoken clarification, automatic guidance and live-start checks.
- Speech adapter: **5 passed**. Navigator: **9 passed**.
- Existing scripted multi-turn conversation regression: **1 passed**.
- API fixture validation: **44 examples passed**.
- `cd frontend && npm run test:voice`: VAD, WAV and speech-queue checks passed.
- `cd frontend && npm run build`: production build passed (existing large-chunk warning).
- Installed headless Chrome, normal autoplay policy, synthetic microphone WAV,
  390 px viewport and fixture service responses: **4 scenarios passed**:
  interruption/manual finish; typed-plus-voice FIFO (maximum one message in flight);
  failed transcription followed by successful speech; building switch during
  transcription (no old message, clip or transcript leaked into the new session).
- With user authorization, live ElevenLabs TTS → STT → Anthropic voice reply →
  ElevenLabs TTS passed on a temporary factory session: “What building am I in?”
  was transcribed correctly, returned distinct written/spoken answers and playable
  audio in **9.9 s**. Further live samples verified start clarification, automatic
  step-free guidance and stopping. These found and prompted the thinking-history
  and stale spoken introduction/stop fixes above. No production report database
  was used or changed.
- Final live route sample with a synthetic wet-floor report in a temporary database:
  **21 spoken words vs. 76 written words**, preserved hazard warning, active step-free
  guidance, rounded 17 m introduction with no redundant confirmation question, and
  synthesized audio in **12.3 s**. A live stop returned only “Guidance stopped.”

Reproduce the browser check with Vite on 5175:

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5175
# From the repo root, another terminal:
uv run --no-project --with playwright python frontend/e2e/voice-smoke.py
```

`PLAYWRIGHT_CHROMIUM` can select a different installed Chrome executable. This
harness uses real browser capture/VAD/playback, but synthetic recognition, model
wording and speech responses; it does not measure live provider accuracy.

## Remaining verification limits

A physical microphone/speaker echo test and an actual iPhone Safari check were not
available. Safari support has gesture-based audio initialization and HTTPS setup,
but is not claimed as device-verified. Live samples do not establish general speech
recognition accuracy or latency. The historical real-user “no output” case still
needs one short real-device check. Existing navigation capabilities/limitations
remain as documented in ADR-0003.
