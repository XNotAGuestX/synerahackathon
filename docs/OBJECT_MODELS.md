# Shared object heights and 3D models

For another agent integrating these assets, start with the
[3D model integration handoff](3D_MODELS_HANDOFF.md).

`final_agent/object_catalog.json` is the single maintained table for Python and
the frontend. It covers all **96 distinct types** found across the 280 buildings
in `data/`. `washing_machine` belongs to both fixture and equipment categories.
The source datasets are unchanged.

Each entry has an estimated `height_m`, an individual `height_reason`, categories,
a local `model_path`, model provenance and a model kind. `preview_footprint_m`
contains median XY dimensions from the supplied assets, used only by the model
showroom. Real building rendering always uses each asset's own footprint.

## Height conventions

Heights are overall object bounding heights in metres: chair backs and bed
headboards count, while a microwave's supporting counter does not. These are
reasoned visualization defaults, not surveyed dimensions or clearance data.
Typical seated tables are 0.74–0.75 m; standing worktops are 0.9 m. Industrial
equipment dimensions vary, so their rationale explicitly identifies the assumed
equipment scale. Wall/ceiling mounting elevation is separate; the current viewer
places asset bases on their floor. It does not infer supporting surfaces.

A positive finite per-object `height_m` overrides the estimate. The floor-plan API
preserves that optional value. Existing curated type defaults are not overwritten
by one unusually sized instance. Heights/models do not alter routing or scoring.

## Unknown types

An accepted backend `PlanDraft.apply()` registers new types in the JSON table.
It uses an explicit initial height when supplied, then shape keywords from the
shared table (for example `inspection_table` → 0.75 m), then a category estimate
(machine 1.8 m, furniture/fixture 0.9 m, equipment 1 m). With no category it uses
1 m. Every inferred value is marked `estimated` with a reason.

New types point to `/models/objects/unknown.glb`, a grey cube stretched to the
asset footprint and estimated height. No recognizable model is invented for a
new type. The frontend immediately uses the same estimation rules for unfamiliar
types, including local preview imports. A browser-only import does not write server
source files; apply it through the backend or run the sync command to persist its
type in the shared table.

```bash
uv run python -m final_agent.object_catalog data /absolute/new-building.json
```

Catalog writes use a process lock and atomic replacement. Failed building saves,
cancelled drafts and read-only benchmark loads never register types. If a catalog
write fails, applying the draft restores the building's previous saved bytes.
Run accepted imports from a writable checkout. Production frontend bundles take
a snapshot of the JSON at build time; rebuild after editing curated defaults or
assigning a new model. Unknown-type heuristics still work without that rebuild.

## Models and provenance

- **41 type mappings** use models from the [Kenney Furniture Kit](https://kenney.nl/assets/furniture-kit)
  (CC0). Some source models are reused for closely related types. `source_asset`
  records the exact original filename; `model_kind: proxy` identifies approximate
  matches, including wardrobes using a closed cupboard/bookcase.
- **55 type mappings** use original schematic models made with simple boxes and
  ten-sided cylinders. They follow the kit's flat-color, untextured style. They
  are not manufacturer models or CAD replicas. Generated assets are CC0.
- `unknown.glb` is an additional original grey block.

All 96 type-specific GLBs together occupy **1,138,876 bytes** (about 1.1 MB);
the largest is **810 triangles**. There are no texture downloads, animations or
external buffer dependencies. Source geometry is normalized to unit bounds at
load time, then scaled to the existing XY footprint and selected height. The
renderer uses metres, Y-up, floor elevation and the asset's existing rotation.
Floor polygons, assets and route lines share the same XY-to-XZ conversion.

Width (`footprint.width_m`), depth (`footprint.depth_m`) and height are independent:
the normalized mesh is stretched along each local axis with no aspect-ratio lock.
For example, a 2 m × 0.5 m footprint stretches the model to exactly those ground
dimensions while retaining its selected height. This applies to library models,
original schematics and the grey fallback alike; rotation follows the local-axis
stretch.

Each used model is loaded once per floor layer. Repeated objects use instanced meshes;
geometry/materials are shared within that layer and disposed on teardown. Layers
belong to the redesigned viewer's animated floor groups, so objects move and fade
with their floors in the single-floor and exploded overview modes. The 3D code is
loaded only when opening **Stack floors**. The viewer renders floor transitions,
camera damping and route animation in its animation loop.
This is a structural resource budget, not a mobile-device performance benchmark.

The original Kenney license is retained in
`frontend/public/models/objects/KENNEY_LICENSE.txt`. The JSON pins the original
download's SHA-256. Restore/rebuild the models without Blender or extra packages:

```bash
python3 scripts/build_object_models.py --kenney-archive /absolute/kenney_furniture-kit.zip
# Existing library files can be retained when rebuilding only original schematics:
python3 scripts/build_object_models.py
```

## Preview and verification

Start the frontend with `cd frontend && npm install && npm run dev`, then open
`http://localhost:5173/model-preview.html` to inspect all types or choose one.
The page uses the same renderer and model loader as the real floor stack.
Its independent **Width** and **Depth** sliders stretch the selected model (or all
models) from 0.25× to 3×. Height stays unchanged. **Reset dimensions** restores 1×;
these preview controls do not edit building data or catalog defaults.

Verified on 25 October 2026:

- 18 catalog, plan-import and workspace checks pass, including coverage, GLB
  budgets, unknown registration, per-instance heights and save rollback.
- 18 HTTP API checks pass, including the optional measured-height projection.
- TypeScript checking and production frontend build pass.
- The browser shows all 96 known models and the unknown grey block. A real
  `proc-factory-dev-003` floor stack loads **505 objects** without model-loading
  warnings/errors. No paid model call or benchmark evaluation was needed.

Additional viewer-integration checks on 25 October 2026:

- Integrated the viewer from `origin/feat/3d-floor-stack` at `f20e987`, preserving
  lazy loading and the showroom. Floor selection also updates the 2D plan.
- Measured the transformed GLB mesh bounds for all 96 known types at unequal
  width/depth and a 37° rotation, plus custom-height and unknown-model instances.
  All 98 instances match their defined width, depth and custom/default height
  within 0.0001 m (maximum observed error 0.000024 m).
- The 505-object factory view passes single/all-floor visibility and model
  fading, expand/reset, 390 px page width and teardown/remount checks. The
  showroom's independent width/depth sliders still work. Models share the
  floor's centred frame without scaling its elevation or parent group.
- `npm run build`, `npm run test:perimeter`, `npm run test:effects` and
  `npm run test:walk` pass. Browser checks show no model-load or application
  errors; the existing missing favicon is unrelated. The build retains Vite's
  advisory about the size of the lazily loaded Three.js chunk.

The backend checks above were prior catalog verification; they were not rerun for
this frontend integration. No new live conversation or benchmark score is claimed.

## Original generated types

All 18 machine types: `3d_printer`, `boiler`, `cnc_lathe`, `cnc_mill`, `compressor`,
`conveyor`, `coordinate_measuring_machine`, `curing_oven`, `drill_press`, `forklift`,
`hvac_unit`, `industrial_3d_printer`, `injection_moulding_machine`, `laser_cutter`,
`milling_machine`, `press_brake`, `robot_cell`, `waterjet_cutter`.

24 equipment types: `atm`, `defibrillator`, `dishwasher`, `electrical_panel`,
`eyewash_station`, `fire_extinguisher`, `forklift_charging_station`, `fume_hood`,
`hand_dryer`, `microscope`, `multifunction_printer`, `oscilloscope_station`,
`pallet_jack`, `powder_station`, `printer`, `projector`, `projector_screen`,
`server_rack`, `soldering_station`, `ups_unit`, `vending_machine`, `water_dispenser`,
`welding_station`, `whiteboard`.

13 furniture types: `assembly_station`, `chemical_cabinet`, `filing_cabinet`,
`inspection_bench`, `lab_bench`, `lectern`, `lecture_seating_row`, `locker`,
`packing_station`, `pallet_rack`, `reception_desk`, `tool_cabinet`, `workbench`.
