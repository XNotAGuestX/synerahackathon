# Audio branch evaluation — 25 October 2026

**Decision: reuse the speech adapter and deterministic geometry/phrasing; rewrite the voice application integration on the current API. Rework guidance progress and rerouting before enabling automatic navigation.** The branch is a useful backend prototype, but it is not an integrated voice feature ready for the current web app. A complete rewrite of the speech and geometry code is unnecessary.

## Scope and evidence

- Refreshed and inspected `origin/Audio` at `35c0341b27a5fd2bace674be71726f132b4ff7cd` against `main` at `82d79a8c81ab2b7ce7d7a6889a2b5d50a7af15c8`.
- The Audio change is one commit after common ancestor `4680cef`: 16 files, 3,144 additions and two removals. Its patch applies cleanly to current main with `git apply --check`. The integration problems below are behavioral, rather than merge conflicts. Comparing the branch tips also shows the newer frontend absent from Audio; that absence is not a deletion introduced by its audio commit.
- Ran the branch in an isolated archive at `/private/tmp/synera-audio-evaluation`, using the primary checkout's installed Python dependencies. Production code and benchmark scoring were not changed or merged.
- **Full branch suite: 307 tests run, 304 pass, three skip.** All **44 audio/guidance tests pass**. The three skips are existing missing-credential scenarios skipped because the SDK detects a local authentication profile. HTTP tests initially could not bind in the sandbox; the successful run allowed temporary loopback servers. No paid endpoint is called by these tests.
- **Additional geometry/confirmation check: 229 resolved-input warm-up routes across all 40 dev buildings.** Of these, 197 produce routes and 32 are unreachable. All 197 have checkpoint walking distances matching the displayed polylines, and all 197 finish through checkpoint confirmations. No unexpected errors or geometry refusals occurred. This uses the existing oracle to supply fixture inputs; it does not measure language interpretation, live positioning, or benchmark accuracy.
- Seven focused diagnostics reproduced the issues and integration limitation described below. These use a small synthetic map and a local HTTP server, with no external services.
- **Two explicitly approved live Anthropic voice-mode text turns pass.** “Guide me to Kitchen 1.08 without stairs” returns a concise lead-in and the first direction in **4.04 s**, with active guidance to the requested destination and `step_free=true`. “Actually take me to Office 0.01 instead” returns a confirmation question in **1.19 s**, retaining Kitchen 1.08 and step-free routing. These are agent-turn timings, excluding speech recognition and audio generation/playback; this sample is not a general latency or accuracy measurement.
- Live ElevenLabs was not tested: no `ELEVENLABS_API_KEY` is configured in the evaluated process. Microphone, playback and recognition quality remain unverified here. Historical audio results in `VOICE_HANDOFF.md` were not independently repeated.

## Feature assessment

| Feature | What is implemented and verified | Use decision |
| --- | --- | --- |
| Speech-to-text | ElevenLabs multipart upload, content-type filenames, language-code normalization, timeout and provider-error handling; offline request/response tests pass. | Reuse `ElevenLabs.transcribe`; confirm with actual browser recordings when credentials are available. |
| Text-to-speech | Streamed MP3 requests, server proxy, completed-clip cache and pinned filler references; fake-provider HTTP flow passes. | Reuse provider adapter and bounded cache behavior. Connect playback to the current frontend. |
| Short voice commands | Whole-utterance English/German confirmation, repeat and stop bypass the model. Questions ending in `?` keep short answers in the conversation. | Reuse command normalization and tested cases. Question routing is a heuristic; interruption and cancellation need application state. |
| Voice conversation | Voice-specific prompt, app position context, guidance tools, concise response rules and low effort setting. Scripted-model round trips and two live turns pass: step-free guidance starts, and a destination change asks for confirmation. | Reuse prompt and tool wiring. Broader dialogue behavior remains unmeasured. |
| Checkpoint generation | Doors, corners, departure turns, selected stairs/lifts and arrival are derived from the actual route. Distances agree with map geometry on all 197 additional reachable fixtures. | Strongest reusable component: keep the pure helpers and associated tests. |
| Spoken directions | Deterministic English/German templates, rounded distances and floor handoffs. | Reuse. Other guidance languages fall back to English; building names remain as supplied. |
| Confirmation navigation | Complete walks work without positioning; repeat/stop work. Reading a whole route works when confirmations are disabled **before starting**. | Usable prototype path. Mid-walk option changes need repair. |
| Position-driven navigation | Finite-coordinate/floor validation, room lookup, checkpoint advancement, tracking-loss notification and two-fix off-route detection. | Happy paths pass, but arrival and position freshness defects block using it unchanged. Position is supplied by a client; there is no localization system. |
| Rerouting and closures | Basic reroute preserves step-free and minimum-width constraints; same-destination map changes can replace guidance. | Rework progress handling: unvisited stops disappear, and closure reroutes still start at the original room. |
| HTTP sessions and map output | Isolated single-building sessions, text/audio turns, position posts, route polylines and basic body limits. | Rewrite around `SessionService`; do not keep a second authoritative map/conversation per browser. |
| Windows console and executable | Push-to-talk WAV normalization, input selection, deterministic local responder and PyInstaller recipe. Portable helper tests pass on macOS. | Keep as optional diagnostics/reference. Physical Windows capture, playback and packaging were not exercised here. |
| Current browser app | Main has browser `SpeechRecognition` that places an English transcript in the input. Audio adds no production browser client and is not wired to it. | Missing end-to-end integration: recording/upload, playback, interruption, map/session synchronization and position posting. |
| Campus, plans and emergency features | The voice server loads one `BuildingMap`; its default agent does not receive the existing workspace or emergency mode. | No new voice workflow for these features is established by this branch. Keep main's existing implementations. |

## Reproduced correctness defects

Source references below are pinned to the evaluated Audio commit. The synthetic fixture has adjacent rooms `A → B → C → D`, an off-route branch `X` from `B`, and a requested stop `V` branching from `C`.

### 1. P1 — Off-route rerouting drops unvisited stops

[guidance.py, lines 558–563](https://github.com/XNotAGuestX/synerahackathon/blob/35c0341b27a5fd2bace674be71726f132b4ff7cd/final_agent/guidance.py#L558-L563)

Start `A → V → D`, then post two fixes in `X` before visiting `V`. The replacement route's stops are `[X, D]`, and its space path never visits `V`. Step-free and minimum width remain intact. This can silently turn a multi-stop task into a direct destination route.

**Required behavior:** track completed stops, and retain every unvisited stop in order during rerouting.

### 2. P1 — Closing a door behind the walker stops a reachable journey

[voice.py, lines 391–398](https://github.com/XNotAGuestX/synerahackathon/blob/35c0341b27a5fd2bace674be71726f132b4ff7cd/final_agent/voice.py#L391-L398), [guidance.py, lines 442–453](https://github.com/XNotAGuestX/synerahackathon/blob/35c0341b27a5fd2bace674be71726f132b4ff7cd/final_agent/guidance.py#L442-L453)

Start `A → D`, advance to `C`, then close door `A–B` through the actual closure tool. That tool recomputes the original request from `A`, finds no route and leaves `last_route=None`. The voice session stops guidance, although `compute_route(C, D)` still succeeds with `[C, D]`. With a detour available from the original start, guidance instead restarts the old journey from checkpoint zero.

**Required behavior:** closure-triggered navigation should recompute from the current confirmed/live location, retaining remaining stops and constraints. Keep the original planning request separate from progress on the walk.

### 3. P1 — Proximity alone announces arrival through a wall

[guidance.py, lines 359–372](https://github.com/XNotAGuestX/synerahackathon/blob/35c0341b27a5fd2bace674be71726f132b4ff7cd/final_agent/guidance.py#L359-L372)

With destination `D` narrowed to two metres, advance to its arrival checkpoint, then post a fix inside a neighboring room, 1.5 m from `D`'s anchor. `space_at` correctly identifies the neighbor, but guidance says “You've arrived — this is D.” and stops. The distance fallback ignores the intervening wall and the known room mismatch.

**Required behavior:** confirmed containment in another room must not count as destination arrival. Constrain distance-based checkpoint acceptance to the walkable route/appropriate room.

### 4. P1 — Deferred positions are ignored by the next turn and regain false freshness

[voice.py, lines 560–585](https://github.com/XNotAGuestX/synerahackathon/blob/35c0341b27a5fd2bace674be71726f132b4ff7cd/final_agent/voice.py#L560-L585), [guidance.py, lines 455–464](https://github.com/XNotAGuestX/synerahackathon/blob/35c0341b27a5fd2bace674be71726f132b4ff7cd/final_agent/guidance.py#L455-L464)

While the session lock is held, post a position in `B`; it is queued. After releasing the lock, submit “Where am I?” before another position poll. The context sent to the responder still says `A`. The next turn does not consume the pending fix.

In a second check, advance the fake clock by 20 seconds before polling. The deferred fix is then labeled `tracking="live"`, despite exceeding the 15-second freshness limit. Its timestamp is assigned when applied rather than received.

**Required behavior:** retain a receive timestamp and sequence with each fix, consume the newest applicable fix before conversation/navigation decisions, and preserve its actual age. Do not let pending updates restore stale tracking.

### 5. P2 — Turning confirmations off during a walk produces no directions

[tools.py, lines 1044–1056](https://github.com/XNotAGuestX/synerahackathon/blob/35c0341b27a5fd2bace674be71726f132b4ff7cd/final_agent/tools.py#L1044-L1056), [guidance.py, lines 408–420](https://github.com/XNotAGuestX/synerahackathon/blob/35c0341b27a5fd2bace674be71726f132b4ff7cd/final_agent/guidance.py#L408-L420)

Start without live positioning, drain the first instruction, then call `set_guidance_options(confirm_each_step=False)`. Progress stays `[0, 4]`, the speech queue stays empty, and there is no automatic continuation. Whole-route reading is implemented only inside `start`, although the tool promises all remaining directions and the prompt recommends this tool mid-conversation.

**Required behavior:** changing this option during active guidance must immediately deliver the remaining directions and establish consistent completion behavior.

## Integration gaps that make a transport/session rewrite worthwhile

- **Different API and different state.** Main uses `/api/v1/sessions/...` and `SessionService`; Audio starts a separate `ThreadingHTTPServer` with `/api/session`, `/api/text`, `/api/turn` and its own maps, agents and locks. Importing its files does not make frontend routes, closures or conversation history shared.
- **Different edit semantics.** Main's `TurnTools` proposes closure/door edits for confirmation. Audio's `default_agent` uses the ordinary tools, which apply and save immediately. Reuse main's tools and confirmed-action flow when integrating voice.
- **Different report storage.** Audio defaults each session's reports to its own output directory's SQLite database. Main deliberately shares a report database while retaining distinct chat identities. Voice users must participate in that same confirmation/report flow.
- **No direct cross-origin browser contract.** A real `OPTIONS /api/text` request returns 501; Audio has no CORS/preflight implementation. A same-origin proxy could address transport access, but would still leave the separate session state. Reuse the existing API's CORS/authentication and limits. Its JSON body limit also needs an explicit, bounded exception or separate handling for audio uploads.
- **No cancellation/playback lifecycle.** A turn holds the session lock; even a stop command waits behind it. The backend supplies audio URLs, but has no client that interrupts playback, discards speech from superseded turns or handles recording/playback overlap. Filler URLs alone do not implement filler timing or interruption.
- **Structured replies need an adapter.** Main needs JSON `ApiReply` and map effects; only its user-facing `text` should be spoken. Reuse the voice wording rules without replacing main's structured result or speaking serialized JSON.
- **Session/runtime limitations.** Voice sessions are in memory, capped at 50 with oldest-session eviction; no reload/resume operation is exposed. The service has no authentication or rate limiting. The optional Windows harness uses a fixed demo building and a labeled deterministic fallback, which is useful for boundary testing but is not evidence of live Claude understanding.

## Implementation decision and smallest useful replacement

| Keep/use | Rework or replace |
| --- | --- |
| `ElevenLabs` STT/TTS calls, language normalization and provider errors | Replace standalone `VoiceServer`/`VoiceHandler` with small endpoints in the existing API. |
| Speech-cache policy and provider failure tests | Bind speech and guidance to the existing session, route revision, preferences and shared report storage. |
| `route_checkpoints`, walk geometry, turn labels and English/German phrasing | Rework `Guidance` progress, arrival validation, remaining stops, closure reroutes and fix timestamps. |
| Validated point-to-room helper, with awareness of its 1.5 m nearest-room fallback | Avoid treating that nearest-room fallback as proof of crossing a wall or arriving. |
| Command phrase sets and voice-prompt requirements | Integrate commands with explicit clarification, cancellation and pending-action state. |
| Relevant regression tests and the console harness as reference | Build browser recording and cancellable playback around the current map and session. Keep Windows audio/build dependencies optional. |

The first implementation slice should be browser push-to-talk → STT → **existing session message flow** → spoken `ApiReply.text`, with the same map effects as text input. Preserve text entry and show provider failures. Add playback cancellation before enabling automatic checkpoint speech.

Then integrate navigation with one progress owner: current floor/location, selected route revision, next checkpoint and remaining stops. Use the reproduced cases above as acceptance checks, along with a normal multi-floor walk, step-free/width constraints, unreachable routes, repeat/stop and confirmation-only navigation. Campus/workspace voice support is a separate extension to that shared contract.

**Disposition:** no merge or production rewrite was performed during this assessment. The selected rewrite boundary and reusable code are identified; voice remains incomplete in the backlog.

## Reproduction and retained local evidence

From the primary checkout, create an isolated copy of the evaluated commit and use an installed project interpreter:

```bash
mkdir -p /private/tmp/synera-audio-recheck
git archive 35c0341b27a5fd2bace674be71726f132b4ff7cd | tar -x -C /private/tmp/synera-audio-recheck
cd /private/tmp/synera-audio-recheck
/Users/felix/tum/artemis/synerahackathon/.venv/bin/python -m unittest discover -s tests -v
```

HTTP tests require permission to bind local loopback ports. Use a Python environment with the branch's project dependencies if the primary `.venv` is unavailable. Focused runs use `-p test_guidance.py` and `-p test_voice.py`.

Temporary diagnostics and their actual output remain outside version control:

- [Complete branch test log](/private/tmp/synera-audio-evaluation/full-suite.log)
- [Seven synthetic/HTTP diagnostics](/private/tmp/synera-audio-evaluation/audio_probes.py) and [results](/private/tmp/synera-audio-evaluation/audio-probes.log)
- [40-building geometry/confirmation diagnostic](/private/tmp/synera-audio-evaluation/geometry_probe.py) and [results](/private/tmp/synera-audio-evaluation/geometry-probe.log)
- [Two live voice-mode text turns](/private/tmp/synera-audio-evaluation/live-voice-smoke.log). The original diagnostic did not capture SDK-object tool blocks, so its `tools` field is incomplete; the recorded speech and resulting guidance state support the live conclusions above. The [smoke script](/private/tmp/synera-audio-evaluation/live_voice_smoke.py) now uses the agent's tool-call accessor for future runs; it was not rerun after the two approved turns.

Run either offline diagnostic from `/private/tmp/synera-audio-evaluation` with the interpreter above. The separate live smoke script sends building context to Anthropic and consumes API credit. These files are local audit evidence, not shipped application modules or a public benchmark submission.
