# Feature shortlist

`final_agent/agent.py` retains the existing draft with appended completion-evidence
rules and use cases. The larger proposed capabilities below remain unimplemented;
prompt instructions do not supply missing tools or application state.
[BACKLOG.md](BACKLOG.md) owns task priorities and status.

[IMPLEMENTATION_HANDOFF.md](IMPLEMENTATION_HANDOFF.md) expands the requested
features into tool contracts, one Sonnet implementation agent per feature and
independent verification gates. These remain planned capabilities; the handoff
does not implement them.

[TASK_TARGET_OBJECT_HANDOFF.md](TASK_TARGET_OBJECT_HANDOFF.md) specifies typed
requests, follow-up patches, session context and application-owned completion
(L1-06). The appended prompt examples explain evidence and partial failures;
the classes/controller and live interpretation checks remain outstanding.

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

## Implementation needed before expanding prompt claims

| Capability | Required change | Existing tasks |
|---|---|---|
| Navigation landmarks and turn directions | Add `find_navigation_landmarks` with an inner candidate radius, outer same-type ambiguity count and minimum footprint area; integrate route-aware selection and heading/turn geometry. Asset proximity alone does not prove visibility. The tool does not exist yet. | L2-01, L2-06; MAP-02–03 |
| Larger destination landmarks | Show and describe nearby named rooms such as a canteen/Mensa; require geometric adjacency for “next to” and use “near” for proximity alone. | L1-05; L2-06 |
| Route maps and locate highlights | Preserve selected openings/connectors; render the computed path and selected room/asset. | MAP-02–03; L1-01–02 |
| Closure rerouting | Invalidate old routes after edits and failed searches; recompute before showing a route. | MAP-04; L2-02 |
| Reliable edits | Validate doors and make save failures transactional; support review/cancel/undo. | MAP-05–06; L4-04 |
| Editing layout | Add tools to edit room boundaries, names/types, doors and connections; validate geometry, preserve IDs/metadata, save changes and invalidate affected routes/indexes. Support preview/cancel/undo. | MAP-04–06; L4-03–05 |
| Furniture changes | Add typed asset add/move/remove tools, persistence and index invalidation. Current tools only search assets. | EXT-01, if selected |
| Width and delivery constraints | Enforce opening widths, entry identity and constrained reachability in deterministic tools. | MAP-08; BEN-06–07 |
| Nearest destinations and tours | Compare constrained route distances for nearest selection; preserve requested tour order. Ordered `via` exists; optimal stop ordering does not. | BEN-08; L2-03 |
| Shortest tour in any order | Add the requested `find_best_tour(start, stops, destination, step_free)` tool: compute constrained pairwise shortest paths, optimize stop order and return the sequence, per-leg distances, directions and total distance. Reorder only when the user permits it; optimize exactly up to 10 intermediate stops, reject larger requests clearly and keep previews from replacing the active route. | L2-05 (requested) |
| Complete search and room inspection | Add page/page-size controls to text/spatial search, exact type filters, `list_spaces` and full `inspect_space` results; aggregates use every matching record. | MAP-07 |
| Reachable-room inventory | Add `reachable_rooms` with one constrained traversal, entry validation, explicit destination eligibility, a count and the counted IDs. | MAP-08; BEN-06–07 |
| What-if analysis | Simulate on isolated state without saving or altering the active map. | BEN-09; MAP-06 |
| Benchmark facts | Add exact enumeration, geometry and aggregation tools for all nine question kinds; never count a truncated search page. | MAP-07–08; BEN-01–09 |
| More buildings and new plans | Add building selection, walkway routing, calibrated plan ingestion and validated export. | L3-02–03; L4-01–06 |

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
