# 3D model integration handoff

25 October 2026. This handoff covers the catalog and its subsequent integration
with the redesigned viewer from `feat/3d-floor-stack` (`f20e987`). The original
catalog handoff added no verification; the later integration's actual checks are
recorded in [the catalog reference](OBJECT_MODELS.md#preview-and-verification).

## Where the work is

The implementation and all model files are already in the primary checkout:

```text
/Users/felix/tum/artemis/synerahackathon
```

These changes are currently **uncommitted**, including untracked JSON, TypeScript
and GLB files. Checking out the existing `codex/object-model-assets` branch alone
will not bring them into another checkout. Preserve the primary working tree and
coordinate an explicit patch/file transfer or commit when integrating elsewhere.
The earlier implementation checkout is `/private/tmp/synera-object-model-catalog`;
the primary checkout is the source for this handoff and subsequent edits.

Read the primary `live_agents.md` and register your files before editing. Other
agents have object-editor and voice-guidance worktrees; their work is separate.

## What is ready

- One shared catalog, `final_agent/object_catalog.json`, covers all 96 existing
  object types. Each entry records a height estimate and rationale, a model URL
  and its provenance. Do not create a second height/model lookup table.
- Each existing type has a local GLB under `frontend/public/models/objects/`.
  There are 41 Kenney library mappings and 55 original schematic models, plus
  `unknown.glb`. Some library mappings reuse a source model or are labelled proxies.
- The app's **Stack floors** view already renders objects with the loader below.
- The redesigned viewer's single-floor and exploded views include the models;
  they move and fade with their own floor. Floor selection updates the 2D plan.
- Width, depth and height stretch independently. The user explicitly accepts
  simple stretching; preserving mesh proportions is unnecessary.
- Unfamiliar types immediately render as a grey block with a reasonable height.
  Accepted backend plan imports also register their type in the shared JSON.

The [catalog reference](OBJECT_MODELS.md) contains the full generated-model list,
height conventions, source licenses and prior verification evidence.

## Files to reuse

| File | Responsibility |
|---|---|
| `final_agent/object_catalog.json` | Canonical heights, estimates, model URLs and provenance |
| `frontend/public/models/objects/` | GLBs and original `KENNEY_LICENSE.txt`; copied into the frontend build as public files |
| `frontend/src/domain/object-catalog.ts` | `objectVisual(asset)` resolves height, model URL and placeholder status |
| `frontend/src/rendering/floor-stack-3d/object-models.ts` | `addObjectModels(scene, plans, onReady)` loads, normalizes and instances models |
| `frontend/src/rendering/floor-stack-3d/FloorStack3D.tsx` | Working React view with scene, floors, objects, route lines, camera and cleanup |
| `frontend/src/app/App.tsx` | Lazy-loads the 3D view and keeps the plans array stable |
| `frontend/src/domain/types.ts` | `Asset` has XY footprint and optional per-instance `height_m` |
| `final_agent/api_session.py`, `openapi.yaml` | Preserve/document optional measured asset height in floor-plan responses |
| `final_agent/object_catalog.py` | Read/estimate/register types, with atomic JSON writes |
| `final_agent/plan_build.py` | Registers types on accepted draft apply; rolls back the building save if catalog registration fails |
| `scripts/build_object_models.py` | Reproduces original schematics and restores the pinned Kenney subset |
| `frontend/model-preview.html` | Development showroom with type selector and independent width/depth sliders |

## Use the existing React view

Reuse `FloorStack3D` when a complete building view is wanted. It accepts:

```tsx
<FloorStack3D
  plans={plans}               // FloorPlan[], including each floor's assets
  route={route}               // Route | null
  activeFloorId={activeFloorId}
/>
```

The existing import and `React.lazy`/`Suspense` wiring are in `App.tsx`. Keep that
lazy loading so the 2D app does not load Three.js and the GLTF loader until needed.
Keep `plans` referentially stable between unrelated renders; replace it when the
building or dimensions change. The current app uses `useMemo` for its plan array.

Floor-plan API requests must include `assets` if an explicit `include=` filter is
used. An empty `plan.assets` array naturally produces no models.

## Add models to another Three.js scene

Use the existing helper rather than creating separate loaders for each object:

```ts
// From frontend/src/rendering/YourScene.tsx:
import { addObjectModels } from './floor-stack-3d/object-models'

const removeModels = addObjectModels(scene, plans, (objectCount) => {
  needsRender = true
  // Loading has settled; request a draw if this scene renders on demand.
})

// On scene teardown or before replacing its plans:
removeModels()
```

This helper accepts a scene or any `THREE.Object3D` parent, adds meshes
asynchronously and immediately returns a cleanup function. It groups objects by
model URL and uses `THREE.InstancedMesh` per mesh primitive. Materials and geometry
are shared within that call's layer. The callback
also runs when a failed model request has been replaced by a grey block; its
count is not a count of successful model downloads. Failures are logged.

Supply the scene's camera, lighting, floors and render loop yourself, or copy the
working arrangement in `FloorStack3D.tsx`. Original schematics use standard PBR
materials and need lighting. Call cleanup even if loading is still in progress;
the helper disposes late results safely. The cache is per layer, not global.

The redesigned viewer loads one layer per floor. Its floor group owns the
animated elevation; a nested model group translates the loader's absolute dataset
coordinates into the viewer's centred frame without changing scale:

```ts
const objectGroup = new THREE.Group()
objectGroup.position.set(-centerX, -plan.floor.elevation_m, centerY)
floorGroup.add(objectGroup)
const removeModels = addObjectModels(objectGroup, [plan], onReady)
```

Room polygons and routes use the same centred XY-to-XZ conversion. Model materials
retain their original opacity, multiplied by floor visibility and overview fading;
ghosted objects do not write depth. Camera fitting includes the selected object
heights, including a custom height taller than the default exterior wall.

## Dimensions, rotation and placement

Use the actual asset's footprint, not `preview_footprint_m` from the catalog:

```json
{
  "id": "custom-workbench-1",
  "name": "Assembly bench",
  "type": "workbench",
  "category": "furniture",
  "floor_id": "F0",
  "space_id": "workshop",
  "position": [12.5, 8.0],
  "footprint": {
    "width_m": 2.0,
    "depth_m": 0.6,
    "rotation_deg": 30
  },
  "height_m": 0.95,
  "source": "user"
}
```

`floor_id` must match the containing plan's floor ID. The loader interprets the
following uncentred coordinates; the viewer's groups then centre and lift them:

| Building value | Three.js value |
|---|---|
| `position[0]` | World X |
| `floor.elevation_m` | World Y, at the object's bottom |
| `position[1]` | Negative world Z |
| `footprint.width_m` | Local X size in metres |
| `footprint.depth_m` | Local Z size in metres |
| Positive finite `height_m`, otherwise resolved estimate | Local Y size in metres |
| `footprint.rotation_deg` | Positive rotation around world Y, converted to radians |

The loader first applies the source GLB's transforms, centres its X/Z bounds,
places its bottom at Y=0 and normalizes the whole model to unit bounds. Each
instance then uses `translation × rotation × scale(width, height, depth)`.
Scaling happens in local axes, so rotation does not swap the width/depth fields.
Raw downloaded/generated GLBs are not guaranteed to have unit bounds; if bypassing
the helper, reproduce its normalization before applying metre dimensions.

To resize an object, update its existing `footprint.width_m` and/or `depth_m` and
pass new immutable plan/asset objects into the React view. To change only height,
set the optional per-instance `height_m`. A finite positive value overrides the
catalog; it does not change other instances of that type.

The current 3D layer renders these values but does not supply a persistent asset
resize HTTP endpoint or 3D object picking. Connect an editor's save flow to the
building/plan edit boundary. The showroom sliders change only preview objects.
Height is never derived from width or depth.

## Unknown types and keeping the table current

In the browser, call `objectVisual(asset)` to get:

```ts
{ height_m: number, model_path: string, placeholder: boolean }
```

It normalizes names such as `Office Chair`/`office-chair` to `office_chair`, uses
the shared catalog for known types and the catalog's keyword/category rules for
unknown ones. Unknown models use `/models/objects/unknown.glb`. Positive explicit
heights still take precedence. No model generation service is required.

Backend code that actually accepts a new asset type should call:

```python
from final_agent.object_catalog import register_asset_types

added_types = register_asset_types(accepted_assets)
```

`PlanDraft.apply()` already does this after saving the accepted building. Other
asset-creation flows must call it at their successful commit boundary and handle
registration failure transactionally. Do not put registration in benchmark loads,
searches, previews or what-if computation. Existing curated defaults are preserved.

An explicit synchronization command is also available from the repository root:

```bash
uv run python -m final_agent.object_catalog data /absolute/new-building.json
```

New entries have `model_kind: placeholder` and a documented height estimate. The
catalog must be writable for registration. A browser-only local import cannot
persist edits to a server source file; apply it through the backend or synchronize
its building JSON explicitly.

## Serving, replacing and rebuilding models

Catalog `model_path` values are browser URLs, for example
`/models/objects/workbench.glb`, not repository filesystem paths. Vite serves them
from `frontend/public/`. The loader combines them with `import.meta.env.BASE_URL`,
so keep that base-path handling when deploying under a URL prefix.

The frontend imports the shared JSON at build time. Rebuild when changing curated
heights or model mappings in a deployed app. New unfamiliar names can use the grey
fallback immediately without a rebuild because the estimation rules are bundled.

To replace a placeholder, add a lightweight, self-contained GLB to the public model
directory and update the one catalog entry's `model_path`, `model_kind` and source
metadata. Keep its height rationale. Record the model's source and license in the
catalog and `ATTRIBUTION.md`. A new source also needs support in the rebuild
script if its assets should survive/reproduce through that script; it currently
handles the Kenney subset and the project's known schematic types.

The retained files need no runtime network downloads or extra frontend dependency.
Models are texture-free, with no animations or external buffers. The 96 files total
1,138,876 bytes and the largest has 810 triangles. When replacing files, keep a
similar flat-color style and the existing script's ceiling of 2,000 triangles and
128 KiB per model. Keep the original Kenney license file and provenance.

Rebuild only when changing assets; these are reference commands, not work already
performed during this handoff:

```bash
python3 scripts/build_object_models.py
# To restore missing Kenney models as well:
python3 scripts/build_object_models.py --kenney-archive /absolute/kenney_furniture-kit.zip
```

## Preview and current limits

Run `npm run dev` in `frontend/` and visit `/model-preview.html`. Its width/depth
controls range from 0.25× to 3× and leave height unchanged. The current running
preview is `http://127.0.0.1:5180/model-preview.html`; the normal configured dev port
is 5173. Treat a running local process as temporary, not a deployment dependency.
The showroom is a development HTML entry; the current production Vite configuration
builds the app entry, not a separate showroom page. Public GLBs are included.

Existing evidence is recorded in `OBJECT_MODELS.md`: 36 focused backend checks,
the frontend build, a browser-rendered 505-object factory and independent dimension
stretching. No additional checks were run for this handoff, at the user's request.

Remaining limitations to preserve when describing the feature:

- Heights are visual estimates unless supplied explicitly; some model mappings
  are approximate and original schematics are not manufacturer/CAD replicas.
- Asset bases sit on the floor. Wall mounting, ceiling offsets and automatic
  placement on desks/counters have not been implemented.
- Phone GPU performance and close-up visual approval of every model are pending.
- Width/depth/height affect rendering. They do not change the deterministic route
  model or turn equipment into routing obstacles.

## Ready-to-forward request

> Use `docs/3D_MODELS_HANDOFF.md` in the primary synerahackathon checkout to
> integrate the existing 3D object assets into your frontend work. Reuse the shared
> catalog and `addObjectModels`/`FloorStack3D`; size each instance from its footprint
> and resolved height, with independent width/depth stretching. Keep unknown types
> as grey blocks and register newly accepted types at the backend commit boundary.
> Preserve the uncommitted implementation, provenance, instancing and cleanup.
> The user has said enough verification has been done; proceed with integration
> rather than spending more time re-running the existing checks.
