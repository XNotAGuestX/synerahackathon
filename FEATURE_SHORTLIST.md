# Feature shortlist

Status, 24 October 2026: the capabilities marked **Implemented** below have a
registered tool in `final_agent/tools.py` and are verified at component level
without credentials (see [BENCHMARK.md](BENCHMARK.md)); the revised system prompt in
`final_agent/agent.py` explains them, but no live prompt evaluation was run. The
rest, including mobile location, layout editing, furniture changes, multiple
buildings, plan ingestion, the Synera route model and the visual/web surface (the
team's separate frontend track), is **not implemented**. [BACKLOG.md](BACKLOG.md)
owns task priorities and status.

[IMPLEMENTATION_HANDOFF.md](IMPLEMENTATION_HANDOFF.md) holds the tool contracts and
verification gates for these features; F14 (map highlights, destination context) is
pending at the time of writing.

## Location updates when the mobile app is implemented

Current proposed rule:

> A destination is not the user's current location. Update location only when
> the user confirms it.

Replace it once the mobile app supplies reliable location events:

> Update the user's current location automatically from mobile location events.
> A requested destination alone does not update location. If tracking is unavailable
> or uncertain, use the last confirmed location and ask when needed for routing.

Implement this with **L1-01 / L1-04**, not just a prompt change:

- Keep current location separate from destination in building/session state.
- Include building, floor, position or resolved space, timestamp and accuracy in
  location events. Reject events from other buildings/sessions and stale events.
- Resolve positions through deterministic map tools. Ask when the floor or room
  remains ambiguous; do not infer arrival from route generation.
- Use accepted location updates as the start of subsequent routes. Recompute an
  active route when movement requires rerouting, retaining accessibility needs.
- Verify movement and arrival without chat confirmation, plus unavailable,
  uncertain, stale and wrong-building events. Keep explicit confirmation as the
  fallback for the CLI and sessions without tracking.

## Capabilities and implementation status

| Capability | Status and tool | Existing tasks |
|---|---|---|
| Navigation landmarks and turn directions | **Implemented (tool)**: `find_navigation_landmarks` (inner radius, outer same-type ambiguity count, minimum footprint area, `is_unambiguous`). Not implemented: heading/turn geometry (no left/right) and route-integrated cue selection, which stays prompt-driven. Nearby does not prove visibility. | L2-01, L2-06; MAP-02–03 |
| Larger destination landmarks | **Pending (F14)**: `describe_destination_context` and map display. “Next to” needs a shared wall of at least 1 m; proximity alone is “near”. | L1-05; L2-06 |
| Route maps and locate highlights | **Partly implemented**: `show_route` draws the computed path through the selected openings/connectors. Locate highlights and markers are pending (F14: `show_location`); a visual chat/web surface belongs to the team's frontend track. | MAP-02–03; L1-01–02 |
| Closure rerouting | **Implemented**: `set_closed` / `add_door` clear stale routes and recompute the active route with its constraints (`active_route` / `active_route_error`). | MAP-04; L2-02 |
| Reliable edits | **Partly implemented**: `add_door` validates the pair and places the door at the shared-wall midpoint; a failed save rolls the edit back. Preview/cancel/undo are not implemented. | MAP-05–06; L4-04 |
| Editing layout | **Not implemented**: tools to edit room boundaries, names/types, doors and connections with validation, preview/cancel/undo. | MAP-04–06; L4-03–05 |
| Furniture changes | **Not implemented**: typed asset add/move/remove tools, persistence and index invalidation. Current tools only search assets. | EXT-01, if selected |
| Width and delivery constraints | **Implemented**: `min_width_m` and `entrance` on `find_route`, `plan_errand`, `find_best_tour` and `reachable_rooms` (width equality passes). | MAP-08; BEN-06–07 |
| Nearest destinations and tours | **Implemented**: `plan_errand` (nearest pickup by constrained route distance, then the largest destination) and `find_route` with ordered `via`. | BEN-08; L2-03 |
| Shortest tour in any order | **Implemented**: `find_best_tour` (exact up to 10 stops, fixed endpoints, `activate=False` preview that keeps the active route). | L2-05 |
| Complete search and room inspection | **Implemented**: paged `search_building` / `spatial_search` with exact `matches`, exact type filters, `list_spaces` and `inspect_space`. | MAP-07 |
| Reachable-room inventory | **Implemented**: `reachable_rooms` (one constrained traversal, entry validation, eligibility rules, count and IDs). | MAP-08; BEN-06–07 |
| What-if analysis | **Implemented**: `analyze_what_if_door` simulates on a temporary copy; nothing is saved or changed. | BEN-09; MAP-06 |
| Benchmark facts | **Implemented**: `find_largest_room`, `sum_floor_area`, `straight_line_distance_3d`, `find_stacked_room`, `count_shared_walls` plus the tools above cover all nine scored kinds. | MAP-07–08; BEN-01–09 |
| More buildings and new plans | **Not implemented**: building selection, walkway routing, calibrated plan ingestion and validated export. | L3-02–03; L4-01–06 |
| Synera route model | **Not implemented**: wall-respecting paths, height costs and forklift/production-bay rules; distances use the local kit model. | README route-scoring clarification |

Keep the local anchor-based route model distinct from the Synera automatic route
check described in the [README](README.md#route-scoring-clarification-synera).
Wall-respecting paths, height costs and forklift/production-bay rules require
deterministic routing changes, not prompt instructions alone.

## System prompt note: Building changes

Retain this section as a reference for the editing workflow:

```text
# Building changes
- Resolve affected elements before editing.
- Use set_closed for closures/reopenings and add_door for supported door additions.
- Apply other changes only if an appropriate tool exists.
- Confirm only successful changes; report edit or save failures.
- After relevant edits, recompute the active route with its original constraints.
- For hypothetical changes, use isolated simulation. Never persist them.
  If simulation is unavailable, state the limitation.
```

## Verification before enabling new behavior

Run the relevant focused tests and the interaction script in **L2-04**. Check
benchmark formatting with the unchanged scorer (**QA-02**), then measure live
interpretation (**QA-03**) when credentials are configured. Oracle warm-up results
do not verify prompt behavior. No live prompt evaluation was run for this shortlist.
