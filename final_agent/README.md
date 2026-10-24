# Project agent

`final_agent` is the independently runnable implementation: conversation (`agent.py`), tool
interfaces (`tools.py`), deterministic geometry and routing (`building_map.py`), persistence
(`storage.py`), rendering (`viewer.py`) and the benchmark adapter (`benchmark.py`). Imports are
package-local; nothing depends on `starter_agent`. The language model interprets requests and
explains results; every fact, count, area, distance and path comes from a tool.

## Run it

```bash
uv sync
cp .env.example .env                                   # set ANTHROPIC_API_KEY (live runs only)

# Conversation in the terminal (needs credentials)
uv run --env-file .env python -m final_agent data/dev/proc-factory-dev-003

# Free checks, no API calls
uv run python -m unittest discover -s tests -v
uv run python -m final_agent.evaluate data/dev --oracle
uv run python bench_analsysis/run_tests.py --mode components --split data/dev

# Benchmark and submission file: see ../BENCHMARK.md
uv run python -m final_agent.benchmark --check agent_output/submission.csv
```

Edits and route images go to `agent_output/` (or `--output`). Closures and added doors are saved to
`building_edited.json` there; pass that file as the building argument to resume. Use separate output
directories for concurrent sessions.

## Tools

Arguments in bold are required. All tools return JSON; expected failures come back as actionable
tool errors, not guesses. "Pending merge" rows belong to features that are not in this branch yet:
the coordinator verifies names and arguments after merging.

| Tool | Use it for | Key arguments | Example |
|---|---|---|---|
| `building_overview` | Floors, stairs/lifts, entrances, closures | none | `{}` |
| `search_building` | Fuzzy find, or exact inventory with filters; `matches` is the exact total, page with `next_page` | `query`, `floor_level`, `kind`, `room_type`, `asset_type`, `space_type`, `page` | `{"query": "", "asset_type": "chair", "floor_level": 2}` |
| `list_spaces` | Complete list of spaces (never assets) | `floor_level`, `room_type`, `space_type`, `page` | `{"floor_level": 0, "room_type": "office"}` |
| `spatial_search` | Rooms, assets, doors near a point | **`x_m`**, **`y_m`**, **`floor_level`**, `radius_m`, `kind` | `{"x_m": 2.5, "y_m": 20, "floor_level": 0, "radius_m": 3}` |
| `inspect_space` | One room in full: area, doors and widths, connectors, contents | **`space`** | `{"space": "Office 0.23"}` |
| `find_route` | Shortest constrained route with directions; becomes the route `show_route` draws | **`start`**, **`destination`**, `step_free`, `via`, `min_width_m`, `entrance` | `{"start": "Office 0.23", "destination": "Office 0.25", "step_free": true}` |
| `find_best_tour` | Shortest tour through stops in any order (at most 10); preview with `activate=false` | **`start`**, **`stops`**, **`destination`**, `step_free`, `min_width_m`, `activate` | `{"start": "A", "stops": ["B", "C"], "destination": "A", "activate": false}` |
| `plan_errand` | "Grab X from the nearest room, deliver to the largest Y on floor N" | **`start`**, **`asset_type`**, **`destination_room_type`**, **`destination_floor_level`**, `step_free`, `min_width_m`, `activate` | `{"start": "Office 0.23", "asset_type": "stove", "destination_room_type": "meeting_room", "destination_floor_level": 0}` |
| `reachable_rooms` | How many rooms can be reached or delivered to under constraints | **`start`**, `floor_level`, `step_free`, `min_width_m`, `entrance`, `closed_elements`, `room_type` | `{"start": "Lobby 0.01", "floor_level": 2, "min_width_m": 1.1, "step_free": true, "entrance": "Lobby 0.01"}` |
| `find_largest_room` | Largest room of a type on a floor, with its area | **`room_type`**, **`floor_level`** | `{"room_type": "kitchen", "floor_level": 1}` |
| `sum_floor_area` | Total area of one room type on a floor | **`room_type`**, **`floor_level`** | `{"room_type": "office", "floor_level": 0}` |
| `straight_line_distance_3d` | Centre-to-centre distance through the air, across floors | **`first`**, **`second`** | `{"first": "Lab 0.12", "second": "Office 3.07"}` |
| `find_stacked_room` | Room directly above or below | **`space`**, **`direction`** (`above`/`below`) | `{"space": "Office 0.29", "direction": "above"}` |
| `count_shared_walls` | Rooms sharing a wall of at least 1 m (soundproofing) | **`space`** | `{"space": "Server room 1.14"}` |
| `find_navigation_landmarks` | Step cues near a route point, with an ambiguity check | **`x_m`**, **`y_m`**, **`floor_level`**, **`inner_radius`**, **`outer_radius`**, `min_size`, `kind`, `within_spaces` | `{"x_m": 2.5, "y_m": 20, "floor_level": 0, "inner_radius": 5, "outer_radius": 10, "within_spaces": ["Office 0.23"]}` |
| `set_closed` | Close or reopen a lift, stair, door or room (saved); recomputes the active route | **`element`**, **`closed`** | `{"element": "Lift 1", "closed": true}` |
| `add_door` | Add a door in the middle of the wall two rooms share (saved) | **`first_space`**, **`second_space`**, `step_free`, `width_m` | `{"first_space": "Office 0.23", "second_space": "Meeting room 0.24"}` |
| `show_route` | Draw the active route on the floor plans, return image paths | none (F14 adds `landmark_ids`, pending merge) | `{}` |
| `analyze_what_if_door` *(pending merge, F12)* | Hypothetical door; nothing saved. `count` = rooms on the target floor whose walk to the nearest entrance gets shorter by more than the threshold | **`first_space`**, **`second_space`**, **`floor_level`**, `improvement_threshold_m` (default 1.0) | `{"first_space": "Corridor 0.01", "second_space": "Lecture hall 0.21", "floor_level": 3}` |
| `show_location` *(pending merge, F14)* | Select a room or asset on the map and return an image | **`element`** | `{"element": "Coordinate measuring machine"}` |
| `describe_destination_context` *(pending merge, F14)* | Nearby sizable named rooms around a destination; relation `adjacent` only with a shared wall of at least 1 m, otherwise `near` | **`space`**, `radius_m` (15), `min_area_m2` (40) | `{"space": "Office 0.23"}` |

Distances use the local kit model (`distance_model` in results); do not mix it with other models.

## Scored answer lines

The model finishes a benchmark reply with `Answer: ...` (the scorer reads the last such line):

| Kind | Tool | Answer line |
|---|---|---|
| `floor_area_total`, `straight_line_3d`, `errand` | `sum_floor_area`, `straight_line_distance_3d`, `plan_errand` | one number |
| `wide_delivery_count`, `step_free_reachable_count`, `shared_walls_count`, `what_if_door` | `reachable_rooms`, `count_shared_walls`, `analyze_what_if_door` | one integer |
| `largest_room` | `find_largest_room` | `<room>, <area> m²`, room first |
| `room_stacked` | `find_stacked_room` | `<room>` |

A room is its name plus its ref in parentheses when the name lacks it (`Büro (1.02)`).
`tests/test_agent_integration.py` checks tool schemas, prompt/tool agreement, one real call per tool,
these formats against `benchmark/score.py` and the submission validator.

## Manual interaction script (no live result recorded)

Run the CLI on `data/dev/proc-factory-dev-003` and check each turn against the tool results:
1. "Where is the stove?" (locate: several stoves exist, so expect a short list or a clarifying question, no route).
2. "I'm in Office 0.23, how do I get to Meeting room 1.10?" then "I use a wheelchair" (route, then a step-free re-route).
3. "Now take me to the kitchen on floor 1" (destination changes; the wheelchair preference stays).
4. "The Office lift is out of service" (closure, reroute or an explained unreachable result), then "It is back" (reopen).
5. "Visit Office 0.25 and Office 0.26 on the way back" (tour; the shorter-order offer, activated only on request).
6. "Take me to room 9.99" (invalid room: say so, offer real options, do not invent one).

These flows were not run against the live model here (no credentials).

- [Challenge and implementation reference](../README.md)
- [Benchmark and submission](../BENCHMARK.md)
- [Remaining implementation work](../BACKLOG.md)
