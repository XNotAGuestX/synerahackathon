# Feature implementation handoff

Implement the requested features for **Talk to Your Building**. Stay within the
hackathon: working deterministic tools, a usable 2D map and a short demonstrable
conversation. Read [AGENTS.md](AGENTS.md), the [README](README.md) and
[BACKLOG.md](BACKLOG.md) first. The backlog owns completion status; this document
defines the implementation contracts and agent handoffs for this feature set.

**Status, 24 October 2026:** F01–F14 are implemented, each by a Claude Sonnet 5.5
agent on an isolated worktree branch, then reviewed, merged and independently
re-verified by the coordinator. By user decision, F14's local web UI was removed
from scope: the team's separate frontend track owns the interactive surface, and
F14 delivers the per-floor PNG renderer plus `show_location`,
`show_route(landmark_ids)` and `describe_destination_context`. **F15 was
implemented and then reverted at the user's request; it is pending again.**
[F15_HANDOFF.md](F15_HANDOFF.md) records its scope, the reverted implementation
(`git show 553e25f:<path>`) and everything learned. Because F15 owned the
documentation update, README/BACKLOG/FEATURE_SHORTLIST currently describe the
pre-implementation state. Verified without API credentials: 173
unit/integration tests (incl. 12 hull tests); 369/369 oracle warm-up; labelled
component checks for all nine scored kinds, dev 138/138 and train 517/517; 45/45
`bench_analsysis` representatives; live sweeps of every tool over all 280
buildings with no unexpected exception; every entry point stops with one clear
message (no traceback) when credentials are missing. No live API evaluation was
possible (no credentials). The original specification below is unchanged.

## 1. Coordinator instructions: Sonnet agents, then verification

Use **one Claude Sonnet implementation agent for each feature F01–F15 below**.
Select Sonnet explicitly using the execution environment's available model
selection. Do not silently substitute another model or claim a Sonnet run that
did not happen. The model used for coding agents is separate from the model
configured inside the building application.

The coordinator owns integration and verification. For each feature:

1. Read the current diff; preserve teammates' changes. Give the Sonnet agent the
   relevant feature section, backlog IDs, agreed interfaces and file ownership.
2. Ask it to deliver the smallest complete input → computation → tool → visible
   result slice, reusing existing checks and adding only minimal regressions for
   meaningful correctness gaps. Keep test-writing time/token use low; no new
   general test framework or exhaustive scaffolding.
3. Review its diff and independently run the relevant checks. Inspect actual
   geometry, paths, state changes and tool JSON, rather than accepting its report.
4. Integrate, fix failures and run the affected interaction before dispatching a
   dependent feature. Update the backlog and README only to the verified extent.

Parallel work is useful only with disjoint file ownership. Most features touch
`building_map.py` and `tools.py`; serialize those edits, or have agents prepare
isolated patches for coordinator integration. Never let agents overwrite each
other's shared-file work. Keep the existing tests green between slices.

Suggested order: **F01 → F02–F03 → F05–F07 → F08–F09 → F04 → F10–F12 →
F13 → F14 → F15**. Areas and 3D geometry provide early benchmark progress;
keep a usable locate/route/map slice moving alongside them. F15 final sign-off
follows all implemented features, even if its integration work starts earlier.

At preparation time the working tree already contained changes to
`final_agent/agent.py`, benchmark outputs and an untracked `bench_analsysis/`
directory. These belong to existing work. Reinspect before editing; do not reset,
delete or adopt them as verified results. The prompt already mentions
`find_best_tour`, although that tool is not registered.

The concurrently added [benchmark request analysis](bench_analsysis/README.md)
and [findings](bench_analsysis/new_request_types.md) provide reusable dev
fixtures and important per-operation eligibility distinctions. Treat them as
development evidence, not organizer announcements or production answer inputs.
Preserve that work and reuse its runner rather than rebuilding the same audit.

## 2. Enforce the existing project structure

| Location | Responsibility |
|---|---|
| `final_agent/agent.py` | Intent, clarification, conversation state and tool-backed explanations |
| `final_agent/tools.py` | Typed tool interfaces, JSON serialization and actionable `ToolError` results |
| `final_agent/building_map.py` | Deterministic search, geometry, route constraints, optimization and analysis |
| `final_agent/storage.py` | Atomic local persistence and derived per-floor spatial indexes |
| `final_agent/viewer.py` | Map rendering from computed route/selection data |
| `final_agent/benchmark.py` | Fresh map/conversation/output state per benchmark question |
| `tests/` | Focused regression and integration checks; small synthetic fixtures |
| `BACKLOG.md`, `README.md` | Task status, supported behavior, evidence and limitations |

Extend these modules with short typed methods and plain data structures. A small
route-result dataclass is appropriate. Avoid a new service, plugin system,
parallel application package or geometry framework. Reuse NetworkX, Shapely,
Matplotlib and the standard library. Add dependencies only for a concrete
requirement that existing dependencies cannot reasonably meet.

Keep `starter_agent/` unchanged and keep final imports package-local. Preserve
building IDs, unknown/custom fields, floor elevations and source/licence data.
Keep secrets, temporary images, caches and exploratory benchmark outputs out of
source changes. Retain deliberate demo/submission artifacts explicitly.

### Shared contracts

- Coordinates, lengths and widths use metres; areas use square metres. Reject
  NaN/infinity, invalid geometry, negative radii/widths and unknown floors/IDs.
- Tool wrappers remain thin. The model never computes inventory counts, polygon
  areas, shortest paths, landmark uniqueness or stop ordering itself.
- Resolve human references to IDs once. Results include IDs, names and floor
  identity; assets retain both their asset ID and containing space ID.
- Explicitly identify the route cost model. Keep `kit` as the compatibility
  default for existing local questions and warm-up tests. Do not quietly use
  Synera distances for kit labels or claim kit paths satisfy Synera geometry.
- Route tools share the same closures, step-free and minimum-width rules. Width
  equality passes. An explicitly selected entrance must itself satisfy them;
  starting inside its room must not bypass its inaccessible/narrow entry door.
- Computation used for comparison, inventory or simulation is read-only. It must
  not replace the active route, highlights, closures or persisted map.
- Expected failures become actionable errors or an explicit unreachable result.
  An empty inventory/page is a normal result. Do not relax constraints silently.
- Give deterministic tie breaks, normally by ID. Calculate with unrounded
  values; round only at presentation boundaries.

## 3. F01 — Faithful route results and safe route state

**Backlog:** MAP-01–06, MAP-08; foundation for L1/L2 and the new tools.

Retain the selected route's ordered graph nodes, selected edge keys and
opening/connector IDs, ordered spaces, leg boundaries, floor segments,
constraints, distance model, directions and unrounded length. A room sequence
alone cannot distinguish parallel doors or a stair from a lift. Preserve outside
and re-entry transitions explicitly. Keep existing `length_m`, `space_path` and
`steps` compatibility where practical.

Separate pure route calculation from assigning `last_route`. Pairwise tour
calculations, reachability, errand selection and what-if analysis use the pure
calculation. Activate only the route actually chosen for navigation. Clear an
old active route before a new activating attempt that can fail, and after any
relevant closure/edit. Store the active request's original endpoints and
constraints so the interaction can recompute it after changes.

Extend the common graph filtering with `min_width_m` and selected entrance
identity. Preserve kit representative-point/opening-node distances, parallel
edges, fixed per-floor vertical costs and outside semantics. Route failure must
identify the failed leg and retain every requested constraint.

Fix door placement/validation before F12: reject self-doors, cross-floor pairs,
corner contact, malformed/nonadjacent polygons and inappropriate duplicates;
place a new door at the shared-wall midpoint with an explicit width and unique
ID. Stage edits and save atomically; on failure restore the prior usable map or
report a recoverable unsaved state explicitly. A failed save must not look like
a successful persisted change.

**Verify:** parallel doors and stairs/lifts, closed start/destination, same-room
routes, repeated stops, width equality, inaccessible entrance, floor gaps,
outside/re-entry, failed route after success, midpoint placement and save
failure. The renderer must receive the same selected edges as the route tool.

## 4. F02 — Complete search, pagination and `list_spaces`

**Backlog:** MAP-07, L1-02. Implements the first image's enumeration request and
fixes the hard 15-result cap in both text and spatial tool wrappers.

Proposed public interfaces; retain existing positional arguments:

```python
search_building(query, floor_level=None, kind="all", room_type=None,
                asset_type=None, space_type=None, page=1, page_size=15)
spatial_search(x_m, y_m, floor_level, radius_m=0, kind="all",
               page=1, page_size=15)
list_spaces(floor_level=None, room_type=None, space_type=None,
            page=1, page_size=15)
```

Use **exact canonical filters**: `room_type` for a space's subtype, `space_type`
for its broad source `type` (`room`, `hall`, `outdoor`, circulation, etc.), and
`asset_type` for an asset's `type`. `kind` selects `space`, `asset` or `all`.
Incompatible filters are actionable errors, not silently ignored. Subtype/broad
space filters narrow results to spaces; an asset-type filter narrows to assets.
Return the broad `type` and the `room_type` separately for spaces. Keep fuzzy/name
matching in `query` separate from exact filtering. `list_spaces` enumerates
spaces completely, including an empty-query equivalent, without mixing in assets
or silently restricting all spaces to broad `type=room`. Normalize case/spacing
consistently; never treat `office` as a substring match for another exact type.

Return `matches` (full filtered count, retained for compatibility), `results`,
`page`, `page_size`, `total_pages`, `has_more` and `next_page` (`null` at the end).
Default to 15 per page; permit 1–100. Reject non-integer/nonpositive page values
and invalid page sizes. An out-of-range positive page returns an empty page and
the real count. Sort before slicing: text/enumeration by stable kind/floor/name/ID;
spatial results retain distance/kind/ID ordering. A map edit may change inventory,
so clients restart pagination after edits.

Internal aggregates operate on all filtered records, never on a page. Searching
must not silently select/highlight every match; F14 handles an explicit selection.

**Verify:** 0, 15, 16 and more than 30 matches; second/last/empty pages; different
page sizes; all IDs exactly once across pages; exact type versus query text;
negative floors; invalid arguments; resolving and highlighting an item on page 2.

## 5. F03 — `inspect_space`

**Backlog:** MAP-07. Implements the first image's complete room inspection.

```python
inspect_space(space)
```

Resolve the reference to one room. Return its complete original record under
`space` (including custom fields), computed polygon area, polygon/centroid,
floor record/elevation, closure state and connected openings/connectors. Opening
details include endpoints, position, width, step-free flag, kind and closure
state; connector details include kind, stops and accessibility. Include asset
count and IDs; page asset details through search if necessary.

Keep source fields separate from derived facts. Missing elevation is reported as
missing; computations requiring it fail clearly rather than inventing a height.

**Verify:** irregular polygon area, custom metadata, multiple doors, a vertical
connector, closed opening, asset reference resolving to its room and ambiguous
or unknown room names.

## 6. F04 — `reachable_rooms` and the two reachability question kinds

**Backlog:** MAP-08, BEN-06 (`wide_delivery_count`), BEN-07
(`step_free_reachable_count`). Implements the first image's traversal tool.

```python
reachable_rooms(start, floor_level=None, step_free=False, min_width_m=0,
                entrance=None, closed_elements=None, room_type=None)
```

Build one filtered graph and perform **one traversal**, rather than one
`find_route` call per candidate. `closed_elements` adds temporary closures to
the current ones for this query only. Validate entrance identity and eligibility
before traversal. If the question names only an entrance room with several
materially different entrances, resolve the ambiguity rather than choosing an
arbitrary door.

Return `count`, sorted `room_ids`, compact room identities, the applied
constraints/entry and the explicit destination-eligibility exclusions. Count
spaces once, never door/outside nodes. Traverse corridors/stairwells/lifts as
allowed without counting them as eligible rooms. Confirm the exact eligibility
rule against train/dev definitions; any additional exclusions must be justified
and tested. Existing dev analysis supports counting broad `type == "room"` for
delivery/reachability counts, excluding halls and outdoor spaces; verify both
question kinds before finalizing that rule. Include an eligible starting room.
Floor/type filters affect counted destinations, not intermediate traversal. A
valid start with no eligible destinations returns count zero; an invalid/closed
entrance reports why it cannot be used. Do not invent lift cabin widths when the
connector supplies none: verify the actual access openings and stated metadata.

**Verify:** narrow entry despite a wide interior route, exactly-at-threshold
width, inaccessible entrance, closed lift, alternative lift, no lift, closed
rooms, target-floor filtering and a temporary closure that leaves active state
and files unchanged. Cover BEN-07 despite its zero public-test examples.

## 7. F05 — `find_largest_room`

**Backlog:** BEN-01; depends on F02–F03.

```python
find_largest_room(room_type, floor_level)
```

Filter all spaces by exact room type and floor, compute polygon areas and return
the selected room first with `area_m2`, identity and candidate count. Resolve
ties deterministically. Empty matches are explicit. Do not rank by furniture
count, bounding-box area or search order. Do not globally require broad
`type=room`: an exactly requested lobby/warehouse subtype can be a hall.

**Verify:** concave polygons, more than 15 candidates, wrong-floor/type rooms,
ties and no matches. Score a reply naming the selected room before alternatives
and including its area; the official area tolerance is ±5%.

## 8. F06 — `sum_floor_area`

**Backlog:** BEN-02; depends on F02–F03.

```python
sum_floor_area(room_type, floor_level)
```

Sum actual polygon areas of every exactly matching space. Return `area_m2`,
`count` and included room IDs; empty matches return zero. This is the sum of room
areas, not their geometric union. Keep all computations independent of paging.
Include exactly matching hall spaces; counted-delivery eligibility is irrelevant
to an area query.

**Verify:** a total spanning multiple search pages, irregular polygons, an empty
filter and strict floor/type isolation. The final scored line contains exactly
one number, within ±5%.

## 9. F07 — `straight_line_distance_3d`

**Backlog:** BEN-03; depends on F03.

```python
straight_line_distance_3d(first, second)
```

Use each polygon's centroid and its floor's actual `elevation_m`, then compute
Euclidean XYZ distance. Return the two XYZ points, resolved IDs and `distance_m`.
Do not use route anchors or floor levels as height.

**Verify:** same-floor, basement, nonconsecutive floors, unequal floor heights,
concave polygons whose centroid differs from the representative point and
missing/nonfinite elevation. The numeric answer tolerance is ±2%.

## 10. F08 — `find_stacked_room`

**Backlog:** BEN-04; depends on F03.

```python
find_stacked_room(space, direction)
```

Accept `above`/`below`; inspect the next available floor in that direction, not
`level ± 1`. In a shared XY frame, choose the candidate with greatest polygon
intersection area. Return identity, source/target floor, `overlap_area_m2` and
overlap fraction. Return an explicit no-floor/no-overlap result. Do not claim
floor alignment when the source does not establish a common frame.

**Verify:** floor gaps, split overlaps, ties, non-overlapping rooms and buildings
without another floor. Score the selected room name before any alternatives.

## 11. F09 — `count_shared_walls`

**Backlog:** BEN-05; depends on F03.

```python
count_shared_walls(space)
```

Count eligible rooms on the same floor with at least **1 m of wall running
within 0.35 m** of the source wall. Exclude the source itself, corridors,
stairwells and lifts. Doors are irrelevant to this geometric relation. Return
`count`, room IDs and measured shared-wall evidence.

Apply this operation's eligibility separately from F04: the existing dev audit
includes factory hall bays as neighbours and excludes outdoor balconies. Verify
those distinctions against the source fixtures; do not use a shared global
`type=room` rule for every analysis tool.

Use a tested boundary-segment method. A naive boundary-buffer intersection can
count short corner caps as wall length: parallel runs, thickness, diagonal walls
and corner-only contacts need explicit treatment.

**Verify:** just below/at/above 1 m and 0.35 m, irregular and diagonal walls,
corner-only contact, a shared wall without a door, exclusions and floor
isolation. The scored answer must be an exact count.

## 12. F10 — `plan_errand`

**Backlog:** BEN-08; depends on F01, F02, F04 and F05.

```python
plan_errand(start, asset_type, destination_room_type, destination_floor_level,
            step_free=False, min_width_m=0)
```

Enumerate rooms containing the exact asset type and select the nearest
reachable pickup room by constrained **route distance from the start**. Then
route from that pickup to the largest requested destination room on the target
floor. This selection order comes from the question: it is not a joint
optimization over pickup-plus-delivery length. Deduplicate assets in one room
for pickup comparison. Respect the question's stair permission.

Pickup candidates can include outdoor balconies containing the requested asset;
do not inherit F04's destination-count exclusions. An item being carried does
not imply an unstated width or stair restriction.

Return selected asset/pickup/destination identities, both complete route legs
and total `length_m`. A failed second leg is reported; never silently choose a
farther pickup or smaller destination to obtain another answer. Calculation
does not disturb an unrelated active route unless explicitly activated.

**Verify:** Euclidean-nearest differs from route-nearest, unreachable pickups,
multiple assets per room, missing assets, stairs allowed/forbidden and
unreachable selected destination. Numeric tolerance is ±1% or ±1 m, whichever
is larger; final answer has exactly one number.

## 13. F11 — `find_best_tour`: shortest tour in any stop order

**Backlog:** L2-05, MAP-02–04, L2-03. Explicitly requested in this handoff;
implement it even though older planning text described optimization as optional.

```python
find_best_tour(start, stops, destination, step_free=False, min_width_m=0,
               activate=True)
```

Start and destination stay fixed. For a round trip, pass the start as the
destination. Resolve every stop and calculate constrained pairwise shortest
paths using F01's common route engine. Use Held–Karp dynamic programming or
another exact method with a documented maximum of **10 intermediate stops**.
Reject larger exact requests with a useful message; do not label a heuristic
result shortest. Break equal-cost orders deterministically by IDs.

Return the optimized stop sequence, full route/edge details, directions,
per-leg distances, total length, constraints, distance model and
`optimal: true`. Calculate the winning order using unrounded distances. Preserve
repeated requested stops as distinct visits with zero-length legs where
appropriate. Keep the deliberate stop sequence separate from intermediate
spaces crossed en route.

Illustrative response shape; the IDs/distances below are examples, not dataset
facts:

```json
{
  "stop_sequence": ["A", "C", "B", "E"],
  "legs": [
    {"from": "A", "to": "C", "distance_m": 39.0},
    {"from": "C", "to": "B", "distance_m": 43.0},
    {"from": "B", "to": "E", "distance_m": 12.0}
  ],
  "length_m": 94.0,
  "optimal": true,
  "distance_model": "kit"
}
```

The real result also includes reconstructable route details for each leg.
An impossible required stop makes the whole tour infeasible; never drop it.
Handle no intermediate stops as a normal A-to-B route. `activate=False` is a
read-only comparison and must not replace the displayed route.

Conversation rules: use this tool when the user requests the shortest route in
any order. Preserve explicit order through `find_route(..., via=...)`. If
offering a shorter alternative, compare without activating it, retain both
fixed endpoints and all constraints, and change the active tour only when the
user chooses the alternative. Do not apply this objective to BEN-08 errands.

**Verify:** exact results versus exhaustive permutations for small fixtures,
an order where nearest-neighbour is wrong, ties, fixed endpoints, repeated stops,
empty stops, 10/11-stop boundary, closed/step-free-inaccessible stops, per-leg
sum and map/sequence agreement. A preview must preserve `last_route`.

## 14. F12 — `analyze_what_if_door`

**Backlog:** BEN-09, MAP-05–06; depends on F01, F04 and F09.

```python
analyze_what_if_door(first_space, second_space, floor_level,
                     improvement_threshold_m=1.0)
```

Clone the active building including current closures, add a valid shared-wall
midpoint door in the clone, and compare every eligible target-floor room's
shortest distance to its nearest entrance before/after. Reuse the common door
and routing rules. Use multi-source shortest-distance calculations rather than
a model loop making one route call per room.

Return the improving-room count/IDs, before/after distances, threshold and
proposed opening. Count improvements **strictly greater than 1 m** by default.
Define infinity handling explicitly and validate it against labelled train/dev:
finite-after/unreachable-before is distinct from unreachable in both states.
Keep kit outside-node/exit semantics explicit.

Never save a simulated door or alter the original data, closures, active route,
selection, indexes or files, including when analysis fails.

**Verify:** improvements of 0.99/1.00/1.01 m, different door/target floors,
unreachable cases, an invalid proposed door and byte-for-byte persisted-state
preservation. The scored answer is an exact count.

## 15. F13 — `find_navigation_landmarks`

**Backlog:** L2-06, MAP-02–04; depends on F01–F03.

```python
find_navigation_landmarks(x_m, y_m, floor_level,
                          inner_radius, outer_radius, min_size=0.0,
                          kind="asset")
```

Purpose: find nearby reference objects at a navigation step, and check whether
similar nearby objects would make the instruction confusing. A fire extinguisher
can be useful only when the cue distinguishes it from other extinguishers.

- Search in the selected building/floor's metre XY frame. Coordinates refer to
  the actual step/arrival point from the computed route.
- `inner_radius`: candidate centres/positions at distance **≤** this radius.
  For spaces, measure distance to the polygon, consistent with spatial search.
- `outer_radius`: count similar objects within this radius **of the same query
  point**, including those inside the inner circle. It must be at least the
  inner radius. Exclude the candidate itself from its competitor count.
- `min_size`: implementation convention is footprint **area in m²**, not visual
  salience. Asset area is `width_m × depth_m`; space area is polygon area. With
  a positive threshold, exclude assets whose size is unknown; with zero, return
  them with `size_m2: null`. Never invent missing dimensions. Rotation does not
  change footprint area.
- `kind`: `asset` for step cues, `space` for larger destination context, or `all`.
  Compare competitors within the same kind and exact normalized asset type or
  room type. Numbered names must not make repeated objects look unique.
- Count **all** matching competitors in the outer circle, even small or
  unknown-size ones excluded by the candidate size filter. Include colocated
  distinct IDs. Never count only the first search page or count another floor.

Return candidate ID, name, kind/type, room/floor, position, `distance_m`,
`size_m2`, `similar_count_outer`, competitor IDs, `is_unambiguous` and the query
parameters/size convention. Sort unambiguous candidates first, then distance,
known size descending and ID. If none qualify, return an empty result.

The coordinate query establishes proximity and ambiguity, not visibility.
Integration must reject cues behind walls or in unrelated rooms, using the
route's selected room/opening context. Report visibility as unknown unless
geometry supports it; do not say an object is visible merely because it is
nearby. When all cues are ambiguous, use room/door names or an explicitly
qualified cue instead of saying “the extinguisher”. Left/right directions also
require an incoming/outgoing route heading; the LLM must not invent a turn.

**Verify:** unique extinguisher near a turn, an identical one in the outer ring,
a competitor inside the inner circle, radius equality/boundaries, another
floor, unknown/small footprints, numbered duplicate names, colocated objects,
more than 15 competitors, a nearby object across a wall, empty results and
index refresh after relevant edits.

## 16. F14 — Map highlights and larger destination landmarks

**Backlog:** L1-01–02, L1-05, L2-01, L2-06, MAP-02–04; depends on F01–F03,
F09, F11 and F13 for their respective displays.

Render the selected room/asset and computed route with clear start, destination,
numbered stops and distinct landmark markers/labels. Show closed areas and the
correct floor handoffs. Fit the useful area; make the current destination and
its contextual landmark visually prominent. Draw each route segment from its
selected edges, never from the first door joining the same room pair. Keep
disjoint floor visits and outside transitions separate instead of drawing a
straight line between them.

Reuse F13 with `kind="space"` and a larger explicit area threshold for nearby
named rooms such as a canteen/Mensa, lobby or large hall. This is larger-scale
arrival context; F13's small assets remain useful at individual turns. Rank
named, sizable, unambiguous rooms; return the supporting ID and geometry so
the text and map refer to the same landmark. Threshold/radius values are visible
tool inputs, not an unexplained hard-coded claim about all buildings.

Use “The destination room is next to the canteen” / “Der Zielraum liegt direkt
neben der Mensa” only when a same-floor adjacency relation is supported by wall
geometry. For a room merely within the radius, say “near” and show its measured
relationship. Adjacency does not assert a connecting door or public access.
Describe a target asset's containing room accurately; do not imply its exact
position is next to the neighbouring room. Omit context when no useful cue exists.

Expose a small typed locate/map action (for example `show_location(element)`)
alongside `show_route`. Selection must be explicit and building-scoped. Search,
landmark lookup and tour previews must not overwrite unrelated selection state.
Recomputation after closures retains the original constraints and updates both
directions and markers. An unreachable result clears the old route display.

Use the existing app surface if one has appeared by implementation time. The
present code only writes PNGs: complete a small local visual interaction with
floor selection, next-page search controls and loading/error states so users can
inspect results without manually finding output files. Keep orchestration and
UI state thin; computation remains in the existing modules. Do not build a
second geometry/routing implementation in the frontend.

**Verify in the actual user surface:** page-2 locate → correct floor/highlight;
route → numbered optimized stops → identical tool/map order; floor handoff;
close chosen door/lift → reroute or cleared unreachable view; duplicate small
landmark → safe fallback; destination beside a canteen → matching large marker
and supported wording. Inspect rendered images as well as tool JSON.

## 17. F15 — Agent integration, answer formatting and final review

**Backlog:** L1-03–04, L2-04, QA-01–03, SUB-01–02; depends on all delivered
features. Give this Sonnet agent the integration work; the coordinator still
performs independent final verification afterwards.

Register every implemented tool in `make_tools` and verify its generated schema
and real `.call(...)` JSON response. Keep prompt claims synchronized with tool
availability. Preserve existing local prompt/model edits while resolving stale
claims deliberately; do not replace the entire prompt without review.

The conversation must distinguish: locate versus navigate; exact inventory
versus fuzzy search; ordered tours versus freely reordered tours; nearest pickup
then delivery versus global tour optimization; real edits versus what-if queries;
small step landmarks versus larger arrival context. Reuse resolved IDs and ask
only necessary clarification. Keep current location separate from destination
and preserve accessibility preferences after reroutes/destination changes.

For benchmark questions, derive replies from actual data and question text.
Train/dev `inputs` and `answer` are verification material only. They must not be
read by the production answer function or used to hard-code responses.

Keep `benchmark/score.py` unchanged. Final committed answers follow its contract:

| Question kind | Dedicated tool | Final answer requirement |
|---|---|---|
| `largest_room` | F05 `find_largest_room` | Selected room first and its area; ±5% |
| `floor_area_total` | F06 `sum_floor_area` | Exactly one number; ±5% |
| `straight_line_3d` | F07 `straight_line_distance_3d` | Exactly one number; ±2% |
| `room_stacked` | F08 `find_stacked_room` | Selected room before alternatives |
| `shared_walls_count` | F09 `count_shared_walls` | Exactly one integer; exact count |
| `wide_delivery_count` | F04 `reachable_rooms` | Exactly one integer; exact count |
| `step_free_reachable_count` | F04 `reachable_rooms` | Exactly one integer; exact count |
| `errand` | F10 `plan_errand` | Exactly one number; ±1% or ±1 m |
| `what_if_door` | F12 `analyze_what_if_door` | Exactly one integer; exact count |

Every scored reply ends with the requested `Answer:` line. Explanatory prose may
precede it; numeric answer lines must not include room numbers, ranges or a
second number. Evaluate generated replies through the unchanged official scorer.

## 18. Verification and delivery gates

Run from the repository root; select `final_agent` explicitly. Finish the
appropriate focused checks after each feature, then these integration checks:

```bash
uv sync
uv run python -m unittest discover -s tests -v
uv run python -m final_agent.evaluate data/dev --oracle
uv run python -m final_agent data/dev/proc-factory-dev-003
```

The interactive command requires configured Anthropic credentials. Run the
real visual flow in F14 and the conversation script in L2-04; a valid PNG header
alone is not verification of visible, usable output.

Reuse and minimally extend the existing evaluation-only
`bench_analsysis/run_tests.py` and fixtures for component-level labelled-dev
checks; its current missing-tool map is a snapshot that must be updated as
features land. Its GAP results are not passes. Cover all nine scored kinds with
small focused additions where the existing representatives lack coverage. Such
code may consume dev `inputs`/`answer` to verify tools; the live answer path
never reads labels. Avoid a second audit framework. Report per-kind correctness
and individual failures separately from language interpretation and formatting.

Live checks consume API credits and need working credentials. Start small:

```bash
uv run python -m benchmark.evaluate data/dev --agent final_agent.benchmark:answer --per-kind 1 --name final-feature-handoff-smoke
```

After inspecting and fixing failures, broaden when justified:

```bash
uv run python -m benchmark.evaluate data/dev --agent final_agent.benchmark:answer --name final-feature-handoff-dev
```

Use distinct result names so existing teammates' benchmark runs are preserved.
Report all 138 dev questions by kind, actual latency/usage and any skipped or
failed calls. Do not quote hard-coded price estimates as actual configured cost.
If credentials/model access block a run, state exactly what remains unverified.

F15 produces `BENCHMARK.md` with the command actually tested. Public test output,
once ready for submission, is generated with:

```bash
uv run python -m benchmark.evaluate data/test --agent final_agent.benchmark:answer --name final-feature-handoff-test --submission-csv agent_output/submission.csv
```

Verify UTF-8, exact `question_id,answer` header, all 145 unique expected IDs,
nonempty replies, correct multiline CSV quoting and size ≤5 MB. No manually
labelled test answers. Do not invent the organizer-dependent Sunday schema or
release time; adapt only when the announced contract is available.

### Coordinator sign-off

- [x] Each F01–F15 implementation has a Sonnet agent report and reviewed diff,
  or is explicitly recorded as pending with its blocker. *(F14 web UI removed
  from scope by user decision; F15 reverted by user decision and pending, see
  [F15_HANDOFF.md](F15_HANDOFF.md).)*
- [x] Focused tool/geometry/state tests and integration suite pass; no starter
  imports, scorer changes, label leakage or unrelated working-tree edits.
  *(173 tests; `benchmark/score.py` and `starter_agent/` byte-unchanged; only the
  evaluation-only `final_agent/evaluate.py` reads warm-up labels.)*
- [x] Existing kit oracle results remain compatible; new tool results identify
  their distance model and preserve all route constraints. *(369/369; selected
  `element_path`/`space_path` equal the labels for 172/172 dev routes and 40/40
  tour legs; 17/17 unreachable cases explained and cleared.)*
- [x] All nine scored kinds have deterministic tool coverage and documented
  dev verification; live results are reported separately from oracle/component
  results. *(Components dev 138/138, train 517/517; live not run: no credentials.)*
- [x] Map, steps, selected connectors, optimized stop order and distances agree;
  stale routes and misleading/ambiguous landmarks do not survive rerouting.
  *(Renderer draws the route's selected doors; best tour equals brute force on 79
  feasible real tours; rendered PNGs inspected; `show_route` refuses a stale route.)*
- [x] Pagination, complete inspection, reachability, what-if isolation and save
  failure behavior have been exercised through actual tool boundaries.
- [ ] README/backlog/tool descriptions agree with what is implemented and what
  was actually tested; demo/submission commands are reproducible. *(Pending with
  F15: its documentation update was reverted with it; the live submission
  command cannot be run here.)*

Each implementation report states: feature/backlog IDs, changed files, tool
contract, exact checks run with outcomes, actual user-flow evidence, remaining
limitations and integration dependencies. The coordinator's final report repeats
the verified results independently and identifies anything still pending.

## 19. Keep the remaining hackathon requirements in view

This feature set improves functionality (55 points) and interaction (25). It does
not by itself complete all required levels. Keep L3-01–03 for multiple floors,
building selection and walkway routing, and L4-01–06 for calibrated plan
ingestion, validation, conversational correction and export/reload. Complete
those existing backlog gates before claiming a finished hackathon product.

Synera's automatic route check also requires wall-respecting door-to-door paths
with approximately 15 cm clearance, height-based stairs/lift costs, forklift-only
eligible aisles/openings and destination-only production bays. Implement and
verify that explicitly identified route model before claiming automatic-check
readiness. Its endpoint/outside details and Sunday output schema remain subject
to organizer clarification. Do not bolt guessed rules onto the kit model.

Use the images as feature evidence: the first requests `list_spaces`,
`inspect_space`, `reachable_rooms` and pagination/type filters; the second lists
all nine missing analysis kinds. Their old status descriptions are not new
verification evidence. The user's requested tours, map context and inner/outer
landmark semantics are specified above. Finish the required product and demo
before adding voice, 3D, AR or another optional extension.
