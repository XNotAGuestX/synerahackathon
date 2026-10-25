# Codebase audit — 24 October 2026

**Superseded for planning on 25 October 2026.** This file is a historical snapshot. Level 3 walkways and Level 4 plan import were implemented after it was written. The current compliance judgment is in the [README](README.md). Today's remaining work is [docs/TODOLIST-2026-10-25.md](docs/TODOLIST-2026-10-25.md). Do not treat the "missing walkway" and "missing plan ingestion" rows below as the current backlog.

**Implementation handoffs, prepared 25 October 2026:** [Level 3 — floors, buildings and walkways](LEVEL_3_HANDOFF.md) and [Level 4 — building creation and correction from plans](LEVEL_4_HANDOFF.md) were briefs for work that has since landed in the CLI. Their acceptance evidence is [examples/level34/README.md](examples/level34/README.md). The audit evidence below retains its original verification date.

**Follow-up source inspection — 25 October 2026:** the primary branch has advanced to `8151c17`. Subsequent work added CLI model selection, aggregate benchmark token usage and model-specific configured cost estimates with running totals. Those changes supersede the model-selection/aggregate-usage gaps in the configuration rows below; per-question latency and external price accuracy were not verified. The original audit snapshot and test results remain historical; no implementation tests were rerun for this documentation handoff.

The deterministic core is substantially ahead of the README's implementation tables. The main unfinished work is delivering the required user workflows: an integrated conversation and map, navigation between buildings, and creating a building from a plan. Rebuilding the nine analysis tools or the router would spend time on capabilities that already work.

Four agents reviewed the current primary checkout: Level 1/interaction; Level 2/routing; Levels 3–4; and benchmark, storage, supporting code and delivery. The Levels 3–4 reviewer also independently checked delivery. This covers all 15 Python modules in `final_agent/` and `benchmark/`, both analysis scripts, all 21 test modules, requirements, configuration and repository deliverables. Generated data, virtual environments and duplicate/unmerged worktrees are not additional product implementations. Active unmerged features do not count as delivered here.

Snapshot: base commit `b53b684`, including the existing uncommitted documentation and tool-contract/pagination integration. That integration occurred during the audit, so references were refreshed and the full suite rerun afterwards. Auditing changed no product code, tests, scorer or dataset. The report and short README/backlog audit notes are the only intentional deliverables.

**Evidence scale:** **implemented** means code and the stated deterministic checks exist; **partial** means a usable fragment exists but a required workflow or correctness condition is missing; **missing** means no implementation was found; **unverified** means the behavior requires evidence beyond the checks performed. These are implementation assessments, not predicted judging scores or completion percentages.

## Requirements and importance

The README explicitly requires:

| Requirement | Importance | Audit conclusion |
|---|---|---|
| **Level 1 — Locate:** converse, find rooms/equipment on one floor, see the result | Required functionality; also enables the 25-point interaction assessment | Strong search/inspection/highlight primitives; incomplete conversation-plus-view workflow |
| **Level 2 — Route:** A→B, step-free, closed areas, multi-stop tours | Required functionality and route validity | Most deterministic behavior implemented; application integration, journey recovery and real interaction verification remain |
| **Level 3 — Scale:** multiple floors, multiple buildings, stairs/lifts/walkways | Required functionality | Multi-floor routing works within one building; multi-building selection and walkways are absent |
| **Level 4 — Build:** create/update from plans through conversation, in minutes | Required functionality; largest capability gap | JSON loading, door edits and saving are foundations; the plan-to-building workflow is absent |
| Automatic answers and valid routes on unseen buildings; all nine public scored kinds | Part of the **55-point functionality** category | All nine tools pass resolved-input dev checks; live interpretation, final output and additional industrial route rules need verification/work |
| Targeted clarification, understood intent, remembered constraints, understandable directions | **25 points** | Prompt/history and tools exist; no current live acceptance script establishes these behaviors |
| One complete optional extension | **10-point creativity** opportunity | No complete extension demonstrated; defer new extension work until required levels work |
| Working 3–5 minute demo and submission artifacts | **10-point pitch/demo** category plus submission requirements | Required command document and generated answer artifacts are missing from the repository; submission/demo readiness is unverified |

Voice, AR, 3D, live positioning, a particular UI framework and a large typed-task architecture are not required to complete the basic four levels. Forklift logistics is an optional extension as a product, but the announced forklift and destination-only-bay rules must still be respected on any automatic-check question that invokes them.

## Ranked remaining work

Ranking considers required-level impact, how much is missing and the smallest work that closes a usable workflow. Correctness fixes belong inside the affected slice; do not defer them merely because they appear lower in this table. Effort sizes are relative scope, not time estimates.

| Rank | Work to finish | Already available | Remaining scope | Smallest acceptance gate |
|---:|---|---|---|---|
| **1** | **Finish Levels 1–2 as a usable app** — L1-01–04, L2-01–04 | CLI tool loop, complete search/inspection, useful locate PNGs, constrained routes, closures, tours | **Medium** integration gap; highest immediate return | Locate → clarify → displayed result → route → “no stairs” → change destination → closure → reroute → reopen, plus a tour and invalid room, through one conversation-and-map surface. Explicit current location and accessibility preferences survive follow-ups. |
| **2** | **Implement Level 4 from a real plan** — L4-01–06 | Common JSON model, validated door placement, transactional saving, isolated what-if | **Very large**; almost the entire required workflow | Accept one supported unseen plan plus scale, extract an editable model, validate it, review/correct one uncertainty, save/reload, then locate and route. Record actual elapsed setup time. Start this alongside the app slice rather than leaving it until optional polish is done. |
| **3** | **Finish Level 3 across buildings** — L3-02–03, remaining L3-01 | Correct single-building multi-floor backend and ordinary floor PNGs | **Large**; both building registry and connecting graph absent | Two buildings with distinct identities, repeated room numbers, an explicit walkway and a constrained route that includes indoor, floor and walkway segments. Fix connector-only floor rendering. |
| **4** | **Close route/input/state correctness gaps** — MAP-03/04, CORE-05, L4-03 | Selected edges, rollback, invalidation and ordinary reroutes already work | **Small–medium** fixes plus **medium** industrial profile work | Fix the reproduced faults below; reject malformed imported maps; keep kit answer compatibility distinct from physical delivery and industrial access rules. |
| **5** | **Prove live behavior and produce valid deliverables** — QA-02/03, SUB-01–06 | Isolated benchmark callable, official scorer, UTF-8 CSV writer | **Medium**, with Sunday schema/input externally dependent | Run the actual agent on a per-kind dev sample and the interaction script, investigate failures, then broaden. Supply `BENCHMARK.md`, validate/generate all 145 public answers and prepare the required demo/explanation. Adapt Sunday input/output only to the announced schema. |
| **6** | **Reconcile status/configuration and freeze low-value expansion** — CORE-03, DOC/REPO follow-up | Package-local imports, working tests, root ignore file, attribution | **Small** | Make setup reproducible, replace stale “missing tool” claims with actual status, keep optional retrieval/landmark/voice/AR work behind the basic-level gates. |

Allocate almost all new implementation effort to the first four rows. The benchmark calculations now need live validation and targeted fixes, rather than another implementation pass.

## Level-by-level implementation coverage

| Level / requirement | Degree implemented | Evidence and remaining gap |
|---|---|---|
| **L1 — conversation** | Implemented CLI; visual interaction partial | `final_agent/agent.py:226` constructs tools/history; `:303` runs terminal input and prints replies. No application surface displays generated maps or offers floor/result selection. A web framework is not mandatory; the missing behavior is the connected view. |
| **L1 — find rooms and equipment** | Substantially implemented | `building_map.py:378`, `:431`, `:760`; `tools.py:87`, `:125`, `:184`: exact filters, pagination, spatial queries, enumeration, inspection, stable IDs and containing-room/floor identities. Synonyms rely on model interpretation/retries; substring search alone is not semantic understanding. |
| **L1 — see the selected thing** | Static rendering implemented; end-to-end display partial | `tools.py:642`, `viewer.py:469`: selected asset marker, containing-room highlight, readable labels and framing. A real machine locate image was visually checked. The CLI prints a path; the locate flow does not enforce calling `show_location` or displaying it. |
| **L1 — ambiguous/unknown requests** | Partial; one verified defect | Most invalid references return actionable candidates/errors. Cross-kind exact-name ambiguity can silently resolve to an unrelated containing room; see F4. No live tricky-user script was run. |
| **L1 — current location and preferences** | Partial | Conversation history and `active_request` retain some facts/route parameters. No explicit current-location, preferred accessibility or selected-building session state exists. A destination request is not an application-owned location update. |
| L1-05 / L2-06 — landmarks | Tool support implemented; workflow partial | `building_map.py:1629`, `:1809`; `tools.py:522`, `:718`: floor-scoped candidates, size/competitor accounting, destination context and map marker IDs exist. `directions()` does not integrate landmark cues; normal locate/route flow does not require lookup. This is useful interaction support, not a reason to postpone the basic surface. |
| L1-06 — typed tasks/completion controller | Missing; prompt-only fragment | Prompt evidence rules exist; request classes, validating dispatcher, map-revision checks and application-owned completion are absent. These are project-specific design requirements. A small explicit session/task state can close the core reliability gap without building a generic framework first. |
| **L2 — A→B** | Implemented backend; app verification partial | `building_map.py:651`, `tools.py:206`: route distance, ordered graph nodes, spaces, selected openings/connectors, floor segments, legs and directions are retained. Rendering uses selected geometry, not a newly guessed door. |
| **L2 — step-free and width constraints** | Implemented backend | `building_map.py:514`: filters steps, closed elements and openings below the inclusive width threshold; preserves parallel stair/lift edges. Tests cover equality, narrow/stepped entrances and unreachable cases. Preference retention still needs live verification. Physical-delivery and forklift caveats appear below. |
| **L2 — close/reopen and reroute** | Substantially implemented; recovery edge case remains | `tools.py:570`, `:583`, `:593`: close/reopen rooms, doors, stairs/lifts; save closures, recompute active request, invalidate stale route, roll back failed save. An explicit unsuccessful retry erases the requested journey, so reopening cannot revive it (F5). Images are generated separately. |
| **L2 — ordered multi-stop tours** | Implemented backend | `compute_route(..., via=...)` preserves order/repeated visits, leg boundaries, selected edges and total length; unreachable legs are named. Complete conversation/leg presentation remains unverified; cumulative leg totals are not explicitly supplied as a field. |
| L2-05 — optimized stop order | Implemented backend | `building_map.py:1453`, `tools.py:439`: exact optimizer through 10 intermediate stops, fixed endpoints, repeated stops, constraints, pure preview and activation. Tests compare against exhaustive permutations. Current prompt explicitly uses `activate=false` for comparisons; the earlier contradiction was fixed during concurrent integration. No rewrite is warranted. |
| **L3 — several floors, stairs and lifts** | Mostly implemented in one building | `building_map.py:514`, `:607`, `:735`: elevations, consecutive stair stops, direct lift rides, floor segments and handoff directions. Real ground→floor-3 step-free route rendered two understandable PNGs. Negative/nonconsecutive floor costs were also checked. Connector-only routes can omit every image (F2). |
| **L3 — several buildings and identity** | Missing | One `BuildingMap` per `BuildingAgent` and one CLI building argument. No registry, building-scoped tool query, explicit selection or multi-building session. Separate CLI runs are not a multi-building workflow. |
| **L3 — connecting walkways** | Missing | No link model, joined graph, walkway costs/closures/accessibility, cross-building route tool or combined presentation. Do not implement this by restoring the prohibited single-building outside shortcut. |
| **L4 — plan input and calibration** | Missing | `storage.py:17` loads JSON only. No image/PDF intake, scale/known-dimension collection, floor metadata or common-frame calibration. |
| **L4 — extract rooms/equipment/connectivity** | Missing | No extraction from plans into polygons, room types/names, openings, entrances, connectors or assets; no uncertain-geometry review or incoming source-attribution capture. Existing dataset images are inputs, not an ingestion implementation. |
| **L4 — validate before navigation** | Missing pipeline; local checks exist | `building_map.py:180` indexes raw data without boundary validation. Individual edit/spatial methods check some geometry, but imported duplicate IDs and impossible cross-floor openings are accepted (F1). |
| **L4 — conversational update and review** | Small fragment | Permanent `add_door` and closure edits exist with useful validation/rollback. No room rename/type/boundary correction, general connector repair, visual edit preview, apply/cancel or undo. What-if correctly uses a clone and does not persist changes. |
| **L4 — export/reload and navigate** | Storage foundation implemented; level workflow blocked | `storage.py:24`, `building_map.py:2008`: atomic JSON replacement, metadata/custom fields and closure snapshots round-trip. Saved file can be passed back to CLI. A validated newly extracted plan cannot yet reach this stage; default sessions can overwrite each other (F3). |
| **L4 — new building in minutes** | Missing/unverified | No unseen-plan ingestion demonstration, recorded setup duration or geometry/correction/navigation acceptance flow. |

No complete Level 1–4 product workflow was established by a live model acceptance run in this audit. That does not mean their existing components are absent.

## All nine scored question kinds

Every kind has a registered deterministic tool. The existing component runner supplied train/dev **resolved `inputs`**, formatted replies from actual tool results and used the unchanged official scorer. These checks establish computation and tool contracts; they do not establish interpretation or the model's final reply formatting.

| Kind | Actual tool | Dev passed / total | Public test questions | Important semantics checked |
|---|---|---:|---:|---|
| `largest_room` | `find_largest_room` | 20 / 20 | 21 | Exact subtype/floor, polygon area, selected room before alternatives |
| `floor_area_total` | `sum_floor_area` | 31 / 31 | 33 | Complete aggregation beyond display pages; matching halls included |
| `straight_line_3d` | `straight_line_distance_3d` | 13 / 13 | 15 | Polygon centroids and actual floor elevations, not route anchors or floor numbers |
| `room_stacked` | `find_stacked_room` | 9 / 9 | 9 | Next available floor and maximum overlap; frame warnings |
| `shared_walls_count` | `count_shared_walls` | 24 / 24 | 26 | Same-floor eligible types, 1 m length, 0.35 m wall tolerance, corner exclusions |
| `wide_delivery_count` | `reachable_rooms` | 19 / 19 | 18 | Step-free/width traversal, eligible room counts, entrance convention below |
| `step_free_reachable_count` | `reachable_rooms` with query-only closure | 1 / 1 | 0 | Named lift closure, isolated state, complete target-floor count |
| `errand` | `plan_errand` | 19 / 19 | 20 | Nearest reachable pickup by route distance first, then largest destination; both legs |
| `what_if_door` | `analyze_what_if_door` | 2 / 2 | 3 | Shared-wall door on a clone, nearest exit, strictly >1 m improvement; original state unchanged |
| **Total** | **All nine kinds** | **138 / 138** | **145** | No scored kind left unchecked |

Scarce-kind train supplements also passed: **2/2 what-if doors and 1/1 lift-outage reachability**, covering all four labelled what-if examples and both labelled lift-outage examples across train/dev. Synthetic tests cover additional boundaries. Zero public questions for a kind does not justify removing its implementation.

## Reproduced faults and concrete impact

| ID / priority | Fault and evidence | Effect and smallest corrective work |
|---|---|---|
| **F1 — P1 now; required before Level 4 navigation** | **Imported maps are not validated.** `building_map.py:180` silently overwrites duplicate space IDs in dictionary comprehensions. `graph()` at `:514` accepts an opening shared by spaces on different floors. A synthetic step-free ground→upper-floor opening, with no vertical connector, returned a **0.0 m** route. Four source space records with one duplicate became only three indexed spaces. | Generated/edited plans can appear navigable while losing rooms or creating impossible routes. Validate unique IDs, metre/finite coordinates, polygons, references, opening floor/endpoints/position and connector stop alignment before indexing/routing. This repro does not assert that supplied kit data contains the malformed records. |
| **F2 — P1** | **Valid connector-only routes generate no map.** `viewer.py:450` derives floors solely from `route_polylines`; connector edges are skipped at `:70`. In `proc-campus-dev-002`, route F0-S005→F3-S005 with `step_free=True` returns **26.4 m** and two handoffs, but `show_route` returns `images=[]`, `floor_levels=[]`. | Breaks required multi-floor presentation; connector endpoint floors can disappear even on otherwise drawable routes. Derive visited floors from route nodes/stops/floor segments/handoffs, including zero-length visits. |
| **F3 — P1** | **Default saved outputs collide.** `agent.py:21`, `:341` share `agent_output`; `tools.py:571` writes every edit to `building_edited.json`; `viewer.py:462`, `:474` name images only by floor. Two different maps sharing an output directory reported the same snapshot path; the second replaced the first building and closure set. | A user can lose the first session's saved work and old image paths can show a later result. Use building/session output directories and explicit resume selection. Atomic replacement does not prevent this logical overwrite. |
| **F4 — P1** | **Ambiguous names can silently select the wrong entity.** `building_map.py:458`, `:796`, `:1764`: name rooms A and B “Printer” and one asset in U1 “Printer”. Search returns all three, but `resolve_space("Printer")` returns U1; `select("Printer")` selects U1 as a space rather than the asset. | Violates the targeted-clarification/identity contract. Resolve exact ambiguity across both spaces and assets, then use explicit IDs to preserve selected entity kind. |
| **F5 — P2, include in Level 2 acceptance** | **An explicit failed reroute erases the desired journey.** `building_map.py:714–716` clears `active_request` before computing. Route left→right; close D1; retry the same now-unreachable route; reopen D1. No active route is recovered, and `show_route` says “No route has been computed yet.” | The normal closure recompute path retains the request, but an explicit retry loses it. Preserve a validated requested journey/constraints across an unreachable result while clearing the old computed path; reopening can then recover it. |
| **F6 — P1 delivery** | **CSV writing does not validate a complete submission.** `benchmark/evaluate.py:68`, `:94`, `:117`: API failures become blank replies; filtered/sampled/empty input still reaches the CSV writer. It checks neither required IDs nor nonempty replies, committed answer validity or size. `benchmark.py:35` returns raw model prose. | A command can finish with a success-looking CSV that is blank, partial or incorrectly formatted. Add submission validation around the runner: exact 145-ID coverage for public output, uniqueness, nonempty UTF-8 replies, required final answer structure, numeric cardinality, CSV readability and ≤5 MB. Keep the official scorer unchanged. |
| **F7 — P2** | **Rendering failures leave changed selection and raw errors.** `tools.py:654`, `:684` catch only `MapError`; an output path occupied by a regular file produces `FileExistsError`, after locate selection changes. | The installed SDK catches the exception and reports it to the model with a traceback; this is not an inevitable CLI crash. Convert expected filesystem/rendering failures to actionable errors and restore prior selection if generation fails. |
| **F8 — verification limitation** | **Warm-up scoring can pass without the requested result.** `evaluate.py:38` accepts a missing route for expected-unreachable cases; reachable checks compare distance without endpoints/path/constraints. Empty prose passes both in minimal reproductions. Oracle locate directly assigns the expected asset (`:63`). | 369/369 is useful compatibility evidence, not complete navigation or live accuracy. Add an acceptance check of actual endpoints, constraints, valid transitions and explicit unreachable outcome when using this evaluator to judge product readiness. Do not change `benchmark/score.py`. |

**Additional announced route rules are still missing.** `building_map.py:514` has no forklift-only space/edge eligibility or destination-only production-bay transit profile. On `proc-factory-dev-003`, `compute_route(F0-S001, F0-S003, min_width_m=3)` returns **34.2 m** through **Production H-A1 → Assembly H-A2 → Additive H-A3**. The intermediate bay is invalid when the announced destination-only rule applies. A 3 m opening filter alone does not establish forklift validity. Add an explicit industrial profile while retaining the public kit model.

**Two documented compatibility conventions require application care:**

- `walking_lengths()` (`building_map.py:104`) uses the inherited **1.5× straight-line fallback** when no visibility walk exists. `walking_path()` then returns an empty path; rendering leaves a gap. This is explicit kit compatibility, not a newly introduced regression or proof of valid navigation. The reviewer checked all **229 dev warm-up route/tour cases**: **197 reachable, 32 unreachable**, with no undrawable fallback on selected reachable paths. Unseen/malformed geometry remains a concern; expose validity or use strict validation for actual navigation without silently altering benchmark semantics.
- `usable_entrances()` (`building_map.py:863`) intentionally does not enforce a narrow entrance's width when the entrance is supplied as a **room reference**, matching labelled benchmark conventions and returning a warning. An explicit opening ID does enforce width. For physical deliveries, resolve the actual entrance and enforce its width; preserve the labelled counting convention separately.

## Work that currently adds little progress

1. **Do not rebuild analysis tools because old checkboxes say they are missing.** BEN-01–09, exact filters, inspection, pagination, constrained reachability, route identities, transactional edits and optimized tours are implemented. Current checks support that assessment. Their remaining gates are specific integration, edge cases and live verification.
2. **Freeze semantic retrieval expansion.** `run_library.jsonl` contains exactly **one accepted train example per kind**. `run_library.py:135` filters by kind before similarity, so Qdrant/FastEmbed cannot change the selected example today. Nevertheless the default adapter initializes the index/model (`benchmark.py:20`, `run_library.py:116`, `embedding.py:39`), adding a first-run model download and dependencies. Existing examples can remain useful; a simple per-kind lookup would currently select the same runs. More retrieval work needs multiple candidates and measured benefit. The documented 17/17 versus 17/17 A/B sample shows no gain and was not rerun here.
3. **Avoid enlarging prompt/specification work without application state.** Stronger evidence instructions cannot themselves remember an actual location, preserve a pending journey or prove a map was displayed. Implement the smallest explicit state and completion checks that the required flows need before a large typed-task framework.
4. **Pause extra landmark/rendering polish and optional voice/AR/3D features.** The current static map is usable when opened; the large gap is the connected surface. Landmark tools already exist but need integration. None substitutes for missing multi-building or plan ingestion workflows.
5. **Do not treat repeat oracle runs as live progress.** The historical `agent_output/benchmark/final-dev-smoke.jsonl` has 2/9 correct, including “tool unavailable” failures from an earlier implementation. It is stale, not a score for this checkout. The documented small A/B result is also not current full-dev evidence. A fresh actual-agent sample is the next meaningful accuracy measurement.

## Configuration, delivery and repository checks

| Item | Status |
|---|---|
| Canonical package/imports | Implemented: package-local `final_agent`; benchmark default uses its adapter; starter-import isolation tests pass. No duplicate production agent package found. |
| Persistence/indexes | Atomic saves, cleanup, metadata/custom-field preservation, closure reload, input-data preservation, per-floor STRtree and edit invalidation work in existing tests. No database/service migration is needed. |
| Benchmark/session isolation | Fresh map/conversation and temporary outputs per question (`benchmark.py:41`); query-only closures and door what-if do not leak state. Interactive output isolation is F3. |
| Label boundary | Production answer code does not import evaluation/training labels. `train_runs.py` uses train/dev labels to accept generated examples; committed examples are train-only. Do not use `--all` to train on dev and then report an independent dev score. |
| Answer formatting | Official scorer enforces committed `Answer:` rules and tolerances. Prompt/tool docs describe them, but raw live reply validity is not programmatically enforced before output (F6). |
| Public test answers | Template verified: **145 rows, 145 unique IDs, 0 nonempty answers**. No generated complete public-answer CSV found in the repository. |
| Required `BENCHMARK.md` | Missing. `usage.md` and README contain useful development commands but do not supply the required named single-command submission document. |
| Sunday adapter | Missing announced-schema adapter. Existing runner reads split-layout `*/questions.jsonl`; it does not accept arbitrary standalone question files or write the potential structured route output. Exact schema/time/input remain external; do not invent them. Route nodes and selected elements are already retained for an adapter. |
| Setup/configuration | `.env.example` referenced by setup is absent. Model/effort are hard-coded module constants, while output directory is configurable. Available model/service facts were not checked externally; no claim is made about current availability/pricing. |
| Live run telemetry | Adapter exposes no aggregate `usage` to the runner; no per-question latency log. Training cost uses the fixed Opus-labelled table despite configurable/default Sonnet. Report actual configured cost rather than treating those estimates as verified prices. |
| Demo/explanation/submission | No demo video or completed submission package found in this checkout. README has architecture material that can seed the short explanation. No external platform submission state was checked. A working required-level demo remains unverified. |
| Attribution | `ATTRIBUTION.md` and per-building metadata exist; storage preserves metadata. New plan ingestion must capture its own provenance. The absent furniture catalogue is a generation reference, not a core product blocker. |
| Hygiene | Root `.gitignore` now exists and covers bytecode, environment files and OS metadata; no tracked bytecode/`.DS_Store` found. REPO-01's description of a missing ignore file is stale. Referenced local files missing include `BENCHMARK.md`, `.env.example`, `TASK_TARGET_OBJECT_HANDOFF.md` and the furniture catalogue; `F15_HANDOFF.md` is present. |

The old README section 9 and several backlog paragraphs still describe missing widths, inspection, pagination, highlights, route invalidation/rollback and all nine tools. Those claims conflict with current code. The audit notes in README/BACKLOG direct readers here; task acceptance should now be reconciled feature by feature rather than blanket-marking whole product levels complete.

## Verification actually performed

All checks were offline with no live model calls or API credit spending. The existing environment was reused; no new dependency was installed.

| Check | Result | Limit |
|---|---|---|
| Full suite after concurrent integration | **202 tests run; 199 pass, 3 skip** | The three credential-dependent tests skip because credentials are configured. Mocked agent tests verify plumbing, not live interpretation. |
| All dev scored component cases | **138/138 pass**, every kind covered | Labelled resolved inputs and deterministic reply formatting; not a live benchmark score. |
| Scarce train component cases | **3/3 pass** | Two what-if doors and one lift-outage count; supplements scarce dev coverage. |
| Corrected dev warm-up oracle | **369/369 pass** | Labels supply requests/answers; scorer limitations F8 apply. |
| Focused route suites, independent reviewer | **61/61 pass** | Routing, best tours, reachability, errands, what-if. |
| Storage suite, independent reviewer | **8/8 pass** | Atomicity, round-trip fields/closures, spatial invalidation and isolation. |
| Selected dev route geometry audit | **229 cases checked; 197 reachable, 32 unreachable; 0 selected fallback gaps** | Oracle endpoints/closures; does not establish safety on arbitrary imported maps. |
| Actual rendered views | Equipment locate, factory step-free/width route, ground→floor-3 lift route generated and visually inspected | Confirms representative static outputs; no live chat/UI acceptance run. |
| Synthetic reproductions | F1–F5, F7 and F8 reproduced; F6 verified in writer/error/filter control flow | Not fixes; existing suite does not catch all these cases. |

Commands for the main reproducible checks, from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/talk-building-audit-mpl .venv/bin/python -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/talk-building-audit-mpl .venv/bin/python bench_analsysis/run_tests.py --mode components --split data/dev
PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/talk-building-audit-mpl .venv/bin/python bench_analsysis/run_tests.py --mode components --split data/train --kind what_if_door --kind step_free_reachable_count
PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/talk-building-audit-mpl .venv/bin/python -m final_agent.evaluate data/dev --oracle
```

The component evidence fingerprint was compared with current source after completion: no production Python/scorer file changed after that check. Short SHA-256 snapshot identifiers: `agent.py` `2971843a6faf`; `building_map.py` `aba2769ac27b`; `tools.py` `b08026a43b5a`; `viewer.py` `09df717357c1`.

**Next implementation gate:** demonstrate Level 1–2 through one connected conversation/map, begin the minimal Level 4 plan pipeline in parallel, and finish Level 3 building/walkway navigation. Keep the existing deterministic core, fix the reproduced defects in those slices, and use live acceptance plus validated submission artifacts to establish completion.
