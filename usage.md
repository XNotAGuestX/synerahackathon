# Usage

Run from the repo root. Commands marked *paid* call Claude and need credentials
(`ANTHROPIC_API_KEY` or `ant auth login`).

## Normal mode

Every paid command takes `--model opus|sonnet|haiku` (default `haiku`, i.e.
`claude-haiku-5-5`). Only the exact names are accepted. The benchmark and training
print the money spent so far after every question (an estimate at list prices).

**Chat** (*paid*): `uv run python -m final_agent data/dev/<building>`
- `--output DIR`: where route images and edits go (default `agent_output`)
- `--model NAME`: `opus`, `sonnet` or `haiku` (default)

**Emergency mode (app):** start the API with `EMERGENCY_ADMIN_PIN=<pin>`. In the app, open the
Emergency tab, unlock with the PIN, type the code shown on screen and activate. The live list shows
every phone inside or outside: twelve simulated people walk out over time, and every open app
session with a position appears too (each phone is asked for a name). Mark people outside by hand,
undo, and end the alarm, which deletes all positions. See ADR-0004.

**Emergency mode (terminal chat, simulated people only, chat is paid):** ask “Start emergency
mode”, “Skip ahead 90 seconds”, “Mark P03 outside; seen at the assembly point”, then “End emergency
mode”. Floor maps are drawn per floor. Benchmark agents omit these tools.

**Benchmark** (*paid*): `uv run python -m benchmark.evaluate data/dev`
- `--per-kind N`: sample N questions per kind (default: all)
- `--kinds K ...`: only these kinds
- `--agent M:F`: `final_agent.benchmark:answer` (default, uses the run library) or
  `final_agent.benchmark:answer_without_examples`
- `--name NAME`: replies saved to `agent_output/benchmark/NAME.jsonl`
- `--submission-csv PATH`: also write `question_id,answer`
- `--debug`: print each question, the agent's `recall_examples` declaration and the
  run-library questions it matched (similarity score, question ID, translation, question)
- `--model NAME`: `opus`, `sonnet` or `haiku` (default)

**Warm-up check** (free): `uv run python -m final_agent.evaluate data/dev --oracle`
- `--limit N`: first N questions only
- without `--oracle` it runs the live agent (*paid*); `--model NAME` as above

## Test image import completely

Use this as an acceptance script. A generated preview or the two-room demo alone
does **not** establish complete image-import support. Complete the single-floor,
failure/recovery, and multi-floor checks below on real plan images; record failures
instead of counting an agent's success message as a pass. Multi-floor image import
has not yet been demonstrated live in the retained project evidence.

### 1. Start from the image path

Run `uv sync` once if dependencies are not installed. Live extraction and chat
are *paid* and require the credentials described above. PNG and JPEG are supported;
PDF pages must first be exported as separate images. Dimensions are interpreted
as **metres**, with no unit conversion or assumed pixel-to-metre scale.

First run the small, dimensioned smoke fixture:

```bash
uv run python -m final_agent --plan examples/level34/new-plan.png \
  --output agent_output/import-acceptance --model haiku
```

Then repeat in a fresh session with an image that has not been manually encoded
as building JSON. Supply its path in the command; no building JSON is required:

```bash
uv run python -m final_agent --plan "/absolute/path/to/your-plan.png" \
  --output agent_output/import-acceptance --model haiku
```

Record the printed `Workspace/resume: ...` directory. Each new run creates its own
workspace beneath the output directory. Do not choose an arbitrary latest saved
file. Path-only import uses the filename as the building name/ID, floor `F0`, and
level/elevation 0 as a local datum; unspecified source attribution/license stays
explicitly unknown. Measured elevations are required for multiple floors.

Start timing before the command. Keep the model, input image, extraction time,
manual review/correction time, and final save/reload/route time in the test record.

### 2. Review the draft against the actual image

The initial result must be `pending_review`, or `needs_calibration` when there is
no readable metric scale. It must not silently commit a new building.

For a calibrated draft, open the returned `images[].image` files and the source
image side by side. An image path proves generation; actually open it to check
the display. Ask in chat:

```text
Show the pending plan preview, its building/floor IDs, rooms, openings,
equipment, calibration and every validation issue. Do not apply it yet.
```

Check all of the following:

- Room labels/types and floor ownership match the source. IDs are unique; later
  name changes must retain them.
- Boundaries overlay the walls, openings connect the intended rooms, and an
  entrance connects one indoor space to outside. No speculative doors appear.
- Calibration cites a visible dimension/scale bar. Check a second dimension
  independently and compare room dimensions/areas with the source. Choose an
  acceptable measurement tolerance before reviewing the extraction.
- The smoke fixture is approximately 10 m × 4 m, with two approximately 20 m²
  rooms and two explicitly labelled 1.2 m step-free doors. Extracted pixel
  boundaries can be approximate; this is a visual/metric check, not a benchmark
  tolerance or a promise of exact results.
- Door widths, accessibility and connector stops are observed or explicitly
  unresolved. Equipment belongs to the correct room and floor.
- Source image dimensions/hash, calibration and attribution state are preserved
  in the proposed model. Uncertainty and disconnection warnings are visible.

Before applying, ask to locate/route in this new building. With no previously
registered version, navigation must remain unavailable. If an existing building
is loaded, a pending draft must leave that live building unchanged.

### 3. Correct, apply and use the imported building

Use IDs from **this extraction**; do not assume IDs match a previous demo run.
For the fixture, these prompts exercise the normal conversational path:

```text
Rename the extracted lab to Lab. Show the changed preview without applying.
```

Check that the room ID/boundary is unchanged and that `changed_ids` and the new
preview identify the correction. Also correct one actual geometry/access
uncertainty if the draft has one, using source evidence. A name-only correction
does not verify boundary, opening or connector correction.

For precise edits, the available tools are:

| Tool | Input/expected result |
|---|---|
| `preview_plan` | Current candidate, base revision, issues and source overlays. |
| `correct_plan` | `actions` with `{kind:"set", element_type:"space", id:"ACTUAL_ID", field:"name", value:"Lab"}`; boundaries use `polygon`, doors use `position`, `width_m`, `step_free` or `space_ids`, all in building metres. |
| `correct_plan_pixels` | `floor_id` and set actions using `polygon_px`, `position_px` or `width_px`; image coordinates start at top left and are calibrated to metre coordinates. |
| `correct_plan` add/delete | `{kind:"add", element_type:"opening", value:COMPLETE_OPENING_RECORD}` or `{kind:"delete", element_type:"opening", id:"ACTUAL_ID"}`. Use only observed/confirmed changes. |
| `correct_plan` uncertainty | `kind:"resolve_uncertainty"` with a supported field and confirmed value; inspect the issues afterwards to check that the intended uncertainty was resolved. |

When the preview agrees with the source, ask:

```text
Apply this reviewed draft. I accept only the remaining approximate-boundary
warnings we just reviewed; do not bypass geometry or accessibility errors.
```

Expected: `applied:true`, a revision, an exact saved JSON `path`, and an updated
building overview. `acknowledge_warnings` must not bypass errors. Record the path.
Then ask:

```text
Locate Lab and show its map. Route from the lobby to Lab without stairs,
with a minimum door width of 1.2 metres, and show the route map.
```

Check the containing room/floor, ordered spaces, actual selected door IDs,
constraints, distance and drawn path. The fixture route should be approximately
5 m under the kit route model. For other plans, compare the computed route with
their geometry rather than reusing this number. An equipment destination ends
in its containing room. No route may cross a wall or an invented connection;
missing drawable geometry must be disclosed, not drawn as a valid walk.

### 4. Cancel, undo, reload and recover from closure

Perform these in order so closures do not invalidate the edit/undo revision test:

1. On the committed building, ask to begin a building edit and rename Lab to
   `Cancelled lab`, preview it, then cancel. The live room must still be Lab.
   Hash the exact current JSON before and after with
   `shasum -a 256 "/absolute/path/to/current.json"`; cancellation must preserve
   its bytes and the registered current revision.
2. Begin a fresh edit, rename Lab to `Test lab`, review and apply. Record the
   new current path/revision. Exit, then resume the **exact** printed workspace:

   ```bash
   uv run python -m final_agent --resume "/absolute/path/to/workspace" --model haiku
   ```

   Ask to locate Test lab, then undo the last committed edit. Lab and its
   original IDs/geometry must return in a newly saved revision. Old route images
   must not be presented as current; regenerate the locate/route maps.
3. Exit and resume again. Confirm the selected building, restored name,
   geometry, assets, connectors, source metadata and route constraints. Also
   test the exported model independently in a fresh session:

   ```bash
   uv run python -m final_agent "/absolute/path/to/committed-building.json" --model haiku
   ```

   Locate and route again. Successful JSON parsing alone is insufficient.
4. On a working route, close its selected interior door. Verify either a valid
   alternative or an explicit unreachable result. Request the route/map again
   while closed: an old path must not reappear. Resume the workspace while still
   closed to check persistence, then reopen the door and verify recovery with
   the same endpoints and constraints. The two-room fixture should be unreachable
   while its interior door is closed.
5. Open two separate sessions from the same source image. A correction/closure
   in one must not affect the other. Compare output paths and source hashes:
   neither session may overwrite the other's files or the input image.

### 5. Test failure handling explicitly

Use separate disposable test workspaces. For negative draft edits, begin an edit
of the working imported building first, record its current JSON hash, and cancel
afterwards. Expected behavior is the acceptance criterion; any discrepancy is a
failure to record, not permission to weaken the check.

| Test | Required result |
|---|---|
| Valid image without dimensions/scale | `needs_calibration`; no guessed metre geometry or navigable commit. |
| Calibration recovery | Supply two **measured** image points and their known metre separation through `calibrate_plan`; a reviewable calibrated draft appears without another vision request. Example input shape: `{"calibration":{"point_a_px":[100,100],"point_b_px":[500,100],"distance_m":10}}`. These numbers are illustrative, not defaults for your image. |
| Missing path, corrupt image, or PDF | Clear load/format/conversion failure; no building is published. |
| Invalid draft | Try zero/negative door width, a self-intersecting polygon, duplicate ID or a door joining different floors. Validation must identify the error; apply must fail even when warnings are acknowledged. The previous current JSON/revision remains usable. |
| Unknown door width/access | Remains explicitly unresolved; no claim of a verified step-free/width-constrained route until the necessary fact is confirmed. |
| Stale preview | Begin an edit, then change a live closure/revision, then try applying the old draft. Apply must reject it; cancel/rebase the edit and restore the closure afterwards. |
| Disconnected room | A warning and honest unreachable result, with no automatically invented door. |
| Extraction/API failure | No success claim or partial live replacement. Truncated output must be an error; malformed JSON has at most one syntax-only repair attempt. |
| Failed save | Prior current bytes and revision survive. Exercise the existing injected-failure regression below rather than damaging a real output directory. |

For the no-scale case, `data/dev/proc-campus-dev-009/floor_0_plain.png` is an
available kit example. Its room numbers are not metre dimensions. Do not obtain
scale or expected geometry from benchmark labels to make this test pass.

### 6. Test multiple imported floors, stairs/lifts and equipment

This is a separate required acceptance gate. A route through an existing
multi-floor JSON fixture does not test multi-floor **image extraction**.

Use two unseen floor images with verifiable shared-frame alignment and known
floor elevations. Include stairs, a lift and at least one identifiable equipment
item. Launch an empty workspace and ask the agent to call
`create_building_from_plan` with both floor records, then perform correction,
review, apply and routing through the conversation. Each record requires:

```json
{
  "id": "F0",
  "name": "Ground",
  "level": 0,
  "elevation_m": 0.0,
  "source_path": "/absolute/path/to/ground.png",
  "alignment_confirmed": true,
  "calibration": {
    "point_a_px": [100, 100],
    "point_b_px": [500, 100],
    "distance_m": 10,
    "origin_m": [0, 0],
    "rotation_deg": 0
  }
}
```

The calibration numbers above are **example syntax**. Replace them with actual
measurements. `origin_m` is the building coordinate of `point_a_px`; choose
anchors/rotations so both floors occupy the same physical XY frame. The second
floor must have its own ID/image/calibration, actual integer level and measured
`elevation_m`. A level difference does not determine the vertical rise. Also
supply building ID/name and the actual license/attribution, or explicit `unknown`.
Do not set `alignment_confirmed:true` without checking the source alignment.

```bash
uv run python -m final_agent.workspace \
  --output agent_output/import-multifloor --model haiku
```

For repeatable direct tool inputs, save a JSON array of
`{"tool":"create_building_from_plan","input":{...}}` to a command file and
pass `--commands "/absolute/path/to/commands.json"` to that workspace command.
Use a normal chat resumed from its printed workspace to test conversation too.
`--commands` runs the registered tools directly; extraction still calls Claude,
but passing command mode does not prove conversational interpretation. A failing
command stops the file, so run negative cases separately.

Check the source overlays on **both** floors and review connector stop-space IDs
and paired floor IDs. Correct incomplete/uncertain stops explicitly from the
plans. After applying, test:

- Normal and step-free routes between floors; the selected stairs/lift and every
  endpoint floor must appear in the directions and maps.
- Lift closure: the normal route can use actual stairs; the step-free request
  must use another real accessible connector or be unreachable. Reopening must
  recover the retained request. Repeat after save/resume.
- Distinct floor levels versus elevations, including a negative or nonconsecutive
  level case. Vertical costs must use measured heights, not floor-number gaps.
- Equipment lookup/assignment on the intended floor, shared XY alignment,
  unchanged IDs after corrections, and export/reload of all floors/connectors.
- Missing alignment/elevations or cross-floor doors must not produce a supposedly
  valid navigable building. Repeat the full flow on an existing-building edit.

### 7. Run the short offline regression check and record the result

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests uv run python -m unittest \
  test_plan_build test_workspace test_map_display test_campus test_final_agent -q
```

This is free: model perception is mocked in the offline import tests. The tests
cover calibration, malformed/truncated responses, validation, edit persistence,
save rollback and routing/display integration; they do not establish extraction
accuracy or completion of the real multi-floor conversation above.

Keep a short report with source/model, actual phase timings, IDs, corrections,
reviewed warnings, committed paths/revisions, opened source/preview/route images,
reload/undo/closure results and every failed gate. Mark the import fully accepted
only when the real single-floor and multi-floor flows and their required failure
cases pass. The previous small live demo and its artifacts are in
[examples/level34/README.md](examples/level34/README.md).

## Training (build the run library)

**Build** (*paid*): `uv run python -m final_agent.train_runs`

It answers labelled questions and stores them in `final_agent/run_library.jsonl`. Correct
answers become examples for the benchmark agent. Questions that are already accepted are
skipped.

- default: 1 question per kind from `data/train` (9 questions)
- `--full`: every pending question; asks you to type `yes` first
- `--all`: also use `data/dev`. Don't use it if you measure on dev.
- `--model NAME`: `opus`, `sonnet` or `haiku` (default)
- `--library PATH`: default `final_agent/run_library.jsonl`

The first run with examples downloads the embedding model (~67 MB) to `~/.cache/fastembed`.
The Qdrant index of the accepted runs is saved in `final_agent/run_library.qdrant/` and
rebuilt automatically when the library or the embedding model changes; deleting the folder
is always safe.
