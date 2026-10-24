# OSM request review

Reviewed every line of both question files for all four selected OSM buildings: **30 scored questions and 36 warm-up questions, 66 total**. The accompanying `osm_annotations.json` has exactly one classification per source question. Labels were used only to inspect expected results and verify offline calculations. No product code, root documentation or scorer was changed; no live model call was made.

| Building | Levels | Spaces / assets | Scored / warm-up | Why it matters |
|---|---|---:|---:|---|
| `osm-way22744230` | -1 through 6 | 325 / 890 | 9 / 10 | Eight floors, the selected set's only scored lift-outage count, three downward stacking questions. |
| `osm-way27326387` | -2, 0, 1 | 61 / 184 | 8 / 7 | Missing level -1, one staircase, both step-free and closure disconnection cases. |
| `osm-way27917482` | -1 through 3 | 1,623 / 5,250 | 9 / 10 | Large aggregation, duplicate names on the same floor, both scored what-if questions. |
| `osm-way360544293` | 0, 1, 2 | 46 / 217 | 4 / 9 | Named shops/lounge spaces, a 22-candidate-room equipment errand, entrances above ground. |

## Exact kind and subtype counts

These are existing kinds, not newly invented benchmark labels. No unknown kind occurs in these 66 questions. `wide_delivery_count` has **zero** examples in these four buildings; it must be covered by the other building families. Difficulty is a review classification, not an organizer field: **20 easy, 32 medium, 14 hard**.

| Source | Kind | Count | Subtypes, with exact counts |
|---|---|---:|---|
| Scored | `largest_room` | 4 | `typed_floor_max_area` 4 |
| Scored | `floor_area_total` | 4 | `typed_floor_sum_area` 4 |
| Scored | `step_free_reachable_count` | 1 | `lift_outage_floor_reachability_count` 1 |
| Scored | `errand` | 3 | `nearest_asset_then_largest_room_stairs` 3 |
| Scored | `room_stacked` | 9 | `below_max_polygon_overlap` 7; `above_max_polygon_overlap` 2 |
| Scored | `shared_walls_count` | 3 | `same_floor_wall_neighbors` 3 |
| Scored | `straight_line_3d` | 4 | `centroid_elevation_distance` 4 |
| Scored | `what_if_door` | 2 | `corridor_to_corridor_exit_improvement` 1; `room_to_room_exit_improvement` 1 |
| Warm-up | `locate` | 9 | `unique_asset_location` 9 |
| Warm-up | `count` | 4 | `exact_type_floor_asset_count` 4 |
| Warm-up | `route` | 12 | `same_floor_route` 4; `cross_floor_route` 8 |
| Warm-up | `route_step_free` | 4 | `cross_floor_step_free_reachable` 2; `cross_floor_step_free_unreachable` 1; `same_floor_step_free_reachable` 1 |
| Warm-up | `route_with_closure` | 3 | `connector_closure_reachable` 2; `connector_closure_unreachable` 1 |
| Warm-up | `tour` | 4 | `ordered_two_leg_tour` 4 |

## Coverage in the current agent

“Implemented” below means an exposed deterministic computation exists. It does not claim live conversational accuracy, a rendered-path check or scored benchmark completion. Scored geometry is unavailable through the current tool surface even where polygons exist internally.

| Question type | Implemented? | Current evidence / missing capability |
|---|---|---|
| Locate a unique named asset | Yes, core lookup | `BuildingMap.search` records located IDs, `final_agent/building_map.py:108`; `search_building` exposes name, room and floor, `final_agent/tools.py:29`. Search still truncates displayed results at 15. |
| Exact asset count by floor/type | Partial | Search exposes total substring matches and only 15 displayed entities, `final_agent/tools.py:39`. It mixes asset and space results; no exact typed count/inventory tool exists. Warm-up oracle separately counts exact asset types, `final_agent/evaluate.py:72`, which is not an agent tool. |
| Route; step-free route | Yes, local graph core | `graph` and `route`, `final_agent/building_map.py:192` and `:227`, support anchors, openings, parallel connectors and step-free flags. Route results omit selected element IDs and leg records. |
| Route after connector closure | Yes, core mutation + route | `set_closed`, `final_agent/building_map.py:304`, and `find_route`, `final_agent/tools.py:62`. Closure tool saves state; route failure can leave an earlier `last_route`. Same-name ambiguity remains a required user interaction. |
| Ordered tour | Yes, distance/order core | `route(..., via=...)` preserves stop order, `final_agent/building_map.py:230`. Leg boundaries and selected edge IDs are discarded from `RouteResult`. |
| Largest room; total floor area | No | Need exact floor/room-type filtering and polygon areas. Search returns neither area nor polygons. |
| Stacked room above/below | No | Need next available floor and maximum polygon-overlap calculation, not search or nearest point. |
| Shared-wall count | No | Need boundary contact length with 0.35 m wall-thickness tolerance and eligibility rules. Current door adjacency's 0.6 m proximity check is a different operation. |
| Centroid/elevation 3D distance | No | Need polygon centroid and `elevation_m`; current `anchor` deliberately uses `representative_point`, `final_agent/building_map.py:188`. |
| Lift-outage reachable-room count | No, graph primitives exist | Closure + step-free component computation can produce the sample's 30, but no exposed eligible-room reachability aggregation exists. |
| Nearest-item then largest-room errand | No, route primitive exists | Need full exact candidate-room inventory, nearest-by-route selection, largest-room selection and two-leg composition. The pickup objective is start→pickup first; optimizing the complete trip can select the wrong pickup. |
| What-if door, other-floor egress improvement | No, edit primitive exists | Need isolated simulation, robust shared-wall midpoint, nearest-exit distances, strict >1 m comparison and aggregate. `add_door` instead uses nearest polygon points and persists through the agent tool, `final_agent/building_map.py:312`, `final_agent/tools.py:99`. |

The benchmark adapter uses a fresh map and temporary output directory per question (`final_agent/benchmark.py:10`), which prevents state leaking between benchmark questions. It does not make a persistent edit tool a proper within-question what-if operation. `final_agent.evaluate` reads `questions_basic.jsonl`, not scored questions; its oracle deliberately reads labelled answers and is not evidence of live interpretation.

## New or underdocumented observations

1. **A source question is genuinely ambiguous even after floor disambiguation.** `osm-way27917482-Q09` names “Generic room 03.08.033 (Floor 3)”. IDs `F3-S015`, `F3-S016` and `F3-S017` all share both name and ref on that floor. The label selects `F3-S016`. After the stated stairs closure, direct-ID offline routes measure 156.65, **154.82**, and 153.12 m respectively; the alternatives fall outside the warm-up 1% tolerance. `resolve_space` correctly raises `MapError` for the shared name. A live agent should ask for disambiguation; a fixture using labelled IDs is only a core-routing test. A forced one-turn text score cannot establish the user's intended start from this wording.

2. **Warm-up labels exercise outside re-entry extensively, including across floors.** Examples: `osm-way27917482-Q05` goes ground→floor 3 in **51.77 m** through `outside`; `osm-way360544293-Q05`, `-Q06`, `-Q07` also use outside between different floors. `osm-way27917482-Q07` has basement endpoints but travels via ground floor/outside. README's assurance that the shortcut makes no difference is phrased about benchmark questions; these warm-up routes show behavior beyond that assurance. This review has not proved the shortcut's effect on scored answers. Preserve local compatibility and show outside discontinuities explicitly; do not infer physical inter-floor teleportation for the Synera route model.

3. **Route labels distinguish spaces from selected transitions.** Every reachable warm-up route includes `space_path` and `element_path`; tours include those fields separately for each of two `legs`. An opening normally appears twice in `element_path` because it connects room→door→room; a vertical connector appears once per graph stop transition. `RouteResult` retains only space path/steps/total (`final_agent/building_map.py:33`). Renderer `route_points_on_floor` removes `outside` and selects the first opening joining two rooms (`final_agent/viewer.py:24`), so outside re-entry, repeated-floor tours (`osm-way27917482-Q10`) and parallel doors require richer route data, even when the length matches.

4. **“Below” has two distinct floor concerns.** Nine scored stacking cases mean greatest positive polygon overlap, seven below and two above. In `osm-way27326387`, available levels are **-2, 0, 1**, but its three actual stacking questions (`-H04` to `-H06`) span only 0↔1. They do not verify gap-spanning stacking. Its routes `-Q03/-Q04`, errand `-H03`, and 3D link `-H08` do exercise the level gap. `-H08` uses elevations +3 and -6 m, a **9 m** vertical difference. Add a separately marked synthetic next-available-floor regression to cover missing-level stacking; do not claim these labels already cover it.

5. **A lift outage does not imply zero reachable rooms.** `osm-way22744230-H03` closes `V07` (“Lift 1”), starts in ground-floor Stairwell N0320A, and expects **30 rooms on floor 2**. An offline closure + step-free graph component reproduces 30. Inspecting names such as “Stairwell” or counting lifts is not a valid substitute for graph reachability. Conversely, `osm-way27326387-Q05` is step-free-unreachable and `-Q06` is unreachable after its sole stairs close; both labels use `reachable:false` and omit a length.

6. **What-if endpoints can be two corridors or two rooms, and their effect can run downward.** `osm-way27917482-H08` inserts a floor-2 corridor↔corridor door and counts **6 floor-3 rooms**; `-H09` inserts a ground-floor generic-room↔generic-room door and counts **2 basement rooms**. The latter polygons' raw boundary intersection is a `MultiPoint`, not a shared `LineString`; wall-thickness/contact reasoning is needed rather than assuming exact boundary overlap. The former has an exact shared segment from `(43.667,-19.001)` to `(42.881,-21.798)`. Current `add_door` chooses its endpoint `(42.881,-21.798)`, not midpoint `(43.274,-20.3995)`. Ad-hoc before/after counts with current insertion still happen to match 6 and 2; those two final counts alone do **not** validate placement correctness. No files or original map were edited in that diagnostic.

7. **Display names, `room_type`, and space `type` are separate fields.** `osm-way27917482-H01` asks for the largest lobby; its answer is **Rechnerhalle, 298.10 m²**, whose `room_type` is `lobby` but space `type` is `hall`. `osm-way360544293-H01` asks for generic rooms and expects **Edeka, 129.93 m²**. Filtering literal display names, or always filtering `type == room` before an explicitly requested subtype, would fail these requests. Reachability's eligible-room policy must be explicit and verified separately; room-area filters must follow the requested `room_type`.

8. **Complete candidate sets are essential even on modest maps.** `osm-way22744230-H02` sums **25** matching polygons, `osm-way27326387-H02` sums **16**, and `osm-way27917482-H02` sums **250**. They exceed 15 displayed search results. `osm-way360544293-H03` considers **53 chairs in 22 distinct pickup rooms**; deduplicate candidate rooms and compare route distance rather than checking one asset or exhausting model tool iterations. `osm-way360544293-Q04` counts 16 chairs on floor 2. These are correctness/scaling fixtures, not measured latency failures; no latency target is supplied.

9. **Expected output shape is task-specific.** Numeric scored results need exactly one number on the final `Answer:` line: exact count for reachability/walls/what-if, ±5% area totals, ±2% 3D distance, and max(±1%, ±1 m) errands. Largest-room replies require the selected room first **and its area**; stacking replies require the selected room first. IDs, floor numbers or runner-up numbers on a numeric answer line can invalidate an otherwise correct value. Source answers also contain verification-only `via`/`target` for errands and accept/reject aliases for room answers; these are not extra user output requirements.

## Necessary deterministic tools

These are proposed capabilities, not an announced organizer schema. They can be small functions in existing modules and compact agent wrappers; they do not require a new framework.

| Capability | Used by | Required behavior |
|---|---|---|
| Exact entity inspection and complete typed enumeration/count | Count, area, errand, all geometry | Distinguish assets/spaces; filter exact type/room_type and floor; expose area, centroid XYZ, elevations, widths and relevant IDs; return full aggregate independent of search display limit. |
| Floor/type area summary | Largest room, total floor area | Compute polygon maximum and sum over complete exact filter; retain winner ID/name and area. Explicit room_type requests can include `type:hall` lobbies. |
| Next-floor overlap lookup | Stacked room | Choose next available level in requested direction; compute greatest positive overlap in a shared XY frame; report no-floor/no-overlap cases explicitly. |
| Shared-wall inspection/count | Shared walls, valid door placement | Measure contiguous/contact boundary length with 0.35 m tolerance, >=1 m threshold, corner rejection and room eligibility; find a valid shared-wall midpoint. |
| Constrained reachable-room aggregation | Width delivery, step-free outage | Specified entrance, opening width including threshold equality, step-free flags, isolated closures, target-floor filter and explicit eligible-space rules. Width delivery is absent from this OSM subset but needed globally. |
| Nearest reachable asset-room selection + errand composition | Errand | Deduplicate exact asset-type rooms, choose closest by constrained first-leg distance, then route to largest requested destination; retain selection evidence and both leg lengths. |
| Isolated door/egress simulation | What-if door | Clone map, compute shortest distance to nearest exit before/after, insert a midpoint door, compare every target-floor eligible room by strictly >1 m; handle disconnected cases explicitly; leave state/files unchanged. These two examples do not specify all infinite-distance edge behavior. |
| Complete route result and faithful rendering | Route, tour, closures, automatic route check | Retain graph nodes, selected opening/connector IDs, outside transitions and leg boundaries; invalidate stale routes after changes/failures; render discontinuities and repeated floor visits faithfully. Keep local anchor costs distinct from Synera physical-route rules. |
| Floor-aware ambiguity candidates | Repeated-name requests | Return stable IDs plus enough location context to distinguish same-name/ref spaces even when their floor is identical; do not select the labelled ID from expected answers. |

## Representative runnable fixture selection

The parent analysis supplies the runnable harness and consolidated selection. The rows below identify exact source fixtures and the assertions it should make. Difficulty reflects reasoning/state/scale; it is independent of implementation status. Known unsupported computations belong in gap tests, rather than silently substituting labelled answers into the production path.

| Tier | Question | Expected assertion / reason |
|---|---|---|
| Easy | `osm-way22744230-Q01` | Unique lectern asset `A00152` in Lecture hall N0314, level 0. Lookup smoke test. |
| Easy | `osm-way27326387-Q01` | Exactly **13 desk assets**, ground floor. Typed count fixture. |
| Easy | `osm-way22744230-Q06` | Same-floor core route **27.93 m**; preserve selected transitions. |
| Easy | `osm-way360544293-H01` | Largest `generic_room`: **Edeka, 129.93 m²**; display name differs from type. |
| Medium | `osm-way27326387-H08` | Centroid/elevation XYZ distance **9.30 m**; floor gap and actual elevation. |
| Medium | `osm-way27326387-H05` | Above E11 → **Generic room 114A** by polygon overlap, not nearest-centre or stairwell. |
| Medium | `osm-way22744230-H08` | **6** same-floor eligible wall neighbours; adjacency independent of doors. |
| Medium | `osm-way27326387-Q05` | `reachable:false` for step-free basement→floor-1 route; assert no route is presented. |
| Medium | `osm-way360544293-Q05` | **283.89 m** local route and an explicit outside discontinuity between floors. Renderer needs a separate assertion. |
| Hard | `osm-way27917482-H02` | Sum all **250** matching polygons → **4925.97 m²**; detect truncated-page computation. |
| Hard | `osm-way360544293-H03` | Nearest chair pickup room **F0-S010**, target **F0-S014**, total **163.96 m**, 53 assets/22 candidate rooms. |
| Hard | `osm-way22744230-H03` | Close **V07**, step-free count **30 floor-2 rooms**; independent map per test. |
| Hard | `osm-way27917482-H08` | Hypothetical corridor door: **6** improved floor-3 rooms; assert midpoint and state/file immutability in addition to final count. |
| Hard | `osm-way27917482-H09` | Hypothetical room door: **2** improved basement rooms; tolerant shared-wall geometry, downward effect, strict threshold. |
| Hard | `osm-way27917482-Q09` | Natural text must surface **three same-floor candidates**. A separate labelled-ID route fixture expects **154.82 m** after closing V01; do not mark clarification as a routing failure. |
| Hard | `osm-way27917482-Q10` | Ordered floor-3→ground→floor-3 tour: **107.24 + 83.99 = 191.23 m**; retain legs and do not draw a spurious same-floor segment across a discontinuity. |

Additional synthetic regressions are justified for gap-spanning stacked lookup, no overlap, width equality, unreachable→reachable what-if semantics and stale-route invalidation; those are **not** additional observed question kinds or verified expectations in these OSM labels.

## Verification performed for this review

Read all eight question files, source building JSON, README sections 3–4/6, BEN/MAP/QA backlog items, current map/tools/evaluator/adapter and route renderer. Parsed 66 annotations and checked per-kind/subtype/tier totals. Offline Shapely calculations confirmed the labelled winner for all nine stacking questions and exposed the door-contact geometry above. Direct graph diagnostics reproduced the 30-room outage count and showed current insertion also yields the 6/2 what-if counts. Direct closure routes measured the three duplicate-start alternatives. These diagnostics inspect core computations only: no claim is made about live scored accuracy, complete UI verification or Synera automatic route compliance.
