# Level 4 handoff — create and correct buildings from plans

**Prepared: 25 October 2026. Status: implementation brief; Level 4 is not complete.**
Read [AGENTS.md](AGENTS.md), [README.md](README.md), [BACKLOG.md](BACKLOG.md) and
[CODEBASE_AUDIT.md](CODEBASE_AUDIT.md). Implement L4-01–06, with
CORE-05 and MAP-04–06 where needed. The backlog owns verified completion status.

## Outcome and scope

A user supplies a new plan, establishes scale, reviews extraction, corrects an
uncertainty through conversation, saves/reloads, then locates and follows a
constrained route. Apply the same review to existing buildings. Record elapsed
setup time; prewritten JSON does not demonstrate “minutes, not days”.

Start with one supported raster format, one floor, a few rooms and an entrance.
Extend that working slice to aligned floors, stairs/lifts and equipment from
available plan/list inputs. Document supported formats precisely. PDF conversion
can follow when a working converter is available; unsupported input gets a clear
conversion instruction. No new frontend framework, service, database, general
CAD importer, phone capture, OCR platform or replacement routing engine is needed.

The separate frontend track owns the interactive surface. Agree its integration
contract below. Backend tools alone do not complete the user-facing Level 4 gate.

## Current code to reuse

| Existing component | Use and limitation |
|---|---|
| `BuildingMap.load`, `JsonBuildingStore` | Common JSON and atomic local saves; loading is not schema validation. |
| `BuildingMap.add_door`, `shared_wall` | Same-floor shared-wall placement, widths, duplicate checks and invalidation. |
| `set_closed`, `recompute_active_route`, `compute_route` | Closures, route state and deterministic checks on the candidate model. |
| `make_tools`, `draw_floor`, `show_location`, `show_route` | Tool errors, useful map artifacts and grounded locate/route results. |
| `BuildingMap.transaction` | Rolls back current closure/opening edits only; not full-map correction or undo. |
| Existing metadata/unknown fields | Retain IDs, source/licence data, elevations and custom fields on every update. |

No plan import, calibration, extraction, full validation, correction review or
timed unseen-plan flow exists. The audit reproduced duplicate room IDs silently
overwriting dictionary entries and an imported cross-floor door yielding a
zero-length step-free route. Prevent both before constructing a usable map.

## Ownership and shared interfaces

| Module | Work |
|---|---|
| `agent.py` | New-building startup, plan attachment/path, required clarifications, draft context and explanations. |
| `tools.py` | Typed begin/extract/inspect/correct/preview/apply/cancel/undo operations and JSON responses. |
| `building_map.py` | Deterministic calibration, model/reference/geometry validation and candidate edits. |
| `storage.py` | Isolated draft/current/previous files, atomic commits, reload and source metadata. |
| `viewer.py` | Source-plan overlay, candidate geometry, IDs, uncertainty/error markers and correction previews. |

Use short typed helpers and plain dictionaries; a focused import helper is acceptable
if image/model handling would crowd existing modules. Keep `final_agent` canonical.
Coordinate shared-file ownership with Level 3; register files in primary `live_agents.md`.

Expose draft/building IDs, base/current revision, source reference, calibration,
proposed building data, validation issues, changed IDs and preview paths. Distinguish
creation, extraction, correction, validation and commit in operation results.
Keep one active draft per selected building/session initially. A new session must
start from a plan without hand-authoring or seeding JSON.

## First complete slice: L4-01–05

1. Accept a PNG or the chosen supported raster format through the existing
   frontend attachment contract or a small existing-CLI create mode. Collect
   building name/ID, floor name/level and elevation, source and declared licence.
   Missing scale or attribution remains explicit; do not invent dimensions or terms.
2. Ask for two plan points and their real separation, or a usable scale bar/known
   dimension. Deterministically transform extracted pixel coordinates to metres.
   Store pixel↔metre transforms, image dimensions, source points, metre length,
   origin, rotation and y-down→y-up inversion. Check another known dimension when
   supplied; expose the residual rather than fitting geometry to a desired answer.
3. Send actual image content in a supported vision request through the existing
   API client to propose rooms, labels/types, boundaries, openings and an entrance.
   The model extracts observations; deterministic helpers own scale, areas/connectivity.
   A local path string alone is not image ingestion.
4. Create a draft in the common schema, validate it, and overlay its boundaries,
   IDs and openings on the source plan. Show uncertain observations and errors.
   The active building, route, selection and saved current map stay unchanged.
5. Take one real correction, such as “that gap is a wall” or a room-name change.
   Resolve the affected draft IDs, apply a focused candidate patch, revalidate
   and show the changed preview. Request only the information needed to resolve it.
6. Apply the reviewed draft atomically, return the committed revision/path, reload
   it and locate/route using existing tools. Demonstrate step-free or minimum-width
   routing, plus a valid unreachable case. Cancel and undo must work in this slice.

**Gate:** source, preview, correction, saved JSON and resulting map agree, with no
hand-encoded replacement geometry. Then complete the model/correction cases below.

## Calibration, extraction and provenance: L4-01–02

Use one metre XY frame per building, with x right and y up. Additional floors
need a declared alignment: common reference points, scale and orientation.
Keep integer floor levels distinct from measured `elevation_m`; basement or
nonconsecutive level numbers do not define height. Ask when elevations/alignment
are unknown. Do not assume separately cropped floor images already stack.

Assign stable building-scoped floor/space/opening/connector/asset IDs once; name
corrections preserve them. Attach equipment only to confirmed containing rooms
and floors. Extract only observable or explicitly supplied items. Keep uncertain
door widths, step-free flags and connector stops as unresolved draft facts until
reviewed; proposed defaults must be labelled as inferred, not measured access.

Preserve source path/hash, page/image, calibration and extraction method in import
metadata or a referenced local sidecar. Keep existing source/licence/attribution.
Mark inferred elements `synthetic`; record what needs review. Model confidence is
not measured accuracy: give uncertainty reasons and highlight source regions.

## Validate before navigation: L4-03

Validate raw records before dictionary indexing can discard duplicate IDs.
Return structured issues with severity, element/floor IDs, reason and repair.

- Require unique nonempty IDs, known references and finite metre coordinates;
  reject booleans used as numeric values, NaN, infinity and impossible dimensions.
- Check nonempty valid room polygons, positive areas and floor membership. Report
  intersections/gaps requiring review; do not silently repair a different floor plan.
- An opening joins two distinct valid spaces on one floor, or one space and
  `outside`. Check declared floor, positive width, valid wall/entrance location and
  sufficient shared stretch. Reject cross-floor doors, self-doors and corner bridges.
- Check connector kind, paired stop/floor arrays, unique stops, matching floor
  ownership, measured elevations and plausible aligned locations. Stairs/lifts
  provide cross-floor travel; an opening never substitutes for a connector.
- Check asset coordinates, containing-room/floor agreement and positive known
  footprint dimensions. Report equipment outside its proposed room.
- Report disconnected components, inaccessible entrances, unresolved accessibility
  and unreachable rooms. Let intentional disconnections remain explicit; never add
  speculative doors to make every room reachable or relax route constraints.
- Check any intended demo route has real selected transitions and drawable walking
  segments. The inherited 1.5× distance fallback does not validate an extracted plan.

Block navigable commit for invalid IDs/references/geometry or unresolved facts
needed by its claimed access. Warnings may be acknowledged when their consequence
is clear; intentional unreachable rooms remain unreachable. Apply strict extraction
checks to new candidates. Existing-map edits preserve unchanged kit geometry/defaults:
report pre-existing limitations separately and reject introduced/worsened errors.
Do not require new import metadata globally or silently rewrite source geometry.
Preserve Swiss alignment limitations and the README's `kit-1.1.0` door-to-door,
wall-clearance and elevation costs. Keep its compatibility fallback explicit and
forbid outside shortcuts; strict plan validation does not change benchmark semantics.

## Corrections, persistence and undo: L4-04–05

Support room name/type, boundary, door position/width/access, entrance, connector
stop and equipment assignment corrections. Copy the live building data and closure
set for existing-map updates; preserve unknown fields and show proposed changes/issues.

Use `draft → validated preview → apply` with explicit cancel and at least one
committed undo. Every candidate carries its base revision: reject applying a stale
preview after another change and offer revalidation. Draft errors leave the prior
candidate/current map usable. Simulation tools remain query-only and save nothing.

Do not use the current `transaction()` as a full snapshot: it omits spaces, floors,
assets, connectors, `active_request` and selection. Validate/save a complete candidate,
then replace the active map, or deliberately implement complete rollback. Keep one
previous committed snapshot for undo; undo uses the same validation/save path.
Cancel preserves active data and saved current bytes. Save failure preserves the
prior map/revision and returns an actionable error; no success before persistence.

After commit/undo rebuild tool bindings and refresh the overview as well as the
map reference: existing tool closures capture their `BuildingMap`. Invalidate walk
caches, spatial indexes, routes and rendered artifacts. Retain preferences; re-resolve
selected/location IDs, clear removed ones, and recompute a still-valid journey or
explain why it is unavailable. Old route images must not appear current.

Store outputs under distinct building/session/draft-or-revision directories, never
shared `agent_output/building_edited.json` or floor-only image paths. Return the
exact resume path. Reload must preserve all arrays, IDs, metadata and intended
closures; compare loaded fields and a locate/constrained route, not just JSON syntax.

## Frontend and Level 3 integration

Return draft/revision IDs, actions, missing calibration, issues and displayable
artifact paths. Accept source-image pixel corrections; return consistent calibrated
coordinates/overlays. The frontend shows source/preview, pending/committed status,
errors, apply/cancel/undo and final locate/route maps. Agree transport/file handling
with its owner; do not build a competing UI or duplicate frontend geometry.

[Level 3](LEVEL_3_HANDOFF.md) receives only a validated committed building revision.
Keep original per-building IDs; namespace cross-building references externally.
Unrelated local XY frames do not become campus geometry: campus transforms and
measured walkway lengths belong to Level 3. Notify its registry on replacement or
undo; invalidate affected campus routes and make removed entrance links unusable
with an actionable review message. No zero-cost connection through `outside`.

## Verification, demo and delivery: L4-06

The 24 October audit's 202 tests (199 pass, 3 skip), storage 8/8, dev components 138/138 and oracle
369/369 are prior evidence; none proves plan extraction or this flow.
Future checks, from the repository root, after adding a focused `test_plan_build.py`:

```bash
uv run python -m unittest discover -s tests -p 'test_plan_build.py' -v
uv run python -m unittest discover -s tests -p 'test_storage.py' -v
uv run python -m unittest discover -s tests -p 'test_routing.py' -v
uv run python -m final_agent <committed-building-json>
```

Keep regressions small: known pixel→metre conversion; duplicate IDs/cross-floor
door rejection; one correction; cancel byte preservation; stale preview; failed
save; undo/reload; two isolated sessions. Extend existing tests where appropriate.
For shared model/routing changes run affected component checks and the oracle;
broaden to the full suite when warranted. Keep `benchmark/score.py`, labels and
dataset files unchanged. Production extraction never reads expected answers.

Run actual image/conversation extraction on an unseen plan with configured credentials.
Time input selection through reload and displayed locate/constrained route. Record
clarification, extraction/review, correction and save/reload times, geometry/connectivity
errors and remaining manual work. Include a multi-floor case and existing-building
correction before claiming completion. Do not invent a promised setup duration.

- [ ] L4-01: supported input, scale/frame/elevation prompts and checkable dimensions.
- [ ] L4-02: extracted editable rooms/connections/equipment with uncertainty/provenance.
- [ ] L4-03: deterministic validation rejects the reproduced bad models.
- [ ] L4-04: new/existing map preview, correction, cancel and persisted undo work.
- [ ] L4-05: isolated export/reload preserves facts; locate and constrained routes work.
- [ ] L4-06: real unseen-plan timing and connected conversation/map demo recorded.

Deliver code, launch/import/resume commands, attributed demo input/output, checks and timing.
Update README/BACKLOG only to verified
behavior; mocked tests do not establish live accuracy, integration or a complete level.
