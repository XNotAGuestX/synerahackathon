# Talk to Your Building: Agent-First Indoor Navigation

> **Consolidated project description — 24 October 2026.** This is the project reference for the challenge, existing implementation and open problems; [BACKLOG.md](BACKLOG.md) tracks the remaining implementation work. This document combines the original root README, both agent READMEs, the supplied challenge PDF and the code review. Original grading, scoring, submission, data-format and reference wording is preserved; the assessment and proposed work are labelled separately. Package READMEs link here.

| Find | Sections |
|---|---|
| Challenge, levels, grading and Sunday benchmark | [1. The challenge](#1-the-challenge) |
| Synera clarification: route validity, distances, forklift rules and scoring | [Route scoring clarification](#route-scoring-clarification-synera) |
| Dataset, schema, route model and question definitions | [2. What's in the kit](#2-whats-in-the-kit), [3. Data format](#3-data-format), [4. Questions](#4-questions) |
| Run, evaluate, score and submit | [5. Quick start](#5-quick-start), [6. Submission format](#6-submission-format), [7. Rules and tips](#7-rules-and-tips) |
| Current features and verified evaluation | [9. Current implementation](#9-current-implementation-and-verified-baseline) |
| Prioritized tasks and acceptance criteria | [Implementation backlog](BACKLOG.md), [10. Tasks](#10-tasks-priorities-and-completion-criteria) |
| Unresolved requirements and source discrepancies | [11. Open decisions](#11-open-decisions-and-source-discrepancies) |
| Consolidated agent commands, tools and storage reference | [12. Consolidated agent reference](#12-consolidated-agent-reference) |
| Complete challenge PDF text, including its grading table | [13. Challenge PDF reference](#13-challenge-pdf-reference) |
| Full data attribution | [8. Licences](#8-licences), [14. Data sources and licences](#14-data-sources-and-licences) |

**Current status:** `final_agent` is independently wired and packaged: CLI, tools, viewer, evaluator, building map and storage use local modules. The kit's `starter_agent` was removed on 24 October 2026 after `final_agent` was verified to contain all of its files, map functions and tools; `benchmark.evaluate` now runs `final_agent.benchmark:answer` by default. Its storage/integration suite passes 11 tests; its free dev warm-up passes 369/369. The scored runner selects it with `--agent final_agent.benchmark:answer`, using fresh state and temporary outputs per question. The nine scored benchmark kinds still need dedicated analysis tools; no live benchmark score or generated test answers are claimed. Sunday output format and release time remain organizer-dependent. See [final-agent commands](final_agent/README.md), [BACKLOG.md](BACKLOG.md) and sections 9–11.

[FEATURE_SHORTLIST.md](FEATURE_SHORTLIST.md) records proposed features, prompt-related implementation gaps and the future switch to automatic mobile location updates; these capabilities remain unimplemented.

[IMPLEMENTATION_HANDOFF.md](IMPLEMENTATION_HANDOFF.md) specifies the requested paginated search, room inspection, reachability, all nine analysis kinds, optimal tours, navigation landmarks and map highlights. It assigns one Sonnet implementation agent per feature and requires independent verification afterwards; it is an implementation specification, not a claim that these features are complete.

[Benchmark request analysis](bench_analsysis/README.md) reviews 280 questions across 20 varied dev buildings, with implementation/missing-tool tables, underdocumented expected results and 45 runnable representatives in three difficulty tiers. Its offline evidence distinguishes passing component checks from missing capabilities; it does not claim live benchmark accuracy.

The original kit reference follows. References such as “section 6” below retain their original numbering. The repository tree and setup instructions are source reference material; section 9 covers implementation additions, and section 11 identifies missing referenced setup resources.

**Industrial Agents Hackathon 2026**, in cooperation with UVC Partners and Anthropic. This is the student kit for Track 01.

## The story

You have walked into an office complex or a factory hall and had no idea where to go. Outdoors we solved this long ago: type where you want to be, and a map shows the way. Indoors, floor plans are PDFs, machines live in spreadsheets, and the one person who knows where the 3D printer is has gone home.

**Your mission:** give any building its own map you can talk to. Feed your system a floor plan and it learns the building. Then anyone can just talk to it.

A factory hall is a building that never stops changing. Machines move, aisles get blocked, deliveries arrive every hour. Think of the people who ask:

- **Service technician:** *"Which of the three presses is line 4, and how do I get there?"*
- **Forklift driver:** *"Aisle 4 is blocked. Fastest route to dock B?"*
- **Logistics:** *"Where is the steel drum delivered yesterday?"*

Questions your agent should answer:

- **Find:** *"Where is the 3D printer?"*
- **Route:** *"How do I get from the lobby to the CNC mill on floor 2 without stairs?"*
- **Edit:** *"Add a door between rooms 2.03 and 2.04."*
- **React:** *"The east lift is closed for maintenance. What changes?"*

## What you build

An app you talk to. It shows 2D or 3D views of buildings and floors, animated routes, and the things inside: rooms, desks, machines, equipment. It works for an existing building and can set up a new one quickly from floor plans.

The **agent** is the interaction layer: you say what you want and the system does it. The **core** underneath is mostly deterministic: a graph of rooms, doors, corridors, stairs and lifts, and a search that finds the best route.

This kit has everything you need to start. No company data and no NDA; everything is public or generated.

- **Data:** 280 buildings with floor plans, equipment lists and plan images.
- **Questions:** train and dev questions with answers, and the test questions you are scored on (without answers).
- **A working starter agent** built on the Claude API.
- **A scorer**, so you can measure yourself on dev before you submit.

Credits for Claude, Lovable and ElevenLabs come via the organizers. UX and voice can play a real role: a voice-in, voice-out agent counts towards Interaction.

---

## 1. The challenge

### Levels (each builds on the previous)

Every level earns points and builds on the one before, so a team that stops early still has something that works. This is the floor, not the ceiling: hit it first, then surprise us.

1. **Locate:** on one floor, talk to the agent, find things and see them on a view.
2. **Route:** A to B on one floor, with step-free routes, closed areas and multi-stop tours.
3. **Scale:** several floors, then several buildings, with stairs, lifts and walkways between them.
4. **Build:** create or update a building from floor plans, by conversation. A new building should take minutes, not days.
5. **Extend (optional, pick one and do it well rather than three badly):**
   - **Make things move:** tools or machines that change place via barcode, RFID or "this is now here", so the map stays current.
   - **Several users:** colleagues update the building while others ask questions.
   - **Industrial logistics:** route forklifts and materials through a hall with blocked aisles and delivery points.
   - **Capture on site:** build a new building by walking through it with a phone instead of starting from a floor plan.
   - **Accessibility:** wider doors, step-free and quiet routes.
   - **Presentation:** isometric stacked floors, animated routes, voice in and out.
   - **AR:** the route as an overlay on your phone. The hard part is knowing where you are (QR codes at doors, WiFi, other tricks).

   Or surprise us.

### Directions, not instructions

How you get there is up to you. A few directions that save hours:

- **Think in a graph.** Rooms and junctions are nodes; doors, corridors, stairs and lifts are edges; Dijkstra or A* finds the route. Agree on the data model in your first hour.
- **One floor first.** Make one question work end to end before 3D or a pretty interface. A flat 2D plan with the route drawn on it is a fine start; three.js gets you extruded floors later.
- **Spend your time on decisions.** AI writes most of the code, so think about the user: what should the agent ask when a request is vague? How does it show what it understood before it changes a plan? "Turn left at the printers" or room numbers?

### Put yourself in their shoes

Design for people, not for the jury. Would you trust this agent in a building you have never been in?

| Who | What they need |
|---|---|
| First day at work | Knows no room names. Asks "where do I get coffee?" |
| Wheelchair user | Step-free routes and wide doors, every time, without asking twice. |
| Service technician | Hands full, phone in pocket. Wants voice and "turn left at the press". |
| Facility manager | Moves a machine, closes a lift, adds a door. The map must keep up. |

Use what is possible today: voice in and out, an agent that asks back, showing what it understood, live updates from a scan, AR on the phone, directions people can follow.

### Judging

Three things count, in this order: does it work, is it a pleasure to use, and what did you add that we did not ask for.

| Part | Points | What counts |
|---|---|---|
| Does it work | 55 | The Sunday benchmark plus automatic checks on buildings and questions you have not seen (levels 1–4): correct answers, valid routes, route length vs. the best route, buildings built correctly from plans. **Your test-set submission (section 6) is part of this.** |
| Interaction | 25 | A short scripted conversation with tricky users, rated on a rubric. Does it ask only what it needs, show what it understood, and give directions a person can follow? Voice counts here. |
| Creativity | 10 | Level 5 and add-ins: anything that makes the product better in a way we did not think of. |
| Submission demo | 10 | Your demo video and technical explanation: clear, convincing, and showing the real product. |

### Sunday benchmark

Shortly before code freeze, we release one new building nobody has seen, plus a question file. Your agent has to answer them, including the best routes. Don't tune to the test buildings. Build something that works on any building in this format.

- **Your run:** a single command in your repo, documented in `BENCHMARK.md`, with no manual steps between input and output.
- **Submission:** you run it yourselves and submit the output with your project. We may re-run your command on the same input to verify.
- **Scoring:** correct answers, valid routes and route length against the best route.

The exact release time and the file format for the Sunday building will be announced with the release.

### Route scoring clarification (Synera)

Source: Synera announcement supplied by the team on 24 October 2026. The announcement below describes the automatic route check; its wording is preserved with Markdown formatting.

Hi all, a quick note on how route answers are scored in the automatic check, so you know what to aim for.

#### How we model a building

- Every building is a set of spaces (rooms, corridors, aisles, stairwells, lifts) joined by doors, openings, stairs and lifts.
- Walking distance is measured inside each space, from door to door, staying about 15 cm off the walls. Paths go around corners, never through walls [unless the user is a Jedi]
- Stairs count as 2 m of walking per metre climbed. A lift counts as 15 m (waiting and doors) plus 1 m per metre of height.
- Furniture, equipment and machines are not treated as obstacles. Distances use the room and aisle outlines only.
- A route to a machine or other item ends in the room or bay that holds it, not at its exact position.

#### Rules that apply to some questions

- Without stairs: lifts, ramps and doors only.
- Forklift: forklift aisles and openings only (3 m or wider). Pedestrian walkways don't count.
- Closed or blocked areas must be avoided.
- Factory production bays are destinations. You can drive into one to deliver, but not through one as a shortcut.
- If no route exists under the rules (e.g. upstairs without stairs and no lift), the correct answer is to say so.

#### How your answer is scored

- Give your route as the ordered list of spaces you pass through.
- We check that each step goes through a real door, opening, stair or lift, and that the rules above hold.
- We then measure your route with our distance rule above. Your own distance numbers don't affect the score; what counts is picking the right sequence of spaces.
- Score = best possible length ÷ your length. Within 1% of the best counts as full marks. An invalid route scores 0.

Questions? Ask any of the Synera folks on site or in the channel.

**Implementation impact (project assessment):** this clarification differs from the supplied kit's [anchor-based route model](#the-route-model-behind-the-expected-answers) and [local text-answer scorer](#how-it-is-scored). The current router uses room anchors and fixed per-floor stair/lift costs; it does not yet implement wall-respecting door-to-door paths with approximately 15 cm clearance, height-based vertical costs, a forklift-only routing profile or destination-only production bays. The automatic route check requires a valid ordered space sequence and recomputes its distance; reporting a plausible distance alone is insufficient. Keep local kit compatibility identifiable when implementing these rules. The announcement does not specify an output file schema or release time, and does not resolve the kit's zero-cost outside-node behavior.

### Submission and judging process

There are no pitch rooms. All teams submit online by code freeze through the organizers' platform:

1. A demo video of your app in action.
2. A short technical explanation (architecture and tech stack).
3. Your repository, including `BENCHMARK.md` and your answers file.

We review all Track 01 submissions and pick four finalists. Finalists present at the joint final pitch session at Tacto: 3 minutes plus 1 minute Q&A per team.

---

## 2. What's in the kit

```
README.md                  this file
ATTRIBUTION.md             data sources and licences (read before you share anything)
pyproject.toml             Python project for the project agent and the scorer (uv or pip)
.env.example               copy to .env and add your ANTHROPIC_API_KEY
final_agent/               the project agent (Claude + tools); grew from the kit's starter_agent, removed 24 Oct 2026
benchmark/                 score.py (the official scorer) and evaluate.py (runs an agent, writes the submission)
data/
  manifest.csv             one row per building: split, source, licence, size, lifts, stairs, ...
  train/<building_id>/     200 buildings: plan, equipment, images, questions with answers
  dev/<building_id>/       40 buildings: same as train; use for self-evaluation
  test/<building_id>/      40 buildings: plan, equipment, images, questions WITHOUT answers
  test/questions.csv       all 145 test questions in one table
  test/submission_template.csv   question_id,answer with every test id, ready to fill in
```

Each building directory contains:

| File | What it is |
|---|---|
| `building.json` | The plan in the common format (section 3) |
| `equipment.csv` | One row per piece of furniture, fixture, machine or piece of equipment |
| `floor_<level>.png` / `.svg` | Plan with furniture |
| `floor_<level>_plain.png` | Plan without furniture |
| `questions.jsonl` | Benchmark questions. Answers are included in train and dev, not in test. |
| `questions_basic.jsonl` | Warm-up questions with answers (train and dev only) |

| Split | Buildings | Benchmark questions | Warm-up questions |
|---|---|---|---|
| train | 200 | 517 | 1,761 |
| dev | 40 | 138 | 369 |
| test | 40 | **145 (this is what you submit)** | – |

The buildings come from four sources:
- **Swiss Dwellings:** multi-floor residential buildings.
- **ResPlan:** single-floor homes.
- **OpenStreetMap indoor data for Munich:** TUM buildings, Munich Airport Terminal 2, Pasing Arcaden and others.
- **Procedural:** generated factories (production halls with machines, loading docks, office blocks) and campus buildings (lecture halls, labs, cores with stairs and lifts).

Test procedural buildings use layouts that train never sees: bigger halls, L-shaped wings, basements and more cores.

---

## 3. Data format

### Conventions

- **Units:** all coordinates are **metres** in a local frame, x to the right and y up.
- **One XY frame per building.** All floors share it, so floors stack. One exception: some Swiss Dwellings floors are centred per floor rather than aligned.
- **Floors:** `level` is an integer: 0 is the ground floor, -1 the first basement, 1 the first upper floor.
- **Outside:** an opening whose `space_ids` contain `"outside"` is an entrance.
- **Synthetic parts:** `synthetic: true` marks things this dataset added that weren't in the source data. Examples are recovered stair halls in Swiss Dwellings, lifts mapped only as a point in OSM, and doors guessed where OSM had none.

### `building.json`

```jsonc
{
  "building": { "id": "proc-factory-dev-003", "name": "Fertigung Ost 27", "source": "procedural",
                "source_ref": {...}, "license": "CC0-1.0", "attribution": "...", "split": "dev", "units": "m" },
  "floors": [ { "id": "proc-factory-dev-003-F0", "level": 0, "name": "Ground floor",
                "elevation_m": 0.0, "height_m": 8.0 } ],
  "spaces": [ { "id": "proc-factory-dev-003-F0-S021", "floor_id": "proc-factory-dev-003-F0",
                "type": "room",                 // room | corridor | stair | lift | hall | outdoor
                "room_type": "quality_lab",     // office, lab, toilet, production_zone, ... (see below)
                "name": "Quality lab 0.21", "ref": "0.21",
                "polygon": [[2.0, 10.5], [6.5, 10.5], [6.5, 15.0], [2.0, 15.0]],   // outline, not closed
                "synthetic": false } ],
  "openings": [ { "id": "proc-factory-dev-003-F0-O0035", "floor_id": "proc-factory-dev-003-F0",
                  "space_ids": ["...-S030", "...-S016"],   // the two spaces it joins; "outside" for entrances
                  "kind": "door",                          // door | opening (no door leaf) | entrance
                  "position": [12.4, -5.0], "width_m": 0.9, "step_free": true, "synthetic": false } ],
  "vertical_connectors": [ { "id": "...-V02", "kind": "lift",     // stairs | lift
                             "name": "Office lift",
                             "floor_ids": ["...-F0", "...-F1"],     // one stop per floor...
                             "space_ids": ["...-F0-S004", "...-F1-S004"],   // ...and the space it stops in
                             "step_free": true, "synthetic": false } ],
  "assets": [ { "id": "...-A00117", "name": "Coordinate measuring machine 0.21",
                "category": "machine",          // furniture | fixture | machine | equipment
                "type": "coordinate_measuring_machine",
                "space_id": "...-F0-S021", "floor_id": "...-F0",
                "position": [2.941, 12.964],
                "footprint": { "width_m": 2.0, "depth_m": 1.5, "rotation_deg": 90.0 },
                "source": "generated" } ]       // dataset = from the source data, generated = placed by rules
}
```

Notes:
- **Space names and refs:** `name` usually includes the room number (`ref`). Refs are unique per building for generated and Swiss/ResPlan buildings. OSM refs come from the map, and a few rooms share names such as "WC".
- **Room types** include: `bedroom`, `living_room`, `kitchen`, `bathroom`, `toilet`, `storage`, `corridor`, `balcony`, `stairwell`, `lift`, `office`, `meeting_room`, `seminar_room`, `lecture_hall`, `lab`, `makerspace`, `library`, `server_room`, `technical_room`, `lobby`, `canteen`, `shop`, `print_room`, `locker_room`, `production_zone`, `additive_zone`, `assembly_zone`, `warehouse_zone`, `logistics_zone`, `quality_lab` and `generic_room` (an OSM room with no type tag).
- **Door widths:** `width_m` matters for moving wide loads such as trolleys, pallets or beds. Swiss Dwellings and ResPlan widths come from the drawings. Procedural doors are 0.9 m for offices, 1.1 m for lifts, 1.2 m for labs, seminar rooms, meeting rooms, libraries, toilets and stairwells, and 1.6 m double doors for halls, storage, server and technical rooms. OSM doors default to 0.9 m.
- **Step-free:** `step_free: false` means steps, such as a stair connector or an entrance with steps.
- **Stairs and lifts:** a connector joins its stop spaces floor to floor in the order of their levels.
- **Asset names** are unique within a building, e.g. `Desk 2.03-B` is the second desk in room 2.03.

### `equipment.csv`

`asset_id, name, type, category, source, building_id, floor_level, floor_name, space_id, space_name, room_ref, room_type, x_m, y_m, width_m, depth_m, rotation_deg`. This is the same information as `assets` in `building.json`, flattened.

### `manifest.csv`

`building_id, split, source, group_id, name, license, floors, levels, spaces, rooms, openings, connectors, assets, has_stairs, has_lift, has_step_free_entrance, questions, path`. `path` is relative to `data/`. `group_id` prevents leakage between splits: buildings from one site are all in the same split.

### The route model behind the expected answers

**Scope:** this is the original supplied kit model, implemented by the current router and used by the local warm-up checks. The newer [Synera route-scoring clarification](#route-scoring-clarification-synera) describes different geometry, vertical costs and route-validation rules for the automatic route check; the model below does not implement that clarification.

Route lengths in the answers come from this graph, so your router reproduces them if you build the same one:

- **Nodes:** one per space, anchored at shapely's `Polygon(space.polygon).representative_point()`, plus one node per opening at its `position`.
- **Edges:** each space connects to each of its openings, weighted by the straight-line distance from the anchor to the opening.
- **Stairs:** 12 m per floor between consecutive stops. **Lifts:** a 15 m wait plus 6 m per floor.
- **Step-free routing** drops every edge with `step_free: false`.
- **Parallel connections:** a stair and a lift can join the same two spaces. Keep both; a simple graph would drop one.
- **Outside:** all entrances meet at one `"outside"` node at zero cost, so a route may go out one entrance and back in another for free. The benchmark questions only use cases where this shortcut makes no difference.

`final_agent/building_map.py` implements exactly this model.

---

## 4. Questions

### Warm-up questions (`questions_basic.jsonl`, train and dev)

One search or one route each. Every line is `{"id", "building_id", "kind", "question", "answer"}`:

| Kind | Example | Answer fields |
|---|---|---|
| `locate` | "Where is the coordinate measuring machine?" | `asset_id`, `space_id`, `space_name`, `floor_level`, `position` |
| `count` | "How many chair items are on the floor 2?" | `count`, `asset_type`, `floor_level` |
| `route` | "How do I get from Office 0.30 (Ground floor) to Office 0.46 (Ground floor)?" | `from_space_id`, `to_space_id`, `optimal_length_m`, `space_path`, `element_path` |
| `route_step_free` | "Is there a step-free route from … to …?" | Same as route, or `reachable: false` |
| `route_with_closure` | "Lift 1 is closed for maintenance. How do I get from … to …?" | Route fields plus `closed_element_id`, or `reachable: false` |
| `tour` | "Starting at …, visit … then … in this order." | `stops`, `optimal_length_m`, `legs` |

### Benchmark questions (`questions.jsonl`; this is what is scored)

There are two groups.

- **Plan facts.** These need facts that a simple search-and-route agent never looks at, mainly **room areas** (from the polygons) and **door widths**. Most combine them with routing, step-free constraints or reachability.
- **Spatial reasoning.** These need the geometry itself: how floors stack in 3D, which walls rooms share, where room centres are, and what a change to the building would do across a whole floor. Exposing one more field isn't enough; your agent has to reason with polygons, coordinates and elevations.

| Kind | Example |
|---|---|
| `largest_room` | "Which is the largest kitchen on the floor 1, and how big is it in m²?" |
| `floor_area_total` | "Facilities want the total floor area of every office on the ground floor added together. How many square metres is that?" |
| `errand` | "I'm in Server room 0.42. I need to grab a stove from the room that has one closest to me, then carry it to the largest meeting room on the floor 1. I can carry it on the stairs. How far will I walk in total, in metres?" |
| `wide_delivery_count` | "I'm moving a 1.1 m wide trolley. It can't go on stairs or steps (lifts are fine), and every door it passes through must be at least 1.1 m wide. It arrives through the entrance into Lobby 0.01. Into how many rooms on the floor 2 can it be delivered?" |
| `step_free_reachable_count` | "Lift 1 is out of service. A wheelchair user comes in through the entrance into …. How many rooms on the floor 3 can they still reach?" |
| `room_stacked` | "There's water dripping from the ceiling in Office 0.29 (Ground floor). Which room is directly above it?" or "A washing machine is leaking onto the floor of Bathroom 2.04 (Floor 2). Which room directly below it will the water reach?" |
| `shared_walls_count` | "We're soundproofing Server room 1.14 (Floor 1). How many other rooms on that floor share a wall with it? Count every room whose wall runs along it for at least 1 m, with or without a door between them; corridors, stairwells and lifts don't count." |
| `straight_line_3d` | "We're planning a wireless sensor link between Lab 0.12 (Ground floor) and Office 3.07 (Floor 3). What is the straight-line distance in metres between the centres of the two rooms (each room's floor-plan centroid, at its floor's elevation)?" |
| `what_if_door` | "What if we add a door between Corridor 0.01 and Lecture hall 0.21 (Ground floor), in the middle of the wall they share? How many rooms on the floor 3 would then have a shorter walk out of the building, to their nearest entrance, by more than 1 m?" |

Precise definitions for the spatial questions:
- **Directly above / below:** the space on the next floor up or down whose outline covers most of this room's outline. These questions only use buildings whose floors share one XY frame (procedural and OSM).
- **Sharing a wall:** at least 1 m of one room's outline runs within 0.35 m of the other room's outline (walls have thickness).
- **Room centre:** the centroid of the room polygon, at the floor's `elevation_m`.
- **What-if door:** placed at the middle of the shared wall, and walked like any other door, between any two rooms, halls or corridors. The question is about a different floor than the door's. "Walk out of the building" is the route-model distance (section 3) to the nearest entrance.

Each question ends with an answer instruction such as *"Finish with a line 'Answer: <number>'"*.

**Train and dev lines** also contain `skill`, the `inputs` behind the question, and the `answer`. Study them, and use them to test your tools.

**Test lines** contain only `id`, `building_id`, `kind` and `question`.

The answers are well defined. The right room always beats the runner-up by a clear margin, every constraint actually changes the answer, and the largest room is never simply the room with the most furniture. Don't hard-code anything: the questions are generated, and new ones work the same way.

---

## 5. Quick start

You need Python 3.12+ and [uv](https://docs.astral.sh/uv/) (or pip), plus an Anthropic API key.

```bash
uv sync
cp .env.example .env        # then put your key in .env
uv run --env-file .env python -m final_agent data/dev/proc-factory-dev-003
```

Measure yourself on **dev** before you touch the test set:

```bash
# warm-up questions, tools only, free:
uv run python -m final_agent.evaluate data/dev --oracle
# benchmark questions with the project agent, the runner's default (uses credits):
uv run --env-file .env python -m benchmark.evaluate data/dev --per-kind 3
# your own agent:
uv run --env-file .env python -m benchmark.evaluate data/dev --agent my_agent:answer
```

`--agent module:function` takes a function `answer(building_directory: Path, question_text: str) -> str` that returns your agent's full reply.

The kit's starter agent scored **under 5% on the benchmark questions**. That was deliberate: its tools didn't expose room areas, door widths or reachability. `final_agent` grew from it, and the starter package was removed from this repository on 24 October 2026.

---

## 6. Submission format

Submit **one CSV file** with exactly these two columns:

| Column | Content |
|---|---|
| `question_id` | The `id` of a test question, e.g. `osm-way363805324-H01` |
| `answer` | Your agent's **full reply** to that question. It may run over several lines, as long as it is quoted the normal CSV way. |

```csv
question_id,answer
proc-campus-test-000-H01,"The largest seminar room on the ground floor is Seminar room 0.32.
Answer: Seminar room 0.32, 61.4 m²"
proc-campus-test-000-H02,"I added up the 12 offices on floor 1.
Answer: 214.7"
```

Writing the file is easiest with the evaluator. It runs your agent on every test question and saves the CSV:

```bash
uv run --env-file .env python -m benchmark.evaluate data/test --agent my_agent:answer --submission-csv team_<name>.csv
```

`data/test/submission_template.csv` lists every test id, if you would rather fill it in another way. The file must be UTF-8 with a header row and at most 5 MB.

### How it is scored

Only the **last line of the reply that starts with `Answer:`** counts. `**Answer:**` in Markdown is fine.

| Answer type | Correct when |
|---|---|
| A room (`largest_room`) | The answer line names the expected room by its number or full name, **before** any runner-up room, and includes the area in m² within **±5%** |
| A distance in metres (`errand`) | The answer line holds **exactly one number**, within **±1%** (at least ±1 m) of the optimal length |
| An area in m² (`floor_area_total`) | Exactly one number, within **±5%** |
| A count (`wide_delivery_count`, `step_free_reachable_count`, `shared_walls_count`, `what_if_door`) | Exactly one number, **exactly** right |
| A room (`room_stacked`) | The answer line names the expected room, before any runner-up room |
| A 3D distance (`straight_line_3d`) | Exactly one number, within **±2%** |

A reply with no `Answer:` line is wrong. So is an answer line with a range or several numbers ("between 92 and 108 m"). Missing questions count as wrong. Rows with unknown ids are ignored, and if an id appears twice the first row counts. Your score is the share of the 145 test questions answered correctly. Judges also see the result per question kind.

`benchmark/score.py` is the exact scorer the judges use. Run it on dev to check your formatting.

---

## 7. Rules and tips

- **Generated answers only:** answers must come from your agent running on the data, not from hand-labelling test questions.
- **The Sunday building** arrives in the same format. Anything you hard-code to the test buildings will fail there.
- **Start small:** get the route graph right first (section 3). Check it against the warm-up answers on dev; the route lengths should match to the centimetre.
- **Expose the data:** give your agent tools for what the plans actually contain (areas, door widths, adjacency, reachability, positions), not only search.
- **Watch your costs:** each question can take many tool calls. Keep tool results compact, and use prompt caching for the building context.

## 8. Licences

The data comes under several licences: CC BY 4.0 (Swiss Dwellings, ResPlan), ODbL 1.0 (the OpenStreetMap buildings) and CC0 (procedural). See `ATTRIBUTION.md`. If you publish anything built from the OSM buildings, it must stay under the ODbL and credit OpenStreetMap contributors.

---

## 9. Current implementation and verified baseline

This section is a code assessment as of 24 October 2026, not an organizer specification. Sections 1–8 retain the original kit documentation. Section 12 consolidates the package READMEs, including the storage documentation added during consolidation. Section 13 preserves the challenge PDF. Source claims, measured results, proposed tasks and unresolved requirements are distinguished below.

### Architecture and repository state

```text
Terminal conversation
  → final_agent.agent.BuildingAgent (Claude + conversation history)
  → seven typed tools in final_agent/tools.py
  → BuildingMap (JSON data + Shapely geometry + NetworkX MultiGraph)
  → route result / edited JSON / Matplotlib PNGs

benchmark.evaluate → agent(building_directory, question_text) → reply
                  → benchmark.score → result log + submission CSV
```

`final_agent/` now uses package-local imports throughout its entry point, conversation layer, tools, viewer, evaluator, map and storage. `BuildingMap` and `MapError` identities are consistent across these modules. `final_agent.storage` contains its own atomic JSON store and spatial index; no project runtime module imports the starter. The wheel includes `final_agent` and `benchmark`; the kit's `starter_agent` baseline was removed on 24 October 2026. Use `python -m final_agent` for the project CLI; `benchmark.evaluate` runs `final_agent.benchmark:answer` by default.

### What exists and what it does not yet cover

| Area | Implemented | Remaining limitation |
|---|---|---|
| Building input | Loads `building.json` from a directory or file; indexes floors, spaces, assets, openings and vertical connectors; preserves custom fields on save | No schema-validation pipeline, image/PDF ingestion or building creation workflow |
| Conversation | Claude tool loop, full in-session message history, cached initial overview, token accounting and CLI API-error messages | No web/mobile interface, durable user preferences or explicit location state; clarification and preference retention rely on the prompt |
| Overview | Floor summaries, entrances, stairs/lifts, asset count and current closures | No detailed spatial analysis or room/door inspection tool |
| Search | Case-insensitive matching of every query word against names, room refs/types and IDs; optional floor filter; assets resolve to their containing room | No synonyms/semantic search, exact typed enumeration or pagination; tool exposes only the first 15 results, though it reports the total match count |
| Spatial queries and storage | Final package integrates its own per-floor STRtree, atomic saves, directory creation and closure snapshots; storage and integration checks pass | No pagination or merged writes |
| Routes | Dijkstra on a MultiGraph, openings as nodes, room representative points, multiple floors, stairs/lifts, step-free filtering and ordered via stops | No minimum door width, reachable-room counts, nearest-equipment selection, optimal stop ordering or cross-building routing |
| Closures | Final tools close/reopen rooms, openings, stairs and lifts; snapshots serialize closures and reload restores them | No automatic route invalidation/recalculation or event history; save failures are not transactional with in-memory edits |
| Edits | Adds a synthetic 0.9 m door between nearby spaces on one floor and exports edited building JSON | No reliable shared-wall midpoint, custom width, preview/undo or transactional save; validation is incomplete |
| Directions | Room/floor transitions and distance estimates from the computed route | No geometric left/right turns, equipment landmarks or live positioning |
| Visualization | Static PNG per crossed floor, space polygons, route line and closed-room shading | No asset markers, interactive locate view, animation or stacked 3D floors; selected opening identities are not preserved for rendering |
| Evaluation | Project warm-up evaluator, isolated benchmark callable, official scorer/runner, CSV export and 11 passing storage/integration tests | No measured live benchmark baseline, complete geometry/interaction regression coverage or Sunday adapter |
| Assets | Reads/searches equipment supplied in building JSON | No movement/update API, barcode/RFID ingestion or asset history |

### Status against challenge levels

| Level | Current status | Completion work |
|---|---|---|
| 1 — Locate | Search and conversation exist | Show and highlight the selected room/equipment on a usable map; handle ambiguous/nonexistent references |
| 2 — Route | Core routing, in-memory closures, step-free routing and ordered tours exist | Reliable visualization, route invalidation, closure persistence and stronger interaction checks; width filtering is also needed for scored delivery questions |
| 3 — Scale | Multiple floors within one building work | Multiple buildings, building disambiguation and walkway connections |
| 4 — Build | One limited door-edit operation exists | Floor-plan ingestion, calibrated geometry, generated rooms/openings/connectors, validation, conversational correction and dependable export/reload |
| 5 — Extend | No complete optional extension is demonstrated | Select and finish one extension after the core workflow works |

### Evaluation evidence and limits

The free dev warm-up command was rerun during the backlog audit:

```bash
.venv/bin/python -m final_agent.evaluate data/dev --oracle
```

| Warm-up kind | Correct / total |
|---|---:|
| `count` | 40 / 40 |
| `locate` | 100 / 100 |
| `route` | 120 / 120 |
| `route_step_free` | 40 / 40 |
| `route_with_closure` | 29 / 29 |
| `tour` | 40 / 40 |
| **All** | **369 / 369** |

This is an oracle-assisted warm-up result, not a conversational-agent benchmark score. The oracle supplies destinations, constraints and closures from expected answers; for locate questions it directly assigns the expected asset ID. The warm-up scorer is also permissive: route checks primarily compare distance, and an unreachable case can pass when no route was computed. It does not establish correct natural-language interpretation, correct final answer formatting or a valid full submission.

After rewiring, `.venv/bin/python -m unittest discover -s tests -v` passes **11 tests**. Storage tests now target the canonical final map/store, rather than requiring new APIs on the original starter map. Integration tests block starter imports, check the CLI and class/error identities, exercise spatial queries, door/closure snapshots and actual PNG generation, and verify benchmark state/output isolation. The built wheel also loads the CLI, evaluator and benchmark adapter with `starter_agent` removed. No paid live API check was performed.

The original README's “under 5%” benchmark statement remains a source claim. No paid live-agent evaluation was run for this review. All nine scored benchmark kinds still need dedicated tool support.

## 10. Tasks, priorities and completion criteria

[BACKLOG.md](BACKLOG.md) is the canonical implementation checklist, audited against the actual code and rerun checks on 24 October 2026. It separates supplied starter capabilities, partially integrated additions, required base levels 1–4, all nine scored question kinds, submission work and optional level 5. Every open task has a stable ID, priority, dependencies where relevant and a completion criterion.

**CORE-01–02 and CORE-04 are implemented:** the final package is independently wired, its storage/spatial tools are active and its benchmark callable isolates each question. Packaging now includes the final package; remaining configuration work is tracked in CORE-03. Next complete the visual locate/route slice, deterministic benchmark tools, multi-building navigation, plan ingestion and submission artifacts.

- [Starter-template inventory and measured baseline](BACKLOG.md#1-what-the-starter-already-supplies)
- [Required base levels and exit criteria](BACKLOG.md#3-required-base-levels-and-exit-criteria)
- [P0 integration repairs](BACKLOG.md#4-p0--repair-integration-and-establish-one-working-implementation)
- [Routing, geometry and editing fixes](BACKLOG.md#5-p0--routing-geometry-and-edit-correctness)
- [All nine scored benchmark kinds and coverage counts](BACKLOG.md#6-p0--all-nine-scored-benchmark-kinds)
- [Levels 1–2 and interaction](BACKLOG.md#7-p1--finish-levels-1-and-2-and-the-interaction-rubric)
- [Level 3: multiple floors and buildings](BACKLOG.md#8-p1--complete-level-3-across-floors-and-buildings)
- [Level 4: new buildings from plans](BACKLOG.md#9-p1--complete-level-4-building-creation-and-update)
- [Verification and submission](BACKLOG.md#10-p0p1--verification-benchmark-delivery-and-submission)
- [Optional level 5](BACKLOG.md#11-p2--optional-level-5) and [delivery milestones](BACKLOG.md#12-suggested-delivery-milestones)

P0/P1/P2 are project delivery priorities, not organizer weights. P1 includes required product work; it is not optional. Warm-up oracle success, standalone component code and an existing CSV writer do not by themselves establish a completed level or a scored submission.

## 11. Open decisions and source discrepancies

| Open point | Source evidence | Working interpretation / next action |
|---|---|---|
| Public test output vs. Sunday output | Repository section 6 defines `question_id,answer` CSV. PDF page 3 specifies `questions.json` → `answers.json` with IDs, route node lists and lengths. | Use the implemented CSV contract for the public 145-question submission. Treat the Sunday JSON contract as provisional until the organizers release its schema; do not assume either format replaces the other. Preserve both specifications below. |
| Sunday timing and schema | PDF literally contains “TODO: exact time” and a schema/example “(TODO)”. Repository section 1 says the exact release time and file format will be announced with the release. | Organizer-dependent open points. Record the announcement and implement/verify the actual adapter when available; no exact time or schema is established here. |
| PDF data description has placeholders | “several buildings”, a “[FORMAT, e.g. JSON; the schema is in the kit.]” placeholder, and a general test-set description | Use the concrete repository data schema and split counts for current development. The public test has no answer labels; train/dev do. Keep the PDF wording as source material, not a claim that hidden answers are present. |
| Project package | Entry point and internal imports now use the final package; storage is local and the wheel includes it | Use the final CLI; the benchmark runner calls it by default. The kit's starter baseline was removed on 24 October 2026. |
| Persistent changes vs. what-if analysis | Final closures/doors save snapshots and reload correctly; benchmark questions have isolated maps and temporary outputs | Add transactional edits, preview/undo and dedicated what-if analysis; isolate concurrent interactive outputs. |
| New-building ingestion quality | Only JSON loading and one door edit exist; no image ingestion implementation | Decide extraction method and uncertainty handling; demonstrate geometry and connectivity validation on a genuinely new plan. |
| Supplied kit vs. Synera automatic route check | The kit uses anchor-to-door segments, fixed per-floor costs and a zero-cost outside node. The [Synera clarification](#route-scoring-clarification-synera) specifies wall-respecting door-to-door paths with about 15 cm clearance, height-based costs, forklift restrictions, destination-only production bays and ordered-space validation. | Implement the clarified automatic-check rules and distinguish them from local kit scoring. Confirm schema, route endpoint details and outside handling with organizers; the clarification supplies no file format or outside-node rule. |
| Optional extension scope | Source recommends picking one add-in | Choose based on the completed core workflow and available time; no optional extension is selected or finished by this document. |
| Setup/reference drift | `.env.example` is referenced but absent; attribution references `config/furniture_catalog.yaml`, also absent from the supplied tree | Supply missing setup instructions/resources where needed. Preserve original reference wording and identify missing resources rather than inventing their contents. |

## 12. Consolidated agent reference

The following reference retains the kit's description of its starter agent and its model/caching claims. `final_agent` grew from that starter, which was removed from this repository on 24 October 2026 after `final_agent` was verified to contain all of it; the commands below therefore run `final_agent`. The project package is documented in [final_agent/README.md](final_agent/README.md); section 9 records current verification.

**API scope:** the storage/spatial examples below use `final_agent`, whose CLI, tools and evaluator use the same implementation. Run the documented test command to check it; see [final-agent commands](final_agent/README.md).

### Starter agent: an indoor "Google Maps" you can talk to

This is a small working example to build on. Claude handles the conversation, and a deterministic module (`building_map.py`) supplies every fact: rooms, things, routes and distances. Claude never makes up a route. It calls tools and explains what they return.

```
you ──► agent.py (Claude Opus 5.5, tool runner) ──► tools.py ──► building_map.py ──► building.json
                                                                   │  search, Dijkstra routes,
                                                                   │  closures, add a door
                                                       viewer.py ◄─┘  route images (PNG)
```

#### Run it

You need Python 3.12, [uv](https://docs.astral.sh/uv/) and Claude API credentials: set `ANTHROPIC_API_KEY`, or run `ant auth login`.

```bash
uv sync
uv run python -m final_agent data/dev/proc-factory-dev-003
```

```
you> where is the cnc mill?
you> I'm at the main entrance, how do I get there without stairs?
you> the office lift is closed for maintenance - what changes?
you> add a door between 1.04 and 1.05
you> show me the route
```

Route images and edited buildings go to `agent_output/`.

#### Tools

| Tool | What it does | Level |
|---|---|---|
| `building_overview` | Floors, stairs and lifts, entrances, current closures | 1 |
| `search_building` | Finds rooms and things by name, room number or type, optionally on one floor | 1 |
| `spatial_search` | Finds rooms, assets and doors within a radius on one floor, using a spatial index | 1 |
| `find_route` | Shortest route with step-by-step directions and metres. Supports `step_free` and `via` stops for tours | 2–3 |
| `set_closed` | Closes or reopens a lift, staircase, door or room and saves `building_edited.json` | 2 |
| `add_door` | Adds a door between neighbouring rooms and saves `building_edited.json` | 4 (start) |
| `show_route` | Draws the last route on each floor it crosses | viewer |

Route costs match the dataset's expected answers: walking distance through door positions, 12 m per floor of stairs, and a 15 m wait plus 6 m per floor for a lift.

#### Building storage and spatial indexes

Buildings stay in the existing JSON format: metadata, floors, room polygons,
openings, vertical connectors and assets. `JsonBuildingStore` creates missing
parent directories and writes a temporary file before atomically replacing the
destination. Saves preserve custom fields and include closures under
`navigation_state.closed`; loading an older dataset file defaults to no closures.
Door and closure tools save a snapshot to `agent_output/building_edited.json`.
Load that snapshot explicitly to resume an edited building.

Spatial searches use Shapely STRtree indexes, built lazily in memory for each
floor and element kind. Coordinates and distances are local **metres**. Rooms
use their polygons, while assets and openings use their point positions. Results
are sorted by distance; `radius_m=0` includes rooms covering or touching the
point. Floors are always queried separately. Adding a door invalidates the
indexes so the next search includes it. Asset footprints are retained in JSON
but are not used for proximity searches.

```python
from pathlib import Path
from final_agent.building_map import BuildingMap

building = BuildingMap.load(Path("data/dev/proc-factory-dev-003"))
nearby = building.spatial_search(
    x_m=12.4, y_m=-5.0, floor_level=0, radius_m=5, kind="asset"
)
building.save(Path("agent_output/building_edited.json"))
restored = BuildingMap.load(Path("agent_output/building_edited.json"))
```

`kind` can be `all`, `space`, `asset` or `opening`. The agent's `spatial_search`
tool returns the total match count and the first 15 results. Indexes are rebuilt
from JSON after loading; no database service or additional dependency is needed.
Concurrent saves use the last completed replacement; this file backend does not
merge simultaneous edits.

Run the storage and geometry checks with:

```bash
uv run python -m unittest discover -s tests -v
```

#### Check how well it does

These commands use the warm-up set (`questions_basic.jsonl`). The real benchmark is `questions.jsonl`, scored with `benchmark.evaluate`; the kit's starter agent failed it on purpose. See section 6 of [../README.md](#6-submission-format).

```bash
### Free: answers every question with the tools directly. Shows the tools can reach 100%.
uv run python -m final_agent.evaluate data/dev --oracle

### Live agent on the first 10 dev questions (uses API credits)
uv run python -m final_agent.evaluate data/dev --limit 10
```

The live score checks what the agent computed, not its wording. A route must be within 1% of the optimal length, a locate question must find the right asset, and a count answer must contain the right number. Each question runs in a fresh conversation, so you can see per-question token use.

#### Where to take it next

- **Interaction (25 pts).** Tune `SYSTEM_PROMPT` in `agent.py`. Test with tricky users: vague ("the printer"), wrong ("room 9.99"), or changing their mind halfway.
- **Level 3 (scale).** Several buildings at once. Load more than one `BuildingMap`, link them with outdoor walkways, and add a `building` argument to the tools.
- **Level 4 (build).** Create a building from a floor-plan image. Send the PNG to Claude as an image, have it produce `spaces` and `openings` in the same JSON format, then load it with `BuildingMap` and check that every room can be reached.
- **Level 5 (extend).** Moving assets (an `update_asset_position` tool), forklift routes that avoid blocked aisles (close hall zones), voice, or a three.js view that stacks floors by `elevation_m`.
- **Cost.** The system prompt (with the building overview) is cached, so you only pay full price for it once. Lower `EFFORT` to `"low"` for quick lookups, or try `claude-sonnet-5-5` or `claude-haiku-5-5` and compare with the evaluator.

#### Notes

- The model is `claude-opus-5-5` at `effort: "medium"`. Server-side fallbacks are switched on (`fallbacks: "default"`), so if a request is declined it is retried on a fallback model instead of failing. Remove the `betas` and `fallbacks` arguments in `agent.py` if you don't want this.
- `tool_runner` comes from the Anthropic Python SDK (beta helper). It runs the call-tools-and-feed-back-results loop. `agent.py` copies its history so that follow-up questions keep their context.

The following unique note came from the final-agent README; its shared text and older tool table are covered by the reference above. Its link now points within this document.

### Final-agent storage note

JSON persistence and per-floor spatial searches are owned by `final_agent.storage`, with no starter imports.
See [building storage and spatial indexes](#building-storage-and-spatial-indexes)
for the Python API, save/reload behavior and tests.

## 13. Challenge PDF reference

Source: `Hackathon Challenge - Talk to Your Building.pdf` (three pages), supplied from `/Users/felix/Downloads/Hackathon Challenge - Talk to Your Building.pdf`.

The following is a verbatim transcription of the PDF's challenge text, checked against rendered pages. Page layout, line wrapping, bullet styling and heading/table formatting have been converted to Markdown; wording, punctuation, grading criteria and even source placeholders and repeated text are retained. The Synera logo/tagline is “The AI Agent Platform for Engineering”. This is source material; unresolved requirements are identified in section 11.

### Page 1

CHALLENGE BRIEF · INDUSTRIAL AGENTS HACKATHON 2026

#### Talk to Your Building: Agent-First Indoor Navigation

#### The story

You have walked into an office complex or a factory hall and had no idea where to go. Outdoors we solved this long ago: type where you want to be, and a map shows the way. Indoors, floor plans are PDFs, machines live in spreadsheets, and the one person who knows where the 3D printer is has gone home.

Your mission: give any building its own map you can talk to. Feed your system a floor plan and it learns the building. Then anyone can just talk to it.

#### Questions your agent should answer

1. FIND “Where is the 3D printer?”
2. ROUTE “How do I get from the lobby to the CNC mill on floor 2 without stairs?”
3. EDIT “Add a door between rooms 2.03 and 2.04.”
4. REACT “The east lift is closed for maintenance. What changes?”

#### About Synera

Synera is agentic AI for engineering, open and connected across every tool in the product development stack. Our AI agents work as digital engineering coworkers that change geometry, run simulations and iterate, at companies such as NASA, Airbus and BMW. This challenge is a compact version of what we work on every day: agents that understand space and geometry and explain themselves to people in plain language.

#### What you build

An app you talk to. It shows 2D or 3D views of buildings and floors, animated routes, and the things inside: rooms, desks, machines, equipment. It works for an existing building and can set up a new one quickly from floor plans.

The agent is the interaction layer: you say what you want and the system does it. The core underneath is mostly deterministic: a graph of rooms, doors, corridors, stairs and lifts, and a search that finds the best route.

#### What you get

All data is in GitHub repository: [Synera-GmbH/industrial-agents-hackathon-2026](https://github.com/Synera-GmbH/industrial-agents-hackathon-2026). No company data and no NDA; everything is public or generated.

- Floor plans of several buildings, e.g. a factory hall with offices and a four-storey campus building, as structured plan files plus PNG images. [FORMAT, e.g. JSON; the schema is in the kit.]

### Page 2

- Equipment lists per building, so there is something to find.
- A test set of example questions with expected answers, to check your agent while you work.
- Credits for Claude, Lovable and ElevenLabs via the organizers. UX and voice can play a real role: a voice in, voice out agent counts towards Interaction.

Lovable and ElevenLabs credits mean UX and voice can play a real role: a voice in, voice out agent counts towards Interaction.

#### Levels

Every level earns points and builds on the one before, so a team that stops early still has something that works.

1. Locate: on one floor, talk to the agent, find things and see them on a view.
2. Route: find the way from A to B on one floor, with options such as step-free routes, closed areas and multi-stop tours.
3. Scale: multiple floors, then multiple buildings, with stairs, lifts and walkways between them.
4. Build: create or update a building from floor plans, by conversation. A new building should take minutes, not days.
5. Extend: pick an add-in below, or surprise us.

#### Optional add-ins

For teams that finish early, and worth creativity points. Make things move: tools or machines that change place via barcode, RFID or “this is now here”, so the map stays current. Let several colleagues update the building while others ask questions. Route forklifts and materials through a hall with blocked aisles and delivery points. Capture a new building by walking through it with a phone instead of starting from a floor plan. Plan for accessibility with wider doors, step-free and quiet routes. Present it well with isometric stacked floors, animated routes and voice in and out. Or go for AR: the route as an overlay on your phone, where the hard part is knowing where you are (QR codes at doors, WiFi, other tricks). Pick one and do it well rather than three badly.

#### Directions, not instructions

How you get there is up to you. A few directions that save hours:

- Think in a graph. Rooms and junctions are nodes; doors, corridors, stairs and lifts are edges; Dijkstra or A* finds the route. Agree on the data model in your first hour.
- One floor first. Make one question work end to end before 3D or a pretty interface. A flat 2D plan with the route drawn on it is a fine start; three.js gets you extruded floors later.
- Spend your time on decisions. AI writes most of the code, so think about the user: what should the agent ask when a request is vague? How does it show what it understood before it changes a plan? “Turn left at the printers” or room numbers?

### Page 3

#### Sunday benchmark: how we run your agent

Shortly before code freeze (TODO: exact time) we release one new building nobody has seen, plus a question file. Your agent has to answer them, including the best routes.

1. Input: the new building in the same plan format as the training data, and questions.json with one entry per question (id, text, optional constraints such as step-free).
2. Your run: a single command in your repo, documented in BENCHMARK.md, e.g. `run_benchmark <building_dir> <questions.json> <answers.json>`. No manual steps between input and output.
3. Output: answers.json, one entry per question id with the located item or room id, the route as an ordered list of node ids, and the route length in metres.
4. Submission: you run it yourselves and submit answers.json with your project. We may re-run your command on the same input to verify.

We score correct answers, valid routes and route length against the best route. A schema and an example answer file are in the data folder (TODO).

#### Submission and judging

There are no pitch rooms. All teams submit online by code freeze through the organizers’ platform:

- a demo video of your app in action
- a short technical explanation (architecture and tech stack)
- your repository, including BENCHMARK.md and your answers.json

We review all Track 01 submissions and pick four finalists. Finalists present at the joint final pitch session at Tacto: 3 minutes plus 1 minute Q&A per team.

Three things count, in this order: does it work, is it a pleasure to use, and what did you add that we did not ask for.

| Part | Points | What we look at |
|---|---|---|
| Does it work | 55 | Sunday benchmark plus automatic checks on buildings and questions you have not seen, covering levels 1 to 4: correct answers, valid routes, route length against the best route, correct buildings built from plans |
| Interaction | 25 | A short scripted conversation with tricky users, rated on a rubric. Does it ask only what it needs, show what it understood, and give directions a person can follow? Voice counts here. |
| Creativity | 10 | Level 5 and add-ins: anything that makes the product better in a way we did not think of |
| Submission demo | 10 | Your demo video and technical explanation: clear, convincing, and showing the real product |

## 14. Data sources and licences

The following attribution reference is retained verbatim from `ATTRIBUTION.md` (heading formatting adjusted). Its source catalogue path is a reference to the dataset generation resources, which are not included in this checkout.

Every building's `building.json` names its own source, licence and attribution, and so does `manifest.csv`. The licences differ by source:

| Source (`source`) | Licence | Attribution | What we changed |
|---|---|---|---|
| `swiss_dwellings` | CC BY 4.0 | Swiss Dwellings, Standfest et al. / Archilyse, https://zenodo.org/records/7070952 | Converted to our format. Added the shared stair halls (recovered from gaps in the plan), stair and lift cores, building entrances and generated furniture. Every addition is marked `synthetic: true` or `source: generated`. |
| `resplan` | CC BY 4.0 | ResPlan, Agour et al., https://github.com/m-agour/ResPlan | Rescaled to metres, added hallways and door connectivity, and generated furniture. |
| `osm_indoor` | ODbL 1.0 | © OpenStreetMap contributors, https://www.openstreetmap.org/copyright | Projected to local metres and split per level. Added fallback doors where none were mapped, small lift spaces for lifts mapped as nodes, and generated furniture. **This part of the dataset is a derived database under the ODbL. If you share it, it stays under the ODbL.** |
| `procedural` | CC0 1.0 | Generated for the Munich hackathon | Everything is generated. |

Furniture with `source: generated` comes from rules in `config/furniture_catalog.yaml`. Fixtures with `source: dataset` come from the original data.
