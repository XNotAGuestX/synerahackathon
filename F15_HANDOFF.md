# F15 handoff: agent integration, answer formatting and delivery docs

**For the next AI implementing F15.** F15 was implemented once (three phases),
verified, and then **reverted at the user's request** so that you can redo it.
This document records the scope, the current repository state and everything
learned while building and verifying it, so you do not have to rediscover it.
Read [AGENTS.md](AGENTS.md) (hard rules) and sections 1, 2, 17 and 18 of
[IMPLEMENTATION_HANDOFF.md](IMPLEMENTATION_HANDOFF.md) first.

The reverted implementation stays in git history. Inspect or reuse any file:

```bash
git show 553e25f:final_agent/agent.py         # prompt with the F15 sections
git show 553e25f:final_agent/benchmark.py     # answer() + submission validator
git show 553e25f:tests/test_agent_integration.py
git show 553e25f:BENCHMARK.md
git show 553e25f:final_agent/README.md        # tool reference with examples
git diff 253b4fa 553e25f -- README.md BACKLOG.md FEATURE_SHORTLIST.md bench_analsysis/README.md
```

`253b4fa` is `main` just before F15; `553e25f` is `main` with F15 complete.

## 1. Scope

F15 makes the language model use the deterministic tools correctly and makes the
benchmark run reproducible. Deliverables:

1. **System prompt** (`final_agent/agent.py`, `SYSTEM_PROMPT`): a compact
   tool-selection guide, the conversation distinctions of handoff §17 and the
   exact `Answer:` formats. Preserve the team's existing prompt structure and
   rules; change stale claims deliberately, never replace the whole prompt.
2. **Integration regression test** (`tests/test_agent_integration.py`).
3. **Submission validator** with a CLI (`python -m final_agent.benchmark --check <csv>`).
4. **`BENCHMARK.md`**: the one command, setup, inputs/outputs, state isolation,
   free checks, honest status. Plus **`.env.example`** (`ANTHROPIC_API_KEY=` only).
5. **Docs to the verified extent**: `final_agent/README.md` tool reference; root
   `README.md` status line, section 9 and section 12; `BACKLOG.md` ticks with
   evidence; `FEATURE_SHORTLIST.md`; a dated update note in
   `bench_analsysis/README.md`. The original kit text in README sections 1–8 and
   13–14 stays untouched. `IMPLEMENTATION_HANDOFF.md` status is coordinator-owned.

**Out of scope (user decisions):** any web UI or interactive map surface (the
team's separate frontend track owns it; never describe one as delivered or
pending), and inventing the organizer-dependent Sunday schema.

## 2. Repository state after the revert

- **F01–F14 are merged and verified.** `final_agent/tools.py` registers 21 tools
  (section 4). Unchanged by the revert.
- **Restored to their pre-F15 versions:** `final_agent/agent.py` (the team's
  original prompt, which already mentions `find_best_tour`), `final_agent/benchmark.py`
  (`answer()` only), `final_agent/README.md`, `README.md`, `BACKLOG.md`,
  `FEATURE_SHORTLIST.md`, `bench_analsysis/README.md`.
- **Deleted:** `BENCHMARK.md`, `.env.example`, `tests/test_agent_integration.py`.
- **Consequence:** the reverted docs describe the pre-implementation state
  (e.g. "the nine scored kinds still need dedicated analysis tools"). They are
  stale until you redo item 5. The verified facts you need are in sections 7 and 10.
- **Kept (not F15):** `bench_analsysis/run_tests.py` with `--mode components`
  (coordinator's labelled checker) and `IMPLEMENTATION_HANDOFF.md` status.

## 3. Environment facts that cost time

- Windows + PowerShell. `uv` is not installed: use
  `.venv\Scripts\python.exe` from the repository root and prefix commands with
  `$env:PYTHONDONTWRITEBYTECODE=1;`. Python stderr shows a PowerShell
  "NativeCommandError" banner; ignore it and read the real output.
- Printing `→`, `²` or `ü` to the console raises `UnicodeEncodeError` (cp1252):
  set `$env:PYTHONIOENCODING="utf-8"`.
- `Set-Content -Encoding utf8` writes a BOM that breaks Python scripts. Pipe
  scripts through stdin (`@' ... '@ | python -`) or write files with an editor tool.
- Inline `python -c` with regex/triple quotes breaks PowerShell quoting; use stdin.
- **No `ANTHROPIC_API_KEY`** on this machine: live agent runs are impossible.
  Never claim a live result.
- Data under `data/` is tracked in git. The git identity is repo-local
  (`karol <karol@DESKTOP-LOH2B08>`).

## 4. The 21 registered tools

All return JSON; expected failures are actionable `ToolError`s. Lengths and
areas are unrounded internally and rounded only in tool output. Distances use
the local kit model (`distance_model: "kit"`).

| Tool | Use | Key arguments (bold = required) |
|---|---|---|
| `building_overview` | Floors, stairs/lifts, entrances, closures | none |
| `search_building` | Fuzzy find, or exact inventory: `query=""` + filters; `matches` is the exact total; page with `next_page` | `query`, `floor_level`, `kind`, `room_type`, `asset_type`, `space_type`, `page`, `page_size` (1–100) |
| `list_spaces` | Every space (never assets), paged | `floor_level`, `room_type`, `space_type`, `page`, `page_size` |
| `spatial_search` | Rooms/assets/doors near a point, paged | **`x_m`**, **`y_m`**, **`floor_level`**, `radius_m`, `kind` |
| `inspect_space` | One room: record, area, centroid, doors (width, step-free), stairs/lifts, assets | **`space`** |
| `find_route` | Constrained shortest route; becomes the active route | **`start`**, **`destination`**, `step_free`, `via` (ordered), `min_width_m`, `entrance` |
| `find_best_tour` | Exact any-order tour, ≤ 10 stops; `activate=False` previews | **`start`**, **`stops`**, **`destination`**, `step_free`, `min_width_m`, `activate` |
| `plan_errand` | Nearest pickup by route distance, then the largest destination; total metres | **`start`**, **`asset_type`**, **`destination_room_type`**, **`destination_floor_level`**, `step_free`, `min_width_m`, `activate` |
| `reachable_rooms` | Delivery/reachability counts (one traversal) | **`start`**, `floor_level`, `step_free`, `min_width_m`, `entrance`, `closed_elements`, `room_type` |
| `find_largest_room` | Largest room of an exact type on a floor + area | **`room_type`**, **`floor_level`** |
| `sum_floor_area` | Total area of a room type on a floor | **`room_type`**, **`floor_level`** |
| `straight_line_distance_3d` | Centroid-to-centroid XYZ distance | **`first`**, **`second`** |
| `find_stacked_room` | Room directly above/below (max overlap on the next floor) | **`space`**, **`direction`** |
| `count_shared_walls` | Rooms with ≥ 1 m of wall within 0.35 m | **`space`** |
| `analyze_what_if_door` | Hypothetical door; nothing saved; `count` of target-floor rooms whose exit walk improves by > threshold | **`first_space`**, **`second_space`**, **`floor_level`**, `improvement_threshold_m` |
| `find_navigation_landmarks` | Cues near a route step with an ambiguity count | **`x_m`**, **`y_m`**, **`floor_level`**, **`inner_radius`**, **`outer_radius`**, `min_size`, `kind`, `within_spaces` |
| `describe_destination_context` | Large named rooms "adjacent" (shared wall ≥ 1 m) or "near" a destination | **`space`**, `radius_m` (15), `min_area_m2` (40) |
| `set_closed` | Real closure/reopening, saved; returns `active_route` or `active_route_error` | **`element`**, **`closed`** |
| `add_door` | Real door at the shared-wall midpoint, saved | **`first_space`**, **`second_space`**, `step_free`, `width_m` |
| `show_location` | The only tool that selects/highlights on the map; PNG path | **`element`** |
| `show_route` | PNGs of the active route only (start, destination, numbered stops, handoffs, closures, `landmark_ids`) | `landmark_ids` |

`show_route` errors when there is no active route. `plan_errand` and
`find_best_tour` create one only with `activate=True`.

## 5. Question → tool → answer line (the nine scored kinds)

Floor words: "ground floor" = 0, "the floor N" = N, "basement N" = −N (the overview
in the prompt lists levels and names). Type words may be written naturally:
types are normalized (`"generic room"` → `generic_room`).

| Kind | Question pattern | Call | Final line |
|---|---|---|---|
| `largest_room` | "largest <type> on the floor N … how big" | `find_largest_room(room_type, floor_level)` | `Answer: <room label>, <area_m2> m²` |
| `floor_area_total` | "total floor area of every <type> on the floor N" | `sum_floor_area(room_type, floor_level)` | `Answer: <area_m2>` |
| `straight_line_3d` | "straight-line distance … centres of A and B" | `straight_line_distance_3d(first, second)` | `Answer: <distance_m>` |
| `room_stacked` | "dripping from the ceiling in X" (above) / "leaking onto the floor of X" (below) | `find_stacked_room(space, direction)` | `Answer: <room label>` |
| `shared_walls_count` | "how many other rooms on that floor share a wall with X" | `count_shared_walls(space)` | `Answer: <count>` |
| `wide_delivery_count` | "<w> m wide … can't go on stairs or steps (lifts fine) … arrives through the entrance into X … how many rooms on the floor N" | `reachable_rooms(start=X, floor_level=N, step_free=True, min_width_m=w, entrance=X)` | `Answer: <count>` |
| `step_free_reachable_count` | "Lift 1 is out of service. A wheelchair user comes in through the entrance into X … floor N" | `reachable_rooms(start=X, floor_level=N, step_free=True, closed_elements=["Lift 1"], entrance=X)` | `Answer: <count>` |
| `errand` | "I'm in A … grab a <asset> from the room that has one closest to me, then carry it to the largest <type> on the floor N. I can carry it on the stairs." | `plan_errand(start=A, asset_type, destination_room_type, destination_floor_level)` (stairs allowed → `step_free=False`) | `Answer: <length_m>` |
| `what_if_door` | "What if we add a door between A and B … how many rooms on the floor N … shorter walk out … by more than 1 m" | `analyze_what_if_door(first_space=A, second_space=B, floor_level=N)` | `Answer: <count>` |

Worked examples run through the real tools with arguments written from the
question wording, scored by the unchanged official scorer (all CORRECT):
`osm-way22744230-H01` → `Answer: Generic room N5325, 79.48 m²`;
`proc-campus-dev-000-H03` → `Answer: 11`; `osm-way22744230-H04` → `Answer: 77.36`;
`osm-way27917482-H08` → `Answer: 6`.

## 6. Official scorer facts (`benchmark/score.py`, never modify)

- Only the **last** line starting with `Answer:` counts (`**Answer:**` is fine).
- Numeric kinds: **exactly one number** on that line. The number pattern ignores
  digits glued to a preceding word character or dot: `N5325` is not a number,
  but a ref such as `1.02` **is**. `²` is not a digit; `m2` does not count.
  Ranges, a second number or a room ref on a numeric line fail. Counts are exact.
- Room kinds: the first accepted label (unique ref or name) must appear before
  any rejected label. Non-unique names appear in neither list. `largest_room`
  also needs some number on the line within ±5% of the area.
- **Room label rule (verified):** name, plus ` (ref)` when the name does not
  already contain the ref, e.g. `Büro (1.02)`. Passes all 122 labelled room
  answers; bare names fail 2 (`osm-way37850565`, several rooms named "Büro").
  `run_tests.py` uses the same rule (`room_label`).
- Tolerances: area ±5%, 3D distance ±2%, errand ±1% or ±1 m, counts exact.

## 7. Semantics verified against train/dev labels (do not relearn)

| Area | Verified rule | Evidence |
|---|---|---|
| Areas | Exact `room_type` on the floor; matching halls included | 96 + 181 labels |
| 3D distance | Polygon centroid at the floor's `elevation_m` | 30 labels |
| Stacked rooms | Next available level; all space types are candidates; max overlap | 26 labels, ids exact |
| Shared walls | Same floor, type room or hall; parallel runs (≤ 15°) within 0.35 m totalling ≥ 1 m; corner contact = 0 | 143 labels |
| Reachability | Count broad `type == "room"` incl. the start; traversal through the outside node allowed (no label difference); width equality passes | 82 labels |
| Narrow entrance | Entrance given as a room: counted from inside it, `entry.warnings` reports the narrow door (5 labels require this); entrance given as an opening id: strictly enforced | 5 labels |
| Errand | Nearest pickup by route distance from the start first, then the largest destination; outdoor pickups allowed; not a combined optimum | 93/93 pickup + destination ids |
| What-if | Clone + door at the shared-wall midpoint; type room on the target floor; strictly > 1 m; door narrowed to a shorter shared wall (a labelled pair shares 0.56 m); newly reachable rooms counted (no label covers it) | 4 labels |
| Routes | `element_path`/`space_path` equal the labels | 172/172 routes, 40/40 tour legs, 17/17 unreachable |

## 8. The reverted F15 implementation (reference)

**Prompt.** The final prompt was 7,591 characters (model `claude-sonnet-5-5`,
effort `medium`, 20 tool iterations). It kept every original section and added
two. Retrieve the exact text with `git show 553e25f:final_agent/agent.py`. Core of
the additions:

```text
# Tool selection
- Locate: search_building or inspect_space, then show_location, the only action that
  selects/highlights on the map (search never does). Navigate: find_route.
- Exact inventory: search_building with query="" and asset_type / room_type / space_type +
  floor_level. `matches` is the exact total; follow next_page while has_more.
- Stops in a stated order: find_route with via. Any order allowed: find_best_tour; preview with
  activate=False and activate only when the user chooses it.
- "Grab X from the nearest room that has one, then deliver to the largest Y": plan_errand,
  never find_best_tour.
- Real edits: set_closed and add_door (saved; report active_route or active_route_error).
  Hypothetical "what if we add a door": analyze_what_if_door (nothing saved).
- Delivery / reachability counts: reachable_rooms. step_free for "no stairs or steps (lifts fine)",
  min_width_m for a load's width, entrance = the start room for "arrives through the entrance
  into X", closed_elements for outages. If `entry.warnings` exist, say so in prose.
- Areas: find_largest_room, sum_floor_area. Through the air: straight_line_distance_3d.
  Above/below: find_stacked_room. Neighbours: count_shared_walls.
- Step cues: find_navigation_landmarks (only `is_unambiguous` cues; nearby is not visible;
  never invent left/right). Arrival context: describe_destination_context ("next to" only for
  relation "adjacent", otherwise "near"); pass the mentioned ids to show_route(landmark_ids=[...]).

# Benchmark output
A question that asks for a final `Answer:` line is a one-turn benchmark question: do not ask back;
state a needed assumption briefly and still finish with the Answer line, even after explanation.
- Numbers: `Answer: <one number>`. No unit, no room names or numbers, no range, no second number,
  no thousands separator. Counts are integers. Use the tool's value.
- Largest room: `Answer: <room>, <area> m²`. Stacked room: `Answer: <room>`.
- Name a room by its name plus its ref in parentheses when the name lacks the ref (`Büro (1.02)`).
```

Smaller edits: "count, area" added to the facts-from-tools rule; "the overview
below is the starting state" (instead of "call building_overview initially");
"results are paged"; `min_width_m` in the Route section; `find_best_tour`
offer uses `activate=False`; `show_route` only after an activating call.

**Integration test** (9 tests): each tool has a name, description and valid
schema matching its signature; registered tools exactly equal the test's `CALLS`
keys and every tool-like name in the prompt is registered; one real `.call()`
per tool on `data/dev/proc-factory-dev-003` returns JSON; answer lines built
from tool values pass `score_reply`; forbidden formats (range, second number,
ref in a count, no Answer line) fail; the room-label rule; validator cases.

**Validator** (`validate_submission(csv_path, template_path)` + `--check`):
UTF-8; header exactly `question_id,answer` (no BOM); exactly the template's 145
unique ids (missing, extra, duplicate reported); non-empty replies; an `Answer:`
line in each (via `benchmark.score.committed_answer`); strict CSV parsing and a
write/read round trip; ≤ 5,000,000 bytes; non-zero exit on failure. The empty
`data/test/submission_template.csv` is correctly rejected (145 empty replies).

**BENCHMARK.md** commands:

```bash
uv sync && cp .env.example .env    # set ANTHROPIC_API_KEY
uv run --env-file .env python -m benchmark.evaluate data/test --agent final_agent.benchmark:answer --name final-feature-handoff-test --submission-csv agent_output/submission.csv
uv run python -m final_agent.benchmark --check agent_output/submission.csv
uv run --env-file .env python -m benchmark.evaluate data/dev --agent final_agent.benchmark:answer --per-kind 1 --name final-dev-smoke
```

Include the `.venv\Scripts\python.exe` equivalents and a PowerShell snippet that
loads `.env` into the environment.

## 9. Pitfalls and lessons

- **Identical questions with different answers exist.** `osm-way37850565-H02`
  and `-H03` both read "…ceiling in Büro (Ground floor)…" but expect `1.02` and
  `1.03`; three ground-floor rooms are named "Büro". `osm-way27917482-Q09` names
  three rooms sharing name, ref and floor. Tools reject ambiguous names with
  candidate ids, which is correct. In a one-turn benchmark the model must pick
  one and state the assumption; no text-only agent can get both H02 and H03.
- Use the tool's returned value on the Answer line; never recompute or re-round
  differently. Keep entrance warnings in prose; the Answer stays the count.
- `show_route` draws only the active route; previews (`activate=False`) never
  replace it, and an unreachable request leaves no route to draw.
- Route drawings follow the kit model (room centre → door), so a line can run
  to a corridor's centre and back: faithful to the computed metres.
- The prompt is sent on every call and the 21 tool descriptions are long; keep
  additions compact (the system block is prompt-cached).
- Component checks (`run_tests.py --mode components`) feed labelled resolved
  inputs to the tools: they prove computation, not interpretation. Only a live
  run measures the prompt.

## 10. Verification after redoing F15

```bash
python -m unittest discover -s tests -v              # 161 tests after the revert; F15 added 9
python -m final_agent.evaluate data/dev --oracle     # 369/369
python bench_analsysis/run_tests.py                  # 45/45 PASS, 6/6 format checks
python bench_analsysis/run_tests.py --mode components --split data/dev    # 138/138
python bench_analsysis/run_tests.py --mode components --split data/train  # 517/517
```

Per kind, dev/train: largest_room 20/76, floor_area_total 31/150,
straight_line_3d 13/17, room_stacked 9/17, shared_walls_count 24/119,
wide_delivery_count 19/61, step_free_reachable_count 1/1, errand 19/74,
what_if_door 2/2 (all passing). Other coordinator checks: best tour equals brute
force on 79 real tours; landmark ambiguity 601 brute-force candidates with 0
mismatches; what-if leaves map state and files byte-identical.

With credentials: run the per-kind dev smoke, inspect failures (interpretation
vs formatting vs tool), then all 138 dev questions, then the public test CSV and
`--check`. Report live numbers separately from component numbers.

## 11. Open beyond F15

Interactive surface (team frontend track); L2-04 live interaction script;
L3 multiple buildings and walkways; L4 plan ingestion; the Synera
wall-respecting route model; edit preview/undo; QA-03, SUB-01 and SUB-02 need a
live run.
