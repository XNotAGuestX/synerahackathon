# Question types and implementation coverage

Status audits the exposed `final_agent` tools. Yes means a resolved-input local-model primitive exists; it does not claim live conversational accuracy or complete rendering. Partial count support is not a complete exact inventory tool. All nine scored kinds lack a complete exposed solution.

Runnable selection targets 5 distinct questions per kind, preserving all original cases. Two kinds exhaust the labelled train/dev supply below that target. The full ledger retains the original dev distribution plus three explicitly marked train supplements; its raw counts are not balanced. See [selection balance](tests.md#selection-balance).

| Type | Questions / buildings | Runnable / labelled available | Implemented | Existing tool | Missing tool or work | Expected result |
|---|---:|---:|---|---|---|---|
| `locate` (warm-up) | 52 / 18 | 5 / 553 | Yes, tool core | search_building | None for resolved asset lookup; interactive highlight still missing | Asset ID, containing room, floor; fixture also records XY |
| `count` (warm-up) | 20 / 20 | 5 / 239 | Partial | search_building | query_inventory: exact asset type + floor + complete count | Exact number of assets, excluding matching room names and other types |
| `route` (warm-up) | 60 / 20 | 5 / 720 | Yes, local model | find_route | None for local length/space path; retain selected openings/connectors for route validation | Reachable route: length_m, ordered spaces and actual opening/connector path |
| `route_step_free` (warm-up) | 20 / 20 | 5 / 240 | Yes, local model | find_route(step_free=True) | None for resolved-input step-free search; explicit unreachable reply still needs live verification | Constrained route OR explicit unreachable; same floor does not imply reachable |
| `route_with_closure` (warm-up) | 15 / 15 | 5 / 138 | Yes, tool core | set_closed + find_route | None for isolated resolved-input closure routing; stale-route invalidation remains open | Route avoiding closed connector OR explicit unreachable |
| `tour` (warm-up) | 20 / 20 | 5 / 240 | Yes, local model | find_route(via=[...]) | None for fixed-order total; expose leg boundaries and selected elements | Ordered stop visits, per-leg paths/lengths in fixture, total distance |
| `largest_room` (scored) | 15 / 15 | 5 / 96 | No | No area tool | room_area_summary | Answer: selected room first, area within 5% |
| `floor_area_total` (scored) | 18 / 18 | 5 / 181 | No | No area aggregation | room_area_summary | Answer: exactly one number; total polygon area within 5% |
| `straight_line_3d` (scored) | 10 / 10 | 5 / 30 | No | No centroid/elevation distance tool | straight_line_distance_3d | Answer: exactly one number; Euclidean XYZ metres within 2% |
| `room_stacked` (scored) | 9 / 3 | 5 / 26 | No | spatial_search is only a point/radius query | stacked_room | Answer: room with greatest overlap on next higher/lower available floor |
| `shared_walls_count` (scored) | 13 / 13 | 5 / 143 | No | No boundary adjacency tool | shared_wall_neighbors | Answer: exact eligible-neighbour count; >=1 m within 0.35 m |
| `wide_delivery_count` (scored) | 11 / 11 | 5 / 80 | No | Step-free route exists, width filtering/count do not | reachable_rooms (minimum width + step-free) | Answer: exact reachable type=room count on target floor, including start if eligible |
| `step_free_reachable_count` (scored) | 2 / 2 | 2 / 2 | No | Closure and pairwise route primitives exist | reachable_rooms (isolated closure + step-free) | Answer: exact reachable room count after named closure |
| `errand` (scored) | 14 / 14 | 5 / 93 | No | find_route(via=...) cannot select pickup/destination | query_inventory + room_area_summary + plan_errand | Answer: one total distance, nearest pickup first; within max(1%, 1 m) |
| `what_if_door` (scored) | 4 / 2 | 4 / 4 | No | add_door persists edits and has no impact analysis | simulate_door_exit_improvement + shared-wall midpoint | Answer: exact other-floor room count with exit-distance improvement strictly >1 m |

Evidence: [full question ledger](questions.csv), [selected runnable cases](tests.md), [tool contracts](tools_needed.md), and the three independent [family reviews](reviews/). `final_agent/tools.py` exposes seven tools; the implementation assessment is based on code and offline probes, not the older README baseline alone.
