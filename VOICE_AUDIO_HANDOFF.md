# Voice mode handoff — no output in the user's browser

**Prepared: 25 October 2026. Status: open. Voice works end to end in headless Chrome with a
fake microphone, but in the user's real browser a spoken request produces no output and no
visible progress.** Everything below is on local `main` (merge `9eacd04`, which includes
the empty-transcript fallback). Nothing here is pushed to `origin/main`.

## Symptom

The user switches to Voice, speaks, and nothing happens: no reply, no spinner, no
"Working…". Backend log of the user's session after the restart (`3a616b9e…`):

```
POST /transcription-tokens 201   # prefetch when the microphone starts
POST /transcription-tokens 201   # second fetch = VAD detected speech start (takeToken prefetches the next one)
PUT  /position …                 # walker position sync, unrelated
(no POST /transcriptions, no POST /messages)
```

So speech start was detected and a live transcription socket was opened, but the utterance
never reached the agent, and the WAV upload fallback never ran either.

## What changed today (all on local `main` unless noted)

| Commit | Change |
|---|---|
| `9a6cbaf` | Voice turns run on Haiku at **high** effort (`VOICE_MODEL`, `VOICE_EFFORT` in `final_agent/agent.py`). A voice route request from the live position starts guidance even if the model skips `start_guidance`; the spoken clip is a one-line lead-in ("Heading to X, about N metres."). `draw_route` is no longer duplicated. |
| `5fc1d91` | Active guidance keeps its route on the map after a later reply without one. |
| `4caf342` | `POST /sessions/{id}/transcription-tokens`: ElevenLabs single-use token plus realtime URL (`scribe_v2_realtime`, `pcm_16000`, `language_code=en`, `commit_strategy=manual`). OpenAPI, DESIGN, tests updated. |
| `c43aa10` | Frontend streams microphone audio while the user talks (`frontend/src/features/voice/realtime.ts`, `useVoice.ts`): socket opens on VAD start, pre-roll and 20 ms PCM frames are sent, commit on VAD end. Socket error or 4 s timeout falls back to `POST /transcriptions`. `API_PROXY` env var in `vite.config.ts`. |
| `a31b659` | Map always draws the full route line plus step dots (the step player had cut it to a stub at step 0). |
| `be780b8` | **Fallback for empty live results:** an empty or failed live transcript is retried as a WAV upload, and an empty final transcript shows "Didn't catch that. Please say it again." instead of silently dropping the utterance (`useVoice.ts`, `i18n/en.ts`). Typecheck and `npm run test:voice` pass; merged into `main`, not yet tested in the user's browser. |

## What was verified

- Backend: `uv run python -m unittest discover -s tests` → 332 tests OK (3 skipped).
- Real API, voice turn with live position (`osm-way13507441`, "Take me to Passage"): guidance
  becomes `active`, first instruction emitted, reply 15–16 words. Turn latency 6–12 s at high effort.
- Realtime STT protocol with Node and the committed key: transcript 160–220 ms after commit.
  Batch upload of the same 1.7 s clip: 450–510 ms.
- **Headless Chrome with a fake microphone, full UI on 5173 and 5174:** pill goes
  Listening → Hearing you → Thinking → Speaking; the guide panel shows the spinner and
  "Working…"; the committed transcript arrives about 0.2 s after speech ends; `/messages`
  returns 201 after about 10 s; the reply clip plays. Quiet speech (8 % amplitude) is still
  transcribed (Chrome's auto gain).
- Not reproduced: the user's "no output" case. The only failure seen in tests was one
  `POST /messages` 503 when the looping fake mic produced overlapping turns.

## Hypotheses, most likely first

1. **Empty live transcript dropped silently.** Before the branch fix, `insufficient_audio_activity`
   or an empty `committed_transcript` resolved to `''`, and `drain()` did `if (!text) continue`
   with no message and no upload. That matches the log exactly (no `/transcriptions`, no `/messages`).
   Fixed on the branch; needs the user's confirmation.
2. **The turn was dropped because the app was busy.** `sendText` returns `null` without any UI
   when `loading` is true (`App.tsx`, `if (!text.trim() || loading) return null`). A typed
   message, an earlier voice turn or a slow 10 s agent turn still in flight would swallow
   the new utterance. That would still show a `/messages` call for the first turn, so it fits
   only if an earlier request was pending from before the restart.
3. **VAD never ends.** With steady background noise above `max(floor*3, 0.015)` the utterance
   only ends at `maxMs = 15000`. For 15 s the user sees just the "Hearing you" pill and may
   call that "no output". Afterwards it should transcribe, so this explains the wait, not the
   missing request, unless the user switched modes or reloaded within 15 s.
4. **Stale page.** A tab loaded before the frontend/backend restart can run old code against a
   new backend. The token calls prove new frontend code ran at least once in session `3a616b9e`.
5. **Browser or network specifics** (Safari/Firefox, extensions or a network blocking
   `wss://api.elevenlabs.io`). A blocked socket should fail and fall back to the upload, so
   alone it does not explain the missing upload.

## Ask the user for

- The voice pill text while waiting (Listening / Hearing you / Transcribing / Thinking).
- Browser and version.
- DevTools console: the branch logs `Live transcription failed; uploading the recording.`
- DevTools Network → WS: frames from `api.elevenlabs.io` (`session_started`,
  `partial_transcript`, `committed_transcript` or an error `message_type`).

## Possible fixes

1. **First idea: do not stream from the browser directly to ElevenLabs; forward through our server.**
   Today `realtime.ts` opens `wss://api.elevenlabs.io/...` from the browser with a single-use token.
   That path depends on the user's browser and network reaching ElevenLabs over WebSocket
   (extensions, firewalls, proxies, Safari), and its failures are invisible to our backend log.
   Instead, let the browser send audio only to our own origin and let the backend talk to ElevenLabs:
   - **Simplest:** drop live streaming and always upload the WAV after the utterance
     (`POST /transcriptions`, already implemented and proven in the user's earlier sessions).
     Costs about 0.3 s per utterance (0.45–0.5 s vs 0.2 s for the 1.7 s test phrase).
   - **Streaming via the server:** add a WebSocket endpoint such as
     `/api/v1/sessions/{id}/transcriptions/stream` in `final_agent/api.py`. The browser sends the
     same 20 ms PCM frames there (same origin, goes through the Vite `/api` proxy, needs `ws: true`
     in the proxy config); the backend opens the ElevenLabs realtime socket with the API key
     (`xi-api-key` header, no token endpoint needed), relays `input_audio_chunk`/commit, and returns
     the committed text. Needs a WebSocket client in Python (`websockets`, not installed yet).
     Every step is then visible in our log, and errors map to `40004_speech_unavailable`.
   - **Chunked HTTP alternative:** upload audio while the user talks in 0.5–1 s chunks to an HTTP
     endpoint that feeds the server-side ElevenLabs socket; the final request commits and returns the text.
   Either way, keep the WAV upload as the fallback and remove `POST /transcription-tokens` if unused.
2. **Branch fallback** (empty live result → upload; "Didn't catch that" note). Done, merged in `9eacd04`; keep it whichever transport is used.
3. **Kill switch for streaming**: e.g. `localStorage['wayfinder-stt'] = 'batch'` or `?stt=batch`
   to skip `openTranscriptStream` and use only `POST /transcriptions`. Lets the user A/B in one reload.
4. **Show progress from the first moment:** put the transcript (and `partial_transcript` while
   speaking) into the composer or as the user bubble, and show the guide panel's "Working…"
   state while `voice.state` is `transcribing` or `thinking`, not only while `loading`.
5. **Never drop an utterance silently:** queue voice turns in `sendText` while `loading`,
   or surface "Still working on your last request" instead of returning `null`.
6. **VAD end:** shorter `maxMs` (8–10 s), or adapt the noise floor during speech so a noisy room
   still ends the utterance. Optional: use the realtime socket's own VAD
   (`commit_strategy=vad`) and commit on its `committed_transcript`.
7. **Latency:** voice turns take 6–12 s at Haiku high effort. Options are `medium` effort, or
   speaking the server lead-in as soon as `find_route` succeeds instead of after the model's final reply.
8. **Investigate the 503** on overlapping voice turns (likely `30012_revision_conflict` or a
   model error mapped to `40001`); overlapping turns should be serialised client-side.
9. Cosmetic: chat text can end with "Answer: 22" (benchmark answer format leaking into
   HTTP replies). Not spoken, but visible in the guide panel.

## How to test without a microphone

Headless Chrome can feed a WAV file as the microphone. Two gotchas cost time: Chrome only read
the file from `/tmp` with `--no-sandbox`, and the file loops, so every repeat is a new turn.

```js
// npm i puppeteer-core (outside the repo); uses the installed Chrome
const browser = await puppeteer.launch({
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true,
  args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
         '--use-file-for-fake-audio-capture=/tmp/mic.wav', '--no-sandbox',
         '--autoplay-policy=no-user-gesture-required'],
})
// open http://127.0.0.1:5173/, click the last `.input-mode button` (Voice), poll `.voice-pill`,
// log CDP Network.webSocketFrameSent/Received and responses to /messages and /transcriptions.
```

Make the WAV with 1 s silence, the phrase, then 3 s silence (16-bit mono, 48 kHz works). An
ElevenLabs TTS call with `output_format=pcm_16000` gives a clean phrase.

Backend repro without a browser: create a session (`Idempotency-Key` header required on POST),
`PUT /position` inside a room, then `POST /messages` with `input_mode: "voice"` and check
`guide_message.text`, `speech_clip_id` and `GET /guidance?after=0`.

## Running servers (at handoff)

- 5173 frontend and 8000 backend: main checkout. The frontend hot-reloads `main`; the 8000 backend was last restarted on `a31b659` (backend code unchanged since).
- 5174 frontend (`API_PROXY=http://127.0.0.1:8011`) and 8011 backend: this worktree. Stop them when done.
