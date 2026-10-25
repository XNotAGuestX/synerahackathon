# Non-voice requirements and bug audit — 25 October 2026

The largest remaining work is connecting existing capabilities to the browser and
finishing verification/submission. Do not rebuild the nine benchmark tools or the
CLI's campus/plan workspace: they exist. Older README section 9 tables and unchecked
backlog rows often describe an earlier implementation.

Scope: current README requirements, backend, frontend integration, tests and delivery
files. Voice-owned files were read where needed to understand integration, but not
edited. README and BACKLOG were concurrently owned by that agent, so this dated
report records the findings separately. No paid model calls were made.

## Required functionality: what is actually left

| Priority / task | Current evidence | Smallest completion gate |
| --- | --- | --- |
| **P0 — Level 4 in the browser** (L4-01–04, CORE-06) | `workspace.py` implements actual PNG/JPEG extraction, calibration, review/corrections, apply/cancel/undo and export/resume. `PlanImport.tsx` only previews images/PDFs and calculates scale; it never submits them for extraction. Its JSON input expects a single API `FloorPlan`, not the dataset's full `building.json`. `App.tsx` creates a synthetic `local-…` session for an imported plan; this is not a backend building session. | Connect upload → existing workspace extraction → visible calibration/validation → confirmed commit → real backend session → locate/route on the imported building. Retain building IDs, floors and source attribution. A local preview must not be presented as a navigable imported session. PDF support can remain an explicit conversion-to-PNG/JPEG step. |
| **P0 — Level 3 in the browser** (L3-02–03, CORE-06) | `Campus` and workspace tools support scoped buildings, explicit measured walkways, constrained routes and closure/reopen recovery. Browser building selection opens independent single-building sessions; `api.py` has no campus/workspace operations and `SessionState` owns one `BuildingMap`. | Expose the existing campus registry and routing through the API; show indoor → walkway → indoor legs with building/floor handoffs. Demonstrate two buildings with repeated room numbers and a closed walkway that reroutes or becomes explicitly unreachable. Switching the building picker alone does not establish cross-building navigation. |
| **P0 — Announced industrial route rules** (MAP-01, SUB-03) | The README's Synera clarification requires forklift-only aisles/openings ≥3 m and destination-only production bays for applicable questions. `graph()` and route tools currently offer step-free, width and closures, with no industrial profile. Their descriptions explicitly acknowledge this limitation. | Add a separate explicit route profile when these rules are requested, including eligible transit spaces and destination exceptions. Test a wide pedestrian passage and a shortcut through an intermediate production bay. Preserve kit 1.1.0 behavior for existing public questions. A width filter alone is insufficient. |
| **P0 — Live interpretation and interaction evidence** (L1-03–04, L2-01–04, QA-03) | All nine deterministic scored components pass below; saved training runs and CLI examples exist. This audit did not establish a current complete live dev score or run the browser's interaction smoke. | Run the documented per-kind live dev smoke, inspect failures, then broaden. Exercise real locate → clarify → constrained tour → closure/reopen → unreachable → building switch. Include nonexistent room references and retained accessibility preferences. Use real responses throughout the demo. |
| **P0 — Required answer artifacts and Sunday adapter** (SUB-01–04) | `BENCHMARK.md`, the benchmark callable, official scorer and CSV writer exist. No completed public-test answer CSV was found; the 145-row dataset template is not a submission. The repository still describes the Sunday schema as organizer-dependent. | Generate all 145 public answers with the agent; validate IDs, uniqueness, nonempty replies, final `Answer:` lines, UTF-8 CSV and size. Capture the announced Sunday contract and implement/run its actual adapter. Preserve ordered spaces/openings/connectors for route grading. Do not assume the existing CSV runner already handles the earlier PDF's standalone `questions.json` → `answers.json` contract. |
| **P1 — Submission demonstration** (SUB-05–06) | A demo script and technical/design documents exist, but `docs/DEMO_SCRIPT.md` still uses debug fixtures for clarification, closure and unreachable. No recorded video artifact was found. Attribution is documented. | Rehearse the 3–5 minute real workflow without restarting; include campus routing and an actual plan correction/build. Prepare the short technical explanation and required recording/package, retaining attribution. Confirm the final demo/submission format with organizers. |

Levels 3 and 4 already have CLI/map-artifact demos in `examples/level34/README.md`.
The browser integration gaps above do not mean their deterministic backends are
missing. Use those existing flows if the immediate submission demonstration must
precede browser integration. General multi-floor vision accuracy remains unverified.

## Bugs fixed in this audit

| Defect | Result after fix | Regression evidence |
| --- | --- | --- |
| A staircase labelled `step_free: true` could be selected for a wheelchair route. | Step-free routing excludes connector kind `stairs` regardless of its flag; ordinary routes retain stairs. | `test_routing.py`: mislabelled staircase succeeds normally and is unreachable step-free. |
| Multi-floor extraction returned at the first unscaled floor; calibration rebuilt only that floor, losing previous and later floors. Pending imports could also be overwritten by starting another draft. | Retains all floor observations, copied sources and known calibrations. `calibrate_plan` accepts an optional `floor_id`, requires it for multiple pending floors, and resumes without another vision request. Starting another draft requires calibration or cancellation first. Older single-floor saved pending records remain supported. | `test_workspace.py`: three floors, two missing scales, explicit selection, two session reloads and deleted original image; all three floors and copied sources survive. Model perception is mocked. |
| List/dict IDs and malformed asset room references crashed validation; an invalid draft ID could also crash preview. | Invalid IDs/references produce validation issues. Preview returns an explicit per-floor rendering error when malformed records cannot be drawn; applying an invalid draft stays blocked. | `test_plan_build.py` and `test_workspace.py`: invalid IDs across all five collections, invalid asset reference and invalid preview/apply. |
| A campus route whose start equalled its destination had no space or floor leg. | Retains a zero-length indoor leg, its room, directions and floor segment, including repeated tour stops. | `test_campus.py`: same-room route retains its floor and scoped space. |
| Adding a walkway cleared the current campus route without recomputing the retained request. | Adding a link recalculates the active journey, including recovery of a previously unreachable route. | `test_campus.py`: disconnected buildings become reachable after adding a walkway; reloaded route identity matches. |
| Invalid width input or a session-save failure could change confirmed location/preferences despite reporting failure. | Validates candidate preferences before mutation and restores prior location/preferences if saving fails. | `test_workspace.py`: negative width and simulated disk-full failure preserve both in-memory and reloaded state. |

Changed implementation files: `final_agent/building_map.py`, `campus.py`,
`plan_build.py`, `workspace.py`; regressions are in their existing test modules.
The official scorer, source datasets, voice implementation and other agent's edits
were not changed by this audit.

## Verification actually performed

| Check | Result |
| --- | --- |
| Focused routing/campus/plan/workspace suite | **39 passed** |
| Full backend suite, final rerun against the shared checkout | **340 run: 337 passed, 3 credential-dependent skips** |
| Scored dev components with labelled resolved inputs and the unchanged official scorer | **138/138**, covering all nine scored kinds |
| Dev warm-up oracle | **369/369** |
| Frontend production build | **Passed**; Vite reports large bundle chunks |
| Frontend effects, walk-field, perimeter and editor checks | **All passed**; editor reports 77 checks |

The initial backend run had three voice/API failures while the voice agent was
editing. The final rerun passed; those voice files were not modified here.
These counts describe a shared-checkout snapshot, not an isolated voice review.
No live conversational benchmark, real vision extraction or browser interaction
run was performed here. The oracle supplies expected-answer information and its
route scorer is permissive; 369/369 is compatibility evidence, not live accuracy
or independent proof that every rendered walk is valid.

Reproduction from the repository root with the installed environment:

```bash
PYTHONPATH=tests .venv/bin/python -m unittest test_routing test_campus test_plan_build test_workspace -v
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python bench_analsysis/run_tests.py --mode components --split data/dev --results /tmp/synera-components.json
.venv/bin/python -m final_agent.evaluate data/dev --oracle
cd frontend
npm run build
npm run test:effects
npm run test:walk
npm run test:perimeter
npm run test:editor
```

This environment needed the existing `.venv` because uv's default cache directory
was not writable. `MPLCONFIGDIR=/tmp/synera-mpl` was used for the later Python
checks. Generated evidence/logs were written under `/tmp`.

## Additions worth considering after the required flows

1. **Finish the presentation extension already built.** The stacked 3D viewer,
   animated routes, movable object editor and ongoing voice work provide ample
   material. Demonstrate one coherent extension before adding AR or another stack.
2. **A persistent minimum-door-width preference.** Deterministic routing supports
   it, but the browser session preferences and direct route request only expose
   step-free. Carry width through preferences, API, reroutes and UI; distinguish
   wheelchair/load clearance from forklift eligibility.
3. **QR room/entrance check-in.** A small reliable source of building/floor/location
   for visitors; it can reuse the current-location pathway. This would be a new
   feature, unlike the existing simulated walk pad, and needs its own validation.
4. **Shared building edits**, only if required work is complete. Current session
   edits are isolated; persistent room reports already share SQLite state. Real
   cross-session map edits need revision conflicts and update delivery. Treat the
   emergency roll-call feature as the documented simulation, not real tracking.

Do not add more benchmark tools, another renderer, or a large task-controller
framework solely to satisfy old unchecked boxes. First close the existing input →
computation → usable browser output and delivery gates.
