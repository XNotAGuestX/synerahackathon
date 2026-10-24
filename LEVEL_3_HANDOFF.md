# Level 3 handoff — floors, buildings and walkways

Prepared **25 October 2026** from the [codebase audit](CODEBASE_AUDIT.md).
Implement **L3-01–03** in [BACKLOG.md](BACKLOG.md), following [AGENTS.md](AGENTS.md)
and the current kit 1.1.0 rules in [README.md](README.md).
This is an implementation specification; it does not claim these gaps are fixed.
Coordinate imported-building validation/replacement with [Level 4](LEVEL_4_HANDOFF.md).

## Outcome and current foundation

A person can locate a room in either of two loaded buildings, retain the intended
building across follow-ups, and follow one constrained route through floors,
selected entrances and an explicit walkway. Closures produce a valid alternative
or an honest unreachable result; reopening can recover the requested journey.

Existing single-building routing already handles elevations, parallel doors and
stairs/lifts, direct multi-floor lift rides, widths, closures, selected route
identities, ordered stops and per-floor directions. Preserve it. Reuse the PNG
renderer, atomic JSON saves and query-only analyses for the missing campus workflow.

| Backlog item | Smallest completion gate |
| --- | --- |
| L3-01 | Every visited floor, including connector-only endpoints, has correct route/handoff output. |
| L3-02 | Two buildings coexist; duplicate room numbers and local IDs cannot mix state or geometry. |
| L3-03 | Deterministic constrained routing chooses indoor legs and walkways together and displays their handoffs. |

The separate frontend track owns the interactive surface.
Deliver backend/tool/artifact contracts and coordinate integration with that owner.
The level still needs verification through the actual surface before completion.

## Boundaries and ownership

- Keep conversation/session interpretation in [agent.py](final_agent/agent.py),
  typed wrappers in [tools.py](final_agent/tools.py), geometry/routing in
  [building_map.py](final_agent/building_map.py), persistence in
  [storage.py](final_agent/storage.py), and rendering in [viewer.py](final_agent/viewer.py).
- Use plain functions, existing dictionaries and small dataclasses. A small campus
  orchestrator is acceptable if multi-map ownership needs a separate module.
  Reuse local graph construction and path reconstruction; keep one routing engine.
- Keep source building JSON, IDs, unknown fields, elevations and attribution.
  Put building registrations and walkway records in a small local campus manifest.
- Keep benchmark questions isolated in their current single-building adapter.
  Kit 1.1.0 forbids outside shortcuts: never add a shared zero-cost outside node,
  reinterpret entrances as connected, or revive the old 1.0.0 outside semantics.
- Campus travel is an explicit application model. Label its total and retain
  `kit-1.1.0` on indoor costs; do not claim an announced Sunday output schema.

## Slice 1 — repair multi-floor output, L3-01

Fix visited-floor discovery in `viewer.route_floor_ids`: walking polylines alone
omit connector endpoints. Use route nodes, stops, floor segments and handoffs.
Include a floor even when its visit has no horizontal walking line. Keep separate
visits and disconnected segments separate; draw no invented connecting line.

Reproduce audit F2 before fixing: load `data/dev/proc-campus-dev-002`, then route
`proc-campus-dev-002-F0-S005` → `proc-campus-dev-002-F3-S005` with
`step_free=True`. The audited result was **26.4 m**, two lift handoffs, but
`show_route` returned `images=[]`, `floor_levels=[]`. After the fix it must
render both endpoint floors and identify the same selected lift.
Retain normal/step-free routes, closed-lift failures and negative/gapped levels.

## Slice 2 — registry and explicit session identity, L3-02

Register maps by unique `building_id`, display name, source/snapshot path and
current revision. Load each into its own `BuildingMap`; keep closures, selections,
walk caches and spatial indexes scoped to that map.
Never merge source dictionaries merely because their local IDs look unique today.
Existing tool closures and cached overview bind one map; dispatch/rebind them to
the validated scope and refresh overview when selection or map revision changes.

Use a scoped reference carrying `building_id`, `kind` and `element_id`.
Retain original local room/asset/opening/connector IDs; assets also identify their
containing space. Internal graph keys may be `(building_id, local_node_id)`.
Reject duplicate registry IDs and unknown buildings; repeated local IDs are valid
across buildings. Resolve names across kinds and buildings before choosing an ID.

Store selected building, confirmed current location and accessibility preferences
as explicit session state. Selecting a building for browsing does not move the
person or change a route destination. A cross-building destination keeps its own
building identity. Follow-ups retain resolved endpoints, ordered stops and
constraints; ask one targeted clarification when several buildings remain plausible.

Give snapshots and images distinct building/session paths; include route/revision
identity in artifact metadata. Two buildings or sessions must never replace each
other's `building_edited.json` or `route_0.png`. Resume the explicitly selected
saved version; never silently choose an unrelated latest file.

## Slice 3 — explicit walkway records, L3-03

Each link has a unique ID/name, two scoped entrance endpoints, measured positive
`length_m`, usable `width_m`, explicit `step_free`, closure state and revision.
An endpoint is `{building_id, opening_id}`; it must resolve to an actual entrance
with one indoor space. Preserve parallel walkways and their individual identities.
The first slice may use undirected walkways; reject unsupported directionality.

Validate endpoints, finite metre lengths/widths and flags before publishing a link.
Width equality passes. Enforce width, step-free and closures on both actual
entrances and the walkway. A starting-room convention from benchmark reachability
must not bypass a physical campus entrance constraint.
An invalid/dangling entrance reference makes that link unusable with a repair message.

Building XY coordinates remain local. For the minimum implementation, a walkway
may be a labelled abstract link with a supplied measured distance between two
entrance views. Never calculate that distance by subtracting unrelated local XY.
If a shared campus map is added, require an explicit validated transform per
building; retain source coordinates and distinguish schematic from calibrated views.
Shared floors within one imported building use Level 4's calibrated frame/elevations.

## Slice 4 — connected shortest routing and recovery

Compose scoped local graphs with explicit walkway edges between their opening
nodes, or construct a small portal graph from exact local opening-to-opening
distances. Use the existing filtered graph and selected-edge reconstruction.
Retain kit's disclosed fallback limitation; a fallback-only indoor segment must
be flagged as unverified geometry and never drawn as a valid walk.
Find the shortest total permitted journey over all entrance/link choices;
choosing the nearest exit greedily does not establish the optimum.

**Portal costs are mandatory.** Current `compute_route(..., entrance=...)`
validates entry but does not add entrance-to-room walking distance. Summing
room-centre routes and link lengths would omit or duplicate access walks.
Use the actual selected door nodes for exit, entry and transit legs, preserving
their kit landing/door-to-door costs. A small shared reconstruction helper is
appropriate; do not reroute those legs through room anchors for display.

Return ordered indoor and walkway legs, selected entrances/connectors, scoped
nodes/spaces/edges, leg metres, cumulative metres, total metres and floor segments.
Keep unrounded computation and deterministic tie breaks; round tool presentation.
An asset endpoint still means its containing room under the existing route model.
Preserve ordered via stops when composing a campus journey; omit no requested leg.

Pin all used building revisions and the link-state revision on a result.
After a relevant map/link edit, invalidate the whole affected campus result and
recompute the requested journey with the same endpoints/stops/constraints.
Keep the validated request if recomputation is unreachable; clear its old displayed
path and retain an actionable reason. Reopening can reactivate that request.
Do not activate read-only comparisons or hypothetical closures.

Level 4 registers/replaces only a validated building revision. On replacement,
recheck entrance references, invalidate affected routes/indexes and expose dangling
links for review. Preserve atomic save/rollback behavior; failure must leave the
old usable registration/state or an explicitly recoverable unsaved result.

## Minimum tool/result and frontend contract

Proposed names are an internal contract, not existing registered tools:

| Operation | Required behavior/result |
| --- | --- |
| `list_buildings()` | IDs, names, floors, revisions and selected-building identity. |
| `select_building(building_id)` | Validated session selection; no location/route mutation. |
| Scoped existing search/inspect/locate/route | Optional building ID uses explicit session scope; outputs always carry building/floor/element identity. |
| `find_campus_route(start, destination, via, step_free, min_width_m)` | Scoped references; reachable result with ordered legs, cost model, revisions and constraints, or explicit unreachable reason. |
| Scoped closure/update | Exact building element or walkway ID; saved state and recomputed result/error. |
| Route display | Exact route/revision identity, ordered view descriptors and artifact paths, including building/floor, connector and walkway handoffs. |

The frontend consumes computed geometry/identities, never reconstructs shortest
paths or chooses its own doors. Each view has `building_id`, `floor_id`, floor
level, route ID/revisions and selected element IDs. Preserve visit order even when
several legs use the same floor image. Show the selected departure entrance,
walkway name/distance and arrival entrance between indoor floor views.
Return all visited floor views, including connector-only visits, plus a schematic
link descriptor when no common campus coordinate frame exists.
Distinguish calculation, generated artifact and confirmed on-screen display.
Reject/clear stale route views and show unreachable/loading/render/save failures.

## Focused verification and acceptance

Reuse existing route/map/storage fixtures; add only regressions for the new
boundaries. Check: connector-only floors; parallel stairs/lifts; negative/gapped
levels; repeated IDs/room refs across two maps; explicit building follow-ups;
portal access costs; globally shorter non-nearest exit; multiple/parallel links;
exact width threshold; stepped/closed entrance or link; disconnected buildings;
unreachable → reopen recovery; failed save; building replacement/dangling link;
two simultaneous session outputs; preview and benchmark isolation.

Proposed offline commands after implementation, from the repository root:

~~~bash
PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest discover -s tests -p 'test_routing.py' -v
PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest discover -s tests -p 'test_map_display.py' -v
PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest discover -s tests -p 'test_storage.py' -v
~~~

Run the new focused campus regression module under the same discovery convention;
document its actual filename. Inspect generated floor/link views visually.
The audit's **24 October** 202 tests (199 pass, 3 skip), 369/369 warm-up oracle and
197 reachable dev-route geometry checks are prior evidence, not Level 3 acceptance.
Run a small changed-route dev check before broadening if local routing changes.
Live conversation requires configured credentials and a recorded actual result.

Script the real surface: select Building A; resolve a room number also present in
B; locate it; request a route to an upstairs target explicitly in B; add “no stairs”
and a width; inspect indoor → selected exit → walkway → entry → lift → target;
close its link or lift; show the valid alternative or cleared unreachable view;
retry while unreachable; reopen and recover; change the target using a follow-up.
Reload chosen saved state and confirm a second session did not overwrite it.
Record tool inputs/results, selected identities, displayed views and limitations.

## Delivery checklist

- [ ] L3-01–03 gates pass through the separate frontend integration.
- [ ] Selected portal costs, every leg and total agree with the deterministic path.
- [ ] Unreachable/closure/reopen, building identity and output isolation are verified.
- [ ] Kit 1.1.0 single-building behavior and benchmark isolation remain intact.
- [ ] Level 4 replacement handoff, supported link/frame limitations and launch
  command are documented; README/BACKLOG status cites only actual verification.
- [ ] Deliver focused code/tests, a small two-building/link demo fixture with
  provenance, useful artifacts and a concise verification report; remove registry entry.
