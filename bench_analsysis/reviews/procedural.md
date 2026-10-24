# Procedural campus and factory question audit

This review covers **8 selected dev buildings, 40 scored questions and 80 warm-up questions**. Every line of both question files was reviewed. `procedural_annotations.json` contains one annotation per question. The six scored kinds present here use existing kind names; no new kind enum was found. Three documented scored kinds are absent from this subset: `room_stacked`, `step_free_reachable_count`, and `what_if_door`. Their absence says nothing about whether the application supports them or whether they appear elsewhere.

Labels and structured `inputs` were used only for analysis and offline verification. No live API request was made, no production code was changed, and no score from `benchmark.score` or conversational accuracy is claimed.

## Coverage and exact counts

| Building | Floors / elevations in m | Spaces | Scored | Warm-up |
|---|---|---:|---:|---:|
| `proc-campus-dev-000` | 0–4 / 0, 3.8, 7.6, 11.4, 15.2 | 152 | 5 | 10 |
| `proc-campus-dev-001` | 0–3 / 0, 3.8, 7.6, 11.4 | 97 | 5 | 10 |
| `proc-campus-dev-009` | 0–5 / 0, 3.8, 7.6, 11.4, 15.2, 19 | 207 | 5 | 10 |
| `proc-campus-dev-013` | 0–2 / 0, 3.8, 7.6 | 63 | 3 | 10 |
| `proc-factory-dev-003` | 0–1 / 0, 3.5 | 79 | 5 | 10 |
| `proc-factory-dev-005` | 0–2 / 0, 3.5, 7 | 132 | 6 | 10 |
| `proc-factory-dev-007` | 0–1 / 0, 3.5 | 45 | 5 | 10 |
| `proc-factory-dev-011` | 0–2 / 0, 3.5, 7 | 140 | 6 | 10 |
| **Total** | | **915** | **40** | **80** |

| Kind | Source | Count | Observed subtypes, exact counts | Current deterministic coverage / missing tool |
|---|---|---:|---|---|
| `largest_room` | scored | 7 | Upper-floor typed maximum 5; ground-floor typed maximum 2 | **Not implemented.** Search exposes names/types without polygon area; needs exact typed enumeration and maximum area (BEN-01 / MAP-07). |
| `floor_area_total` | scored | 8 | Ground-floor typed sum 5; upper-floor typed sum 3 | **Not implemented.** Needs full exact room-type/floor aggregation, including matching hall bays (BEN-02 / MAP-07). |
| `wide_delivery_count` | scored | 8 | Same-floor step-free + width 6; cross-floor step-free + width 2 | **Not implemented.** Existing graph has step-free and closures but ignores widths, exposes no reachability/count tool (BEN-06 / MAP-08). |
| `errand` | scored | 7 | Nearest pickup then largest destination on same start/target floor 2; cross-floor 5 | **Not implemented.** Existing route with ordered `via` is reusable only after correct pickup and destination selection; needs exact assets, nearest reachable pickup and largest typed room (BEN-08). |
| `straight_line_3d` | scored | 6 | Centroid/elevation distance across distinct floors 6 | **Not implemented.** Needs polygon centroid XYZ and Euclidean distance; route anchors and floor-number costs are unsuitable (BEN-03). |
| `shared_walls_count` | scored | 4 | Hall target with hall neighbours 3; ordinary room target with hall neighbours 1 | **Not implemented.** Needs boundary proximity/length calculation and explicit eligible-neighbour rule (BEN-05). |
| `locate` | warm-up | 24 | Unique named asset 24 | **Implemented for these questions** by search; one matching asset per subject in all 24. Exact numeric asset position is not exposed by ordinary search; containing room/floor is. |
| `count` | warm-up | 8 | Asset type on one stated floor 8 | **Partial.** Search's total match count happens to yield correct counts for all eight queried subjects, but it mixes matching spaces/assets and substring matches. Needs exact typed count for robust general use (MAP-07). |
| `route` | warm-up | 24 | Same-floor reachable 9; cross-floor reachable 15 | **Implemented under local kit model.** Missing selected element IDs / leg structure in exported result and Synera route-model rules. |
| `route_step_free` | warm-up | 8 | Same-floor reachable 5; cross-floor reachable 3 | **Implemented under local kit model.** No unreachable example in this subset and no implication about door width. |
| `route_with_closure` | warm-up | 8 | Named staircase closed, alternate route remains reachable 8 | **Implemented computation under local model.** Closure mutation and routing exist; stale route invalidation and transactional mutation remain gaps. |
| `tour` | warm-up | 8 | Ordered three-stop, two-leg tour crossing floors 8 | **Implemented route computation with `via`.** Result concatenates the path and sums lengths; no structured per-leg result or stop-order optimizer is registered. |
| `room_stacked` | scored | 0 | Absent | **Not implemented:** next available floor and greatest polygon overlap, BEN-04. |
| `step_free_reachable_count` | scored | 0 | Absent | **Not implemented:** isolated closure + step-free graph + eligible-room count, BEN-07. |
| `what_if_door` | scored | 0 | Absent | **Not implemented:** cloned simulation, correct shared-wall midpoint, nearest-exit comparison and strict >1 m improvement, BEN-09. |

## Under-documented expected-result distinctions

### Eligibility is specific to the question kind

The words “room” and “zone” cannot share one universal `type == 'room'` filter:

* **Wide-delivery counts use `space.type == 'room'` in all eight audited labels.** They exclude halls/lobbies/industrial bays as well as corridors, stairwells and lifts. `proc-factory-dev-007-H03` expects **8**, although its reachable target-floor component also contains **8 halls**, four corridors, one stair space and one lift space. `proc-factory-dev-011-H03` expects **13**, excluding **17 reachable halls**. `proc-campus-dev-000-H03` expects **11**, excluding its reachable lobby. A stair landing may be reachable through a level doorway even when no stair connector is traversable; it still cannot count.
* **Shared-wall counts include hall bays.** `proc-factory-dev-003-H05` expects **7 = five ordinary rooms + two hall bays**, excluding the main aisle. `proc-factory-dev-005-H05` also expects **7 = five rooms + two halls**; `proc-factory-dev-007-H05` expects **6 = four rooms + two halls**. The ordinary kitchen target in `proc-factory-dev-011-H05` expects **4 = two rooms + two halls**. Counting only `type == 'room'` would fail all four.
* **Area aggregation is by `room_type`, even for `type == 'hall'`.** `proc-factory-dev-005-H02` asks for all warehouse-zone area and expects **1522.5 m²**. Its six matching warehouse zones are halls. Restricting an area tool to `type == 'room'` would return an incorrect zero.

These observations are verified on the selected labels, not a newly announced organizer schema. Encode eligibility explicitly in analysis tools and test it rather than inferring a single global definition of “rooms.”

### Nearest pickup is a sequential objective, not minimum total errand distance

All seven errands explicitly allow stairs and select the nearest asset-containing room by start-to-pickup route distance first. They then deliver to the largest requested room on the specified floor. Multiple assets in one room are one pickup candidate. No width restriction is implied merely because a stove, cabinet, or shelf is being carried.

Two questions distinguish the required objective from a shorter total trip:

| Question | Required nearest pickup | Required result | Incorrect globally shortest pickup + delivery |
|---|---|---:|---|
| `proc-campus-dev-001-H04` | Oscilloscope station in `F0-S006`, 26.31 m from the start | **100.67 m** via that pickup to Storage 2.06 | **90.01 m** via `F2-S007`; farther pickup but shorter combined trip |
| `proc-factory-dev-003-H04` | Stove in `F0-S028`, 20.82 m from the start | **132.35 m** to Kitchen 1.14 | **108.91 m** via the destination kitchen itself; skips the required nearest stove |

The candidate pickup-room counts are 25 (`campus-000-H04`), 8 (`campus-001-H04`), 6 (`campus-009-H04`), 7 (`factory-003-H04`), 10 (`factory-005-H04`), 5 (`factory-007-H04`), and 3 (`factory-011-H04`). A search page of 15 cannot support the first case. `proc-campus-dev-000-H04` and `proc-factory-dev-007-H04` keep start, nearest pickup and target on one floor; the other five deliver to a different floor.

### Width applies to all openings, with equality allowed

The eight questions say **“at least”** 1.0 or 1.1 m, so comparisons must use `>=`, not `>`. `proc-factory-dev-003-H03` expects **7** reachable ordinary rooms upstairs for a **1.1 m** load. Its ground-floor and first-floor lift access doors are exactly **1.1 m** wide. Filtering only room-entry doors or treating lift connectivity as automatically sufficient misses this bottleneck. Connector objects here have no `width_m`; enforce widths where the data supplies them rather than inventing a lift cabin size.

The two cross-floor delivery questions are `proc-campus-dev-009-H03` (1.0 m, floor 3, **10** rooms) and `proc-factory-dev-003-H03` (1.1 m, floor 1, **7** rooms). The six same-floor labels are campus 000 **11**, campus 001 **9**, campus 013 **6**, factory 005 **12**, factory 007 **8**, factory 011 **13**.

All audited named entrances are sufficiently wide. These labels therefore do **not** prove behavior when the entry door itself is narrower than the load. The tool should retain entrance identity and reject an impossible entry in a dedicated regression case, as required by MAP-08.

### Factory clear height is not floor elevation

All four factory buildings have ground-floor `height_m: 8.0`, but upper office-floor elevations are **3.5 m** and, where present, **7.0 m**. Do not accumulate `height_m` to calculate sensor distances or replace elevations with floor numbers. `proc-factory-dev-011-H06` uses centroid positions `(9.5, 29.325, 0)` and `(9.5, 8.725, 7)` and expects **21.76 m**. `proc-factory-dev-005-H06` expects **39.72 m** between ground and second floor. Campus elevations increment by 3.8 m.

This distinction is already documented generally, but the factory data supplies a concrete adversarial test. The local kit's route cost remains 12 m per floor for stairs and 15 + 6 m per adjacent floor for lifts; neither cost is the 3D sensor distance.

### Asset vocabulary and industrial map content do not establish new request kinds

`proc-factory-dev-005-Q01` asks for an **“air compressor”**, while its asset enum is `compressor`. `proc-campus-dev-013-Q04` says **“seating row”**, while its enum is `lecture_seating_row`. Search by names helps interpret these terms, but an exact typed count must resolve them to the enum before aggregation.

`proc-factory-dev-003-Q03` locates a **forklift charging station**; it does not request a forklift route. Industrial machine assets and production bays appear in these buildings, but no selected question specifies a forklift profile, destination-only production-bay traversal, moving equipment, or new Sunday response schema. Those route obligations come from the separately documented Synera clarification, not from a newly discovered kind in these files.

### Warm-up tours have a richer label shape than the current return object

Each of the eight tours asks for a **fixed order** and labels three stops plus **two leg objects**, each containing route length, space path and element path. `find_route(..., via=[...])` computes the ordered path but exposes only one flattened `RouteResult`; no `legs`, selected door/connector `element_path`, or explicit stops field is returned. Route length and room sequence therefore do not prove the displayed opening sequence or leg boundaries.

`proc-factory-dev-003-Q10` expects **276.28 m**, with legs **150.03** and **126.25 m**, and forces a floor-1 → ground → floor-1 tour. `proc-campus-dev-009-Q10` also returns to its starting floor after visiting ground. No tour permits reordering. The edited system prompt mentions `find_best_tour`, but the registered seven-tool list contains no such function; that mention is not implemented capability.

## Answer shapes and scoring boundaries

| Request | Required result shape |
|---|---|
| Largest room | Last `Answer:` line names selected room before any other room and includes area in m², ±5%. For example `proc-campus-dev-001-H01`: `Storage 2.06, 33.96 m²`. |
| Total floor area | Last `Answer:` line contains exactly one number, ±5%; no room ref or floor number on that line. |
| Delivery / shared-wall count | Last `Answer:` line contains exactly one integer, exact. |
| Errand | Last `Answer:` line contains exactly one number, ±1% or ±1 m, whichever is larger; retain pickup and destination as tool provenance outside that final numeric line. |
| Straight-line 3D | Last `Answer:` line contains exactly one number, ±2%. |
| Locate warm-up | Correct asset identity, containing room, floor and optional position; no mandatory benchmark `Answer:` line in these prompts. The warm-up evaluator scores identity in map state. |
| Count warm-up | Integer asset count on requested floor; the current warm-up evaluator only requires the labelled integer to appear in reply text, a weaker check than exact semantics. |
| Route / step-free / closure warm-up | From/to IDs, length, ordered spaces and selected elements in labels, or explicit unreachable shape when applicable. All 40 simple/step-free/closure examples here are reachable. |
| Tour warm-up | Ordered stops and two legs plus total. No unreachable tour is present. |

Do not run the nine-kind `benchmark.score` as if it understood warm-up labels. Conversely, `final_agent.evaluate` loads only `questions_basic.jsonl`; a green warm-up run does not verify any of these 40 scored questions.

## Current code evidence and required deterministic additions

The observed seven tools are registered at `final_agent/tools.py:121`. The following facts were read directly from the current implementation (the working tree already has unrelated edits to `final_agent/agent.py`, which this review preserved):

* `final_agent/building_map.py:108` searches by all-word substrings and optional floor. Returned search fields omit area, polygon, centroid and numeric elevation. `final_agent/tools.py:29` returns `matches` across spaces/assets and the first 15 records.
* `final_agent/building_map.py:192` builds the local anchor-based graph. It filters opening/connector step-free flags and closures, but never reads `width_m`. `final_agent/building_map.py:219` applies fixed per-floor costs. Furniture/machines are not obstacles.
* `final_agent/building_map.py:227` supports ordered stops; `RouteResult` at line 33 does not preserve selected element IDs or structured legs. `route()` stores the last successful route only, and failure/closure does not clear the old route.
* `final_agent/building_map.py:304` closes/reopens elements. `final_agent/tools.py:80` saves after mutating; no rollback on save failure. `final_agent/benchmark.py:10` supplies fresh state and temporary output per scored question, reducing cross-question contamination.
* `final_agent/building_map.py:312` adds a door using nearest polygon points, with a 0.6 m proximity check and fixed 0.9 m width. It is a persistent mutation, not shared-wall midpoint analysis or a non-persistent what-if tool.
* `final_agent/evaluate.py:59` is the label-informed warm-up oracle. It supplies expected IDs/closures and directly assigns locate identity. It does not establish natural-language success.

Recommended plain functions in `building_map.py` with thin interfaces in `tools.py`, avoiding a separate framework:

| Tool capability | Required input/output | Supports |
|---|---|---|
| Exact typed inspection / inventory | Floor, `room_type`/asset type; full matching IDs, numeric polygon area, centroid, elevation, opening width; compact count/aggregate output | All scored kinds and robust count |
| Area maximum and sum | Exact room type and floor; return selected room+area or total+matched IDs; include hall spaces when their room type matches | 15 scored area questions; every errand destination |
| Constrained reachability | Named entrance/start, target floor, step-free, minimum width and optional closure; reached IDs and a count with explicit eligibility | Eight deliveries; closure count kind absent here |
| Nearest equipment-containing room | Start, exact asset type and route constraints; deduplicate rooms; select by start-to-pickup path and return actual route/identity | Seven errands |
| Errand composition | Start, asset type, destination room type/floor; nearest pickup first, then maximum-area destination; return two legs and total | Seven errands |
| Shared-wall neighbours | Target ID, ≥1 m length within 0.35 m; IDs and qualifying lengths; include hall bays, exclude transit spaces | Four factory wall questions |
| Centroid XYZ distance | Two space IDs; numeric floor elevations and room centroids; straight-line metres | Six 3D questions |
| Enriched route result | Preserve selected openings/connectors, ordered stops and leg boundaries, explicit unreachable reason | Warm-up route/tour, map validity and future automatic route output |
| Isolated simulation / exit analysis | Clone state, reliable shared-wall midpoint, before/after nearest-exit distance with strict >1 m improvement count | `what_if_door`, absent here |
| Stacked-room overlap | Next higher/lower available floor; eligible space polygons and greatest overlap | `room_stacked`, absent here |

Synera's wall-respecting in-space paths with about 0.15 m wall clearance, physical-height vertical costs, forklift-only 3 m openings/aisles and destination-only production bays remain separate requirements. Do not silently switch those into the local labelled model; preserve and identify both models. The announcement supplies route validity/distance rules and ordered space sequences, not a new announced file schema.

## Representative tests in three tiers

Tier is analysis metadata, not a dataset field. **Easy** isolates one lookup/filter/area operation or an ordinary same-floor route. **Medium** introduces spatial arithmetic, a floor change, accessibility, or one geometric/count constraint. **Hard** composes selections and routes, applies a closure, fixes tour order, or combines width/accessibility across floors. The complete annotations contain **56 easy, 39 medium and 25 hard** cases.

| Tier | Question ID | Check and expected result | Why select it |
|---|---|---|---|
| Easy | `proc-campus-dev-013-Q04` | Eight seating rows on ground floor | Natural term differs from enum `lecture_seating_row`; count assets, not rooms |
| Easy | `proc-factory-dev-003-Q03` | Forklift charging station in Logistics zone H-C5, ground floor | Industrial locate without falsely imposing forklift routing |
| Easy | `proc-campus-dev-001-H01` | Storage 2.06, **33.96 m²** | Single typed maximum and selected-room-first output |
| Easy | `proc-factory-dev-005-H02` | **1522.5 m²** | Warehouse areas are `hall` spaces; rejects universal room-only filter |
| Medium | `proc-factory-dev-011-H06` | **21.76 m** | Actual elevations 0 and 7 m despite ground clear height of 8 m |
| Medium | `proc-factory-dev-007-H03` | **8 rooms**, 1.1 m | Reachability must exclude eight reached halls |
| Medium | `proc-factory-dev-011-H05` | **4 shared-wall neighbours** | Shared-wall count must include two halls, unlike delivery count |
| Medium | `proc-campus-dev-013-Q08` | Step-free route, **98.48 m** | Multi-floor lift routing under local kit model |
| Hard | `proc-factory-dev-003-H03` | **7 rooms upstairs** at minimum width **1.1 m** | Both lift access doors equal the threshold; constraint equality matters |
| Hard | `proc-campus-dev-009-H03` | **10 rooms on floor 3** at minimum width **1.0 m** | Six-floor campus, multi-floor constrained count |
| Hard | `proc-campus-dev-001-H04` | **100.67 m**, pickup `F0-S006`, target `F2-S006` | Minimum total tour chooses the wrong pickup and returns 90.01 m |
| Hard | `proc-factory-dev-003-H04` | **132.35 m**, pickup `F0-S028`, target `F1-S014` | A stove already at destination is a tempting wrong pickup |
| Hard | `proc-campus-dev-000-H04` | **37.38 m**, pickup `F4-S024`, target `F4-S008` | 25 candidate pickup rooms exceed the search-result page |
| Hard | `proc-campus-dev-000-Q09` | Close Staircase 2, alternate route **118.17 m** | Named closure must affect routing and be isolated |
| Hard | `proc-factory-dev-003-Q10` | Ordered tour total **276.28 m**, legs **150.03 / 126.25 m** | Required return to original floor and explicit leg boundaries |

These are recommended source fixtures for the parent analysis runner. Missing capabilities should be reported as gaps, not replaced with expected labels in the production answer path. Add synthetic regression fixtures for unreachable routes, width below/equal/above threshold, entry too narrow, closed lift causing disconnection and state rollback, because this eight-building subset contains none of those negative examples.

## Offline verification performed

A read-only `.venv/bin/python` audit computed the 40 scored label values independently from `building.json` with Shapely/NetworkX, using exact typed area, centroid/elevation arithmetic, width-filtered step-free graph reachability, nearest-pickup-first errands and boundary-neighbour geometry. **40/40 matched labels to their recorded precision.** This establishes the proposed calculations on this sample; none of these new analysis functions is currently registered as a product tool.

The same audit exercised current search and routing for all 80 warm-up fixtures, using labelled endpoint/closure IDs for route setup. The 24 locate subjects each resolved to one expected asset, all eight substring-search counts matched their labels, and route sequences/lengths matched within the warm-up tolerance. Two tour totals differ by one centimetre when separately rounded labelled legs are compared with rounding the summed raw distance (`proc-campus-dev-001-Q10` and `proc-factory-dev-007-Q10`); both are well inside the evaluator's 1% distance tolerance. This is component evidence with label-informed setup, not a live conversation or official scored benchmark result.
