# Tools needed for the audited requests

This is a proposed implementation plan for the current `final_agent` package, not an organizer API or a list of tools already available. Keep computation in `building_map.py`, thin agent interfaces in `tools.py`, and answer formatting in the conversation/benchmark layer. The existing seven tools provide search, pairwise routes, closure edits, door edits and rendering; they do not solve any complete scored kind.

The smallest coherent addition is **eight deterministic capabilities**, sharing exact inventory, polygon geometry and constrained graph traversals. Function names below are suggestions. Existing `find_route` remains the route/tour tool.

| Priority | Proposed tool | Inputs | Result and correctness requirements | Question kinds / backlog |
|---|---|---|---|---|
| P0 | `query_inventory` | Entity kind (`asset` or `space`), exact asset type or `room_type`, optional floor ID | Complete count and matching IDs, or pagination with an explicit total. Asset results include containing space; expose exact geometry/elevation/width facts through focused inspection when needed. Resolve phrases such as “seating row” to the enum before counting. Do not combine matching room names and assets. | `count`; candidate sets for every scored kind; MAP-07 |
| P0 | `room_area_summary` | Floor ID, exact `room_type` | Matching count, total polygon area, largest space ID/name and its area. Explicit room-type filters can include `type=hall` spaces, including warehouse zones and lobbies. Use all candidates, not the search page. | `largest_room`, `floor_area_total`, errand destination; BEN-01/02 |
| P0 | `straight_line_distance_3d` | Two resolved space IDs | Polygon centroids, each floor's actual `elevation_m`, Euclidean XYZ distance in metres. Route representative points, level numbers and clear `height_m` are different quantities. | `straight_line_3d`; BEN-03 |
| P0 | `stacked_room` | Source space ID, `above` or `below` | Next higher/lower available floor in the shared XY frame, maximum positive overlap, selected ID/name and overlap area. Handle no floor, no overlap and ties explicitly; those negative outcomes are not specified by the nine selected labels. | `room_stacked`; BEN-04 |
| P0 | `shared_wall_neighbors` | Source space ID; defaults 1 m minimum boundary length, 0.35 m wall gap | Eligible same-floor neighbour IDs, qualifying lengths and count. Include factory hall bays; exclude circulation and outdoor spaces. Do not equate door connectivity, polygon distance, or a corner touch with a qualifying wall. A shared internal helper should identify the contact segment and midpoint for door simulation. | `shared_walls_count`, door placement; BEN-05, MAP-05 |
| P0 | `reachable_rooms` | Resolved start, target floor ID, step-free flag, optional minimum opening width, optional closed IDs and explicit entrance ID when supplied | Exact reachable eligible-room IDs/count and applied constraints. Selected width/outage labels count `type=room`, not halls, corridors, stairs, lifts or outdoor spaces. Include start when it is eligible. Apply width to every opening, allow equality, retain parallel connections and honor closures/step flags. Use one graph traversal, rather than one route call per room. | `wide_delivery_count`, `step_free_reachable_count`; BEN-06/07, MAP-08 |
| P0 | `plan_errand` | Start, exact asset type, destination floor ID and `room_type`, explicitly requested route constraints | Deduplicate asset-containing spaces, including outdoor balconies; choose nearest reachable pickup by **start-to-pickup** route distance, then largest destination. Return pickup/destination IDs, selection evidence, both legs and total. Stairs are expressly allowed in all 14 selected errands. This is a sequential selection task, not best-tour optimization. | `errand`; BEN-08 |
| P0 | `simulate_door_exit_improvement` | Two same-floor spaces, target floor ID, default strict improvement threshold 1 m | Clone current state, validate shared wall, insert door at its midpoint, compare before/after shortest distances to nearest entrance for eligible target-floor rooms. Return count and changed IDs/distances. Preserve original map, closures, route/index state and files. Evaluate exact distances before rounding. Report disconnected-case semantics explicitly until confirmed by the organizer/labels. | `what_if_door`; BEN-09, MAP-05/06 |

The signatures can use existing space references, resolved to stable building-local IDs at the boundary. Avoid creating separate services, registries or a generic query language for these operations.

## Shared routing and result work

These are changes to the existing route/tool result, rather than eight more agent-facing tools:

- Reuse the local `MultiGraph` and add width filtering to the shared graph operation. Keep constraints identical between reachability, nearest pickup and pairwise routing. Validate references, widths and floor IDs at the boundary.
- Retain ordered graph nodes, selected opening/connector IDs, outside transitions, ordered stops and per-leg boundaries/lengths. Current `RouteResult` drops the selected element trace and leg structure. Return an explicit unreachable outcome/error, never a made-up distance of zero.
- Clear stale routes after relevant edits or failed route attempts; ensure failed persistence either rolls back mutation or reports a recoverable unsaved state. Existing atomic file replacement does not roll back in-memory changes.
- Produce final answer lines from actual computed results. Numeric scored answers have exactly one number. Room answers name the chosen room first; `largest_room` also includes area. Keep the official scorer unchanged.
- Return enough context to distinguish duplicate names on the **same floor**. `osm-way27917482-Q09` needs clarification among three spaces; no deterministic tool can infer which labelled start the user intended from that text alone.

The current system prompt mentions `find_best_tour`, but no such tool is registered. No selected tour permits reordering, so implementing that optimizer is unnecessary for these fixtures. Preserve requested order with `find_route(..., via=...)`.

## Routing rules beyond these local question files

Synera's clarification already appears in the root README; these are additional required route behaviors, **not newly discovered kinds in this sample**. They have no supplied local expected-distance labels for the newer model:

| Request / validation rule | Necessary work |
|---|---|
| Walking around room corners | In-space door-to-door paths with about 0.15 m wall clearance; asset geometry is not an obstacle. |
| Stairs and lifts with physical height costs | Stairs cost 2 m per metre climbed; lift costs 15 m plus height difference. Use floor elevations. |
| Forklift route | Restrict to forklift aisles and qualifying openings at least 3 m wide; exclude pedestrian walkways. Do not interpret “forklift charging station” as a request for this profile. |
| Delivery to production bay | Allow the destination bay but reject transit through other production bays as shortcuts. |
| Route to equipment | End in the containing room/bay, rather than inventing an obstacle-avoiding route to an exact asset point. |
| Automatic route answer | Preserve an ordered valid space sequence; validity and best-length ratio matter. Reporting only a distance is insufficient. |

Expose a clearly identified routing model/profile if adding these capabilities. Keep the local anchor graph, 12 m/floor stairs, 15 + 6 m/floor lifts and zero-cost common outside node for local label compatibility. The Sunday file schema and release time remain organizer-dependent; this analysis does not introduce one.

## Suggested delivery order

1. Exact inventory and area summary: **33/93** selected scored questions, plus robust warm-up counts and errand prerequisites.
2. Centroid distance and overlap: **19/93** more selected scored questions.
3. Shared-wall geometry and constrained reachability: **25/93** more, including the only lift-outage count.
4. Compose the **14 errands**, then the **2 what-if** analyses. Reuse the prior computations instead of adding a second geometry or graph model.

These counts describe the selected sample, not public-test weights or a measured agent score. Route validity, ambiguity and visible interaction remain product requirements alongside scored coverage.
