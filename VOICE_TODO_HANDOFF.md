# Voice control: live-demo follow-up (updated 25 Oct 2026)

Contract and design: [VOICE_HANDOFF.md](VOICE_HANDOFF.md). The backend and UI-free console
verification are complete; this file lists the remaining Claude and client-integration checks.

## Delivery state

- The implementation, tests and documentation were reconciled on 25 October 2026 for the `Audio` branch.
- The production backend is API-only. `voice_launcher.py` and `TalkToYourBuilding.spec` are a disposable
  Windows console harness, not a production UI.
- `sounddevice` is Windows-gated in the project dependencies; importing the backend and its tests does not
  require PortAudio on Linux or macOS.

## Verified

- `python -m unittest discover -s tests`: **307 tests OK**. Guidance, voice server, ElevenLabs
  request building and the tools all use fakes; no test calls a paid endpoint.
- The headless HTTP flow was extended to cover a complete position-driven walk, an unrelated
  question during navigation, and a complete no-position walk using checkpoint confirmations.
- A live ElevenLabs Flash v2.5 → Scribe v2 round trip returned the original English sentence.
- A generated spoken sentence survived the launcher's WAV normalisation and was recognised by live Scribe.
  The source and packaged testers enumerated the WASAPI inputs, paired the JBL capture endpoint with
  the active JBL output, and uploaded measurable microphone input. Typed/route round trips and guidance
  advancement with "okay" also passed. `/mics` can override automatic pairing.
- `GET /` now returns JSON metadata with `"ui": false`; no HTML or browser client is packaged.

## Critical before the demo

1. **Live Claude check in voice mode.** The agent must:
   - Use the context line's space id as the route start.
   - Call `find_route` and then `start_guidance`.
   - Give only a one-sentence lead-in and never read out the `[app: …]` line.
   - Ask before replacing an active route; call `guidance_next_step` for "I'm at the stairs".

   Check latency at `VOICE_EFFORT = "low"`.
2. **Production-client integration.** The separately owned client must implement recording,
   playback, position posting, interruption and any phone-specific HTTPS behavior against the API.
3. **Security:** the server has no authentication. The default bind is `127.0.0.1`. A tunnel
   or `0.0.0.0` exposes the API, and with it paid ElevenLabs/Anthropic usage, to anyone with the
   URL. Keep tunnels short-lived.
4. **Headset utterance check.** Speak one real request through the automatically paired input and confirm
   the console prints `heard[language]> ...`; synthetic speech and physical capture were verified separately.

## Known limitations (deliberately not done)

- No production UI is included. Client layout, continuous recording/VAD and application-owned
  position tracking belong to the separate client integration.
- Corner ("Ecke") turn checkpoints rarely fire in the procedural buildings (rectangular rooms).
  Left/right comes from departure turns at doors, e.g. "turn right, then walk 20 metres to the
  door into …".
- Guidance phrases exist in English and German only; other languages hear English guidance,
  while the agent still replies in the user's language. Room and floor names come from the
  data as-is.
- Reroute goes straight to the destination; unvisited `via` stops are dropped.
- A closure that changes the route makes guidance restart from the new route's first checkpoint.
- An agent turn holds the session lock. Position updates during the turn are deferred, and only
  the newest is kept.
- TTS starts after the whole agent reply (no sentence streaming). Fillers ("One sec.") cover
  replies slower than 1.6 s.
- `/api/session` reports `agent: true` even without Anthropic credentials. The first turn then
  says the AI service is not set up, and guidance still works.
- Sessions live in memory (max 50) and are lost when the server restarts.

## Commands

```bash
.venv/Scripts/python.exe -m unittest discover -s tests            # 307 OK on 25 Oct 2026
.venv/Scripts/python.exe -m final_agent.voice data/dev/proc-factory-dev-003   # API only
.venv/Scripts/python.exe voice_launcher.py                        # typed + /talk console test
```
