# Residential request audit

The eight selected Swiss Dwellings and ResPlan buildings contain **94 questions: 23 scored questions and 71 warm-up questions**. Every row of both question files was reviewed. `residential_annotations.json` records one annotation per source question, with an exclusive subtype and difficulty tier. Labels were read for verification and analysis only. No production answers or live API calls were made.

| Building | Source family | Scored | Warm-up | Distinguishing coverage |
|---|---|---:|---:|---|
| `swiss-450` | Swiss Dwellings | 4 | 10 | Apartment names, thick walls, cross-floor unreachable results |
| `swiss-460` | Swiss Dwellings | 3 | 10 | Levels 0, 2, 3, 4; nearest-pickup order changes expected distance |
| `swiss-5097` | Swiss Dwellings | 4 | 8 | Basement, 19-item count, outside/re-entry routes, same-floor inaccessible pair |
| `swiss-1689` | Swiss Dwellings | 1 | 7 | Basement-to-upper-floor routes; a same-floor tour leg needs a floor detour |
| `resplan-8269` | ResPlan | 2 | 9 | Five-room home; wide delivery includes entrance room |
| `resplan-14509` | ResPlan | 2 | 9 | Width thresholds cut alternate bathroom accesses |
| `resplan-15179` | ResPlan | 3 | 9 | Nine rooms plus three outdoor spaces; near-threshold doors |
| `resplan-1677` | ResPlan | 4 | 9 | Nearest-first errand differs greatly from shortest overall tour |
| **Total** | | **23** | **71** | |

## Question types and current tool coverage

“Implemented” below means a deterministic operation exists in the current `final_agent` tool path. It does not claim live conversational accuracy, UI completion or compliance with the newer Synera route model. Code inspected: `final_agent/tools.py:20–121`, `final_agent/building_map.py:108–290`, `final_agent/evaluate.py:26–88`, and `final_agent/storage.py:68–110`.

| Kind | Scored / warm-up count | Current status | Missing tool or capability |
|---|---:|---|---|
| `locate` | 0 / 19 | Implemented: all 19 source phrases resolve to one asset using `BuildingMap.search` | None for these unambiguous cases; a map highlight is a separate product requirement |
| `count` | 0 / 8 | Partial: substring search and its full `matches` count happen to match these exact labels, but no exact typed aggregate exists | `count_assets(asset_type, floor)` or exact typed enumeration; never count a truncated result array |
| `route` | 0 / 24 | Implemented under the local anchor model; offline direct checks reproduce all 24 labelled distances and paths | Complete selected opening/connector trace remains absent from `RouteResult`; wall-respecting Synera routing is separate |
| `route_step_free` | 0 / 8 | Implemented locally, including three unreachable outcomes | Clear stale route on failure; retain selected elements for render/validation |
| `route_with_closure` | 0 / 4 | Implemented locally: close the named staircase, then report unreachable in all four cases | Transactional/isolation and stale-route guarantees for multi-turn use |
| `tour` | 0 / 8 | Implemented locally using `find_route(..., via=[...])`; all eight totals and concatenated paths reproduce labels | Return explicit leg boundaries and selected elements; no reordered tour is needed by these questions |
| `largest_room` | 4 / 0 | Not implemented as a scored operation | Exact room-type/floor filter, polygon areas and deterministic maximum (`BEN-01`, `MAP-07`) |
| `floor_area_total` | 6 / 0 | Not implemented | Exact room-type/floor area aggregation (`BEN-02`, `MAP-07`) |
| `errand` | 4 / 0 | Not implemented; search and ordered routes are only some primitives | Complete asset-bearing-room enumeration, nearest reachable pickup by route distance, largest destination, two-leg total (`BEN-08`) |
| `wide_delivery_count` | 3 / 0 | Not implemented; `graph` has step-free filtering but no minimum width | Entrance-aware width filtering and reachable eligible-room count (`BEN-06`, `MAP-08`) |
| `shared_walls_count` | 6 / 0 | Not implemented; point-radius spatial search is insufficient | Boundary adjacency with 0.35 m wall tolerance, 1 m minimum length and eligible-space filtering (`BEN-05`) |
| `straight_line_3d` | 0 / 0 | Absent from this slice; dedicated operation is also absent in code | Centroid XYZ distance (`BEN-03`); absence of examples is not evidence it is implemented |
| `room_stacked` | 0 / 0 | Absent from this slice; dedicated operation is absent | Adjacent available floor plus maximum overlap (`BEN-04`). README excludes Swiss floors from stacked questions because some are not aligned |
| `step_free_reachable_count` | 0 / 0 | Absent from this slice; dedicated operation is absent | Isolated closure plus constrained reachable-room count (`BEN-07`) |
| `what_if_door` | 0 / 0 | Absent from this slice; dedicated operation is absent | Non-persistent shared-wall-midpoint door simulation and before/after exit-distance aggregation (`BEN-09`) |

The seven exposed tools are `building_overview`, `search_building`, `spatial_search`, `find_route`, `set_closed`, `add_door` and `show_route`. Neither search tool exposes room polygons, areas, centroid/elevation geometry or opening widths. `add_door` mutates and saves; it is not a what-if tool. Its nearest-point placement is also different from the shared-wall midpoint specified for scored door questions.

## Exact subtype counts

These are analysis subtypes within the supplied kinds, not proposed new official question kinds. Each question has exactly one subtype here. Additional characteristics are preserved in annotation notes.

| Kind | Analysis subtype | Count |
|---|---|---:|
| `locate` | `unambiguous_asset_lookup` | 19 |
| `count` | `exact_asset_type_floor` | 7 |
| `count` | `exact_asset_type_floor_over_search_limit` | 1 |
| `route` | `same_floor_indoor` | 14 |
| `route` | `cross_floor_indoor` | 4 |
| `route` | `cross_floor_via_outside` | 6 |
| `route_step_free` | `same_floor_reachable` | 5 |
| `route_step_free` | `cross_floor_unreachable` | 2 |
| `route_step_free` | `same_floor_unreachable` | 1 |
| `route_with_closure` | `staircase_closure_unreachable` | 4 |
| `tour` | `ordered_tour_same_floor` | 4 |
| `tour` | `ordered_tour_cross_floor` | 2 |
| `tour` | `ordered_tour_via_outside` | 1 |
| `tour` | `ordered_tour_with_floor_detour` | 1 |
| `largest_room` | `exact_room_type_max_area` | 4 |
| `floor_area_total` | `exact_room_type_area_sum` | 5 |
| `floor_area_total` | `exact_room_type_area_sum_basement` | 1 |
| `errand` | `nearest_pickup_then_largest_destination` | 1 |
| `errand` | `nearest_pickup_before_delivery_optimization` | 3 |
| `wide_delivery_count` | `width_reachability_includes_start_room` | 2 |
| `wide_delivery_count` | `width_reachability_excludes_outdoor` | 1 |
| `shared_walls_count` | `thick_wall_adjacency` | 4 |
| `shared_walls_count` | `thick_wall_adjacency_excludes_outdoor` | 2 |
| **Total** | | **94** |

Tier totals in the annotation file are **46 easy, 27 medium and 21 hard**. Difficulty reflects the number of deterministic operations, topology/state issues and misleading alternatives; it is not a benchmark score.

## Under-documented outcomes and traps

**The nearest pickup is selected before optimizing delivery distance.** Three labelled questions distinguish this from finding the shortest overall pickup/delivery tour. All four residential errands explicitly allow stairs; none requests an unordered tour. Asset candidates are building-wide, even though the destination is restricted to a floor and room type. **Pickup eligibility differs from counted-room eligibility:** the selected pickup in `swiss-5097-H03` is Balcony 2.61 (`type=outdoor`), and in `resplan-1677-H03` it is Balcony 0.09 (`type=outdoor`). These balconies must remain valid pickup spaces even though outdoor spaces are excluded from reachable-room and shared-wall counts. A shared global `type == "room"` filter would break these errands.

| Source question | Pickup spaces by exact asset type | Expected nearest-first result | Shortest overall two-leg choice, which would be wrong |
|---|---:|---|---|
| `swiss-450-H03` | 8 bathtub-containing spaces, across four floors | Via `F1-S018`, to `F1-S016`: **9.02 m** | Same selected pickup in this example |
| `swiss-460-H03` | 26 wardrobe-containing spaces, across four floors | Via `F3-S017`, to `F3-S013`: **15.72 m** | **14.26 m**, by picking up in the destination room `F3-S013` |
| `swiss-5097-H03` | 46 plant-containing spaces, across three floors | Via `F2-S061`, to `F2-S047`: **31.15 m** | **24.17 m**, via `F2-S045` |
| `resplan-1677-H03` | 3 plant-containing spaces | Via `F0-S009`, to `F0-S003`: **19.82 m** | **12.31 m**, via `F0-S001` |

These candidate counts and competing lengths were recomputed offline from building data and the existing graph; none of the pickup candidates is unreachable in these four examples. Unreachable-pickup handling remains a necessary general behavior, not an observed residential subtype in this selection.

**Width counts include the room entered from outside.** `resplan-8269-H01` counts four rooms, including Living room 0.01; `resplan-14509-H01` counts three, again including the living room. `resplan-15179-H02` counts six eligible rooms from nine `type=room` spaces and excludes three `type=outdoor` polygons. Its doors at 1.096 m fail a 1.1 m requirement; rounding door widths before filtering would be incorrect. All three entrances are step-free and wider than the specified load. None of these three cases has a door exactly at the threshold, so equality requires a supplemental synthetic test rather than a claim of observed coverage.

**Wall adjacency is not an opening graph or exact polygon contact.** Exact coincident-boundary intersection finds no eligible neighbour of at least 1 m in any of the six labelled cases; labelled counts are 4, 3, 3, 3, 3, 3. Buffering the other boundary by 0.35 m and measuring the source boundary portion in that buffer reproduces all six counts when eligible spaces have `type == "room"`. This is evidence on these cases, not proof of every corner/threshold geometry. For example, `swiss-450-H04` has four neighbours separated by approximately 0.141–0.186 m. `swiss-5097-H04` excludes adjacent corridors, a stair hall and Balcony 1.106 (`type=outdoor`); `resplan-1677-H04` excludes Balcony 0.10. Outdoor exclusion is not explicitly named in the question prose's list of corridors/stairwells/lifts.

**A same-floor request need not admit a same-floor route, or any constrained route.** `swiss-5097-Q06` has both endpoints on floor 2 but labels `reachable: false` under the step-free constraint. In `swiss-1689-Q07`, the first tour leg starts and ends on floor 1 but goes via floor 0. Its second leg also descends before ascending to floor 3. Preserve the computed floor sequence; a simplistic monotone vertical route would fail.

**The supplied local labels use outside/re-entry transitions.** All six ordinary routes in `swiss-5097-Q03–Q05` and `swiss-1689-Q02–Q04` explicitly include `outside`. Both legs of `swiss-5097-Q08` do as well. These are valid local anchor-model labels with the common zero-cost outside node, not physical inter-building walkway lengths. README says benchmark shortcuts make no difference; these examples are warm-up route labels and show the behavior still needs to be retained for local compatibility. Synera's separate ordered-space validation, interior wall clearance and height costs must not be silently substituted for these label distances.

**Basements and sparse floor levels need typed floor resolution.** `swiss-5097-H02` asks for storage area on “basement 1”, which is numeric level -1, and expects **14.66 m²**. `swiss-460` has levels 0, 2, 3 and 4, with no level 1; its scored bedroom questions target level 3. The supplied residential warm-up routes do not traverse its 0→2 connector edge, so a gap-span regression is additional coverage rather than an observed request subtype.

**Detailed search truncation is not inventory truncation.** `swiss-5097-Q02` expects 19 wardrobe items on floor 1. `search_building` reports `matches=19`, but returns only 15 detailed records (`final_agent/tools.py:36–39`, `MAX_SEARCH_RESULTS=15`). All eight count questions happen to have substring search matches equal to exact typed asset counts. This does not establish correctness for overlapping type names or a mixed room/asset query. Exact aggregate tools should make this reliable without asking an LLM to infer completeness.

**Duplicate questions should not inflate the representative test set.** `resplan-8269-Q05/Q06`, `resplan-15179-Q06/Q07`, and `resplan-1677-Q05/Q06` each repeat identical prompt text and labels. They still count as six source rows in the exhaustive audit. Select one member of each pair for a representative behavioral suite.

No unlisted official `kind` occurs in these 94 rows. The new findings are expected-result and composition subtypes within documented kinds. There is no evidence here for a new Sunday schema, release time, forklift question file or plan-ingestion question format.

## Expected result shapes

Scored `largest_room` questions require the selected room name/number first and its area on the final `Answer:` line. The four expected room/area pairs are `swiss-450-H01`: Bedroom 1.16, 19.86 m²; `swiss-460-H01`: Bedroom 3.13, 20.42 m²; `swiss-5097-H01`: Living room 0.07, 38.08 m²; `resplan-1677-H01`: Bedroom 0.03, 24.94 m². Area tolerance is 5%.

The six scored area totals are `swiss-450-H02`: 91.12; `swiss-460-H02`: 106.34; `swiss-5097-H02`: 14.66; `swiss-1689-H01`: 157.43; `resplan-15179-H01`: 19.67; `resplan-1677-H02`: 16.45. Each final `Answer:` line must contain exactly one number, within 5%. Errands likewise contain exactly one distance number, within 1% or 1 m, whichever is larger. Counts contain exactly one exact number, with no range or alternative numeric answer. Source labels are fixtures for verification; they must not enter the production answer path.

Warm-up locate labels contain `asset_id`, containing space, floor level and position. Count labels contain count, exact asset type and floor level. Reachable route labels contain endpoint IDs, `optimal_length_m`, `space_path` and `element_path`; unreachable labels instead have `reachable: false` and may add `closed_element_id`. Tours contain ordered stops, total distance and two leg results. The current `RouteResult` provides distance and room path but omits the label's selected element trace and explicit leg results. A numeric zero must not be used as the generic representation of an unreachable route.

## Necessary deterministic tool interfaces

These can remain plain functions in the existing module boundaries; they do not require a new framework.

| Proposed operation | Minimum useful output | Why needed |
|---|---|---|
| Exact `list_spaces` / `list_asset_rooms` / `count_assets` | Complete typed IDs, floor, room type; exact aggregate counts and unique pickup-space IDs | Prevent substring and pagination mistakes; deduplicate multiple items in one space and retain outdoor pickup spaces |
| `room_area_summary(floor, room_type)` | Matching count, total area, largest room ID/name and area | Covers both area kinds and the destination-selection part of errands |
| `constrained_distances(start, step_free, min_width, closures, entrance)` | Distances and predecessor/selected-element data for every reachable space | Reuse one graph traversal for nearest pickup, reachability and valid ordered paths |
| `count_reachable_rooms(...)` | Eligible room IDs/count on target floor; excluded/unreachable reasons as useful evidence | Width and accessibility counts, including start-room and outdoor semantics |
| `plan_errand(start, asset_type, destination_floor, destination_room_type, constraints)` | Chosen nearest pickup room, largest target, each leg and summed length | Preserve pickup-first semantics instead of total-tour optimization |
| `shared_wall_neighbors(room)` | Eligible neighbour IDs and qualifying boundary lengths | Wall-thickness geometry and type exclusions can be verified directly |
| Complete route result | Ordered graph nodes, selected opening/connector IDs and leg boundaries | Reconstruct outside transitions, floor detours and displayed/validated routes |
| Typed answer renderer | Final `Answer:` line produced from computed result | Enforce numeric cardinality and room-first formatting without changing `benchmark/score.py` |

The four scored kinds absent here still require the XYZ distance, floor overlap, isolated closure-count and isolated what-if tools listed in the coverage table. `final_agent.benchmark:answer` already gives each question fresh building/conversation state and temporary outputs. It does not create any of the missing deterministic calculations.

## Representative source tests in three tiers

Each row names a real, runnable fixture for the parent representative-suite manifest. The offline checks use source labels as verification; an optional live runner must pass only the question text and building directory to the production adapter.

| Tier | Question ID | Expected assertion and selection reason |
|---|---|---|
| Easy | `resplan-8269-Q01` | Locate microwave in Kitchen 0.05; unambiguous asset lookup |
| Easy | `resplan-14509-Q04` | Exact `dining_chair` count is 3; multiword type normalization |
| Easy | `resplan-14509-Q05` | Bedroom→living room route is 4.38 m; one-door baseline |
| Easy | `swiss-450-H01` | Bedroom 1.16 with area 19.86 m²; exact type and area maximum |
| Easy | `swiss-5097-H02` | Basement storage total is 14.66 m²; negative floor parsing |
| Medium | `swiss-5097-Q02` | Count is 19 despite only 15 displayed detail rows |
| Medium | `resplan-8269-H01` | Width 1.0 m, step-free reachable count 4; start room included |
| Medium | `resplan-15179-H02` | Width 1.1 m count 6; exclude outdoor polygons and 1.096 m openings |
| Medium | `swiss-450-H04` | Shared-wall count 4 despite no exact qualifying boundary coincidence |
| Medium | `resplan-1677-Q09` | Preserve specified ordered tour, total 28.75 m and two legs |
| Hard | `swiss-460-H03` | Nearest-first wardrobe errand 15.72 m, not shorter total-tour choice |
| Hard | `swiss-5097-H03` | 46 candidate spaces including balconies; nearest-first plant errand 31.15 m |
| Hard | `resplan-1677-H03` | Three-candidate errand 19.82 m; demonstrates ordering even on a small map |
| Hard | `swiss-5097-H04` | Shared-wall count 3; excluded corridor/stair-hall/outdoor neighbours |
| Hard | `swiss-5097-Q03` | 31.25 m cross-floor route with required outside/re-entry transition |
| Hard | `swiss-5097-Q06` | Same-floor step-free request is unreachable |
| Hard | `swiss-450-Q09` | Close Main staircase; route becomes unreachable; no relaxation |
| Hard | `swiss-1689-Q07` | Ordered tour total 156.85 m; first leg needs a descent to floor 0 |

Supplement the real fixtures with small synthetic regressions for width equality, outside/entry-width enforcement, corner-only wall contact, exact 1 m shared-length threshold, 0→2 connector span, multiple assets in one pickup room, unreachable pickup candidates, route invalidation after a failed attempt, and mutation rollback. They are correctness boundaries identified from contracts/code, not newly observed source question types.

## Verification actually performed

An offline script loaded fresh `final_agent.BuildingMap` instances for all 44 residential warm-up route-family cases and called the actual core using fixture endpoint/closure/stop IDs. **24 ordinary routes, 8 step-free routes, 4 closure routes and 8 tours matched the labelled reachable/unreachable outcome and distance; every successful ordered space path also matched the fixture path** (tour paths compared after concatenating labelled legs). This is component verification with labelled inputs, not a natural-language interpretation score. Search was separately checked for all 19 locate phrases and eight count phrases. Building-derived areas, three width counts, six tolerant wall counts and four errand selections were recomputed for analysis; these computations are not exposed production tools.

No live conversational run, Anthropic credits, official scored benchmark result or Synera automatic-route score is claimed.
