# Benchmark request analysis — 20 buildings

Reviewed **280 dev questions: 93 scored and 187 warm-ups**, with three subagents dividing OSM, procedural campus/factory, and Swiss/ResPlan review. The balanced sample has **four buildings from each of five families**, **1–8 floors**, negative and nonconsecutive levels, **5–1,623 spaces**, and **20–5,250 assets**. Selection is deliberately varied, not random or weighted to estimate public-test accuracy.

**All 15 documented kinds occur; no new official kind was found.** All nine scored kinds still lack a complete exposed deterministic solution in the current `final_agent`. The six warm-up kinds have search/routing primitives, with exact inventory counts only partially supported. The important new findings concern expected-result semantics, eligibility, ambiguous source text, and missing route provenance.

| Deliverable | File |
|---|---|
| Question types, implemented status, existing and missing tools, expected results | [Coverage table](question_types.md), [CSV](question_types.csv) |
| Consolidated subtypes and overlapping edge characteristics | [Subtype table](question_subtypes.md), [CSV](question_subtypes.csv) |
| Necessary tools, suggested inputs/outputs and implementation order | [Tool plan](tools_needed.md) |
| Under-documented results, source ambiguities and remaining uncertainties | [Findings](new_request_types.md) |
| Representative tests: 15 easy, 15 medium, 15 hard | [Test table](tests.md), [machine-readable manifest](test_cases.json), [runner](run_tests.py) |
| Complete source-backed classification of every question | [280-row ledger](questions.csv) |
| Exact building selection and reasons | [20-building CSV](building_sample.csv), [JSON](buildings.json) |
| Recorded offline outcomes and implementation fingerprints | [Results](results.json), [sample counts](summary.json) |
| Independent subagent evidence | [OSM](reviews/osm.md), [procedural](reviews/procedural.md), [residential](reviews/residential.md) |

## Most consequential findings

- **Eligibility depends on the operation.** Typed area totals include matching warehouse/lobby halls; delivery counts exclude halls; shared-wall counts include factory hall bays; outdoor balconies remain valid asset pickup locations.
- **Errands select the nearest pickup first.** A shorter total pickup/delivery tour can be wrong: `swiss-460-H03` expects **15.72 m**, not **14.26 m**.
- **Counting search matches is unsafe.** The toilet query in `osm-way22744230-Q04` reports **7 matches** but expects **3 assets**. Larger inventories and area totals exceed the 15-result display page.
- **Topology matters beyond floor labels.** Same-floor step-free requests can be unreachable; local warm-up paths can leave and re-enter through the zero-cost outside node. Preserve that model separately from Synera's physical-route rules.
- **One request is underspecified.** `osm-way27917482-Q09` names three different rooms with the same name, reference and floor. The correct interaction is clarification; a labelled-ID oracle bypasses this issue.
- **Correct counts do not validate geometry.** The existing door insertion can happen to produce the expected what-if counts despite putting the door at a wall endpoint. Assert midpoint/contact and state isolation separately.

Full examples and expected values are in [findings](new_request_types.md). Labels in this folder are development fixtures, never production answer inputs.

## Run the selected tests

From the repository root, using the existing environment (`uv sync` if dependencies are not installed):

```bash
uv run python bench_analsysis/build_catalog.py
uv run python bench_analsysis/run_tests.py --results bench_analsysis/results.json
```

Run one tier or require implemented coverage:

```bash
uv run python bench_analsysis/run_tests.py --tier easy
uv run python bench_analsysis/run_tests.py --tier medium
uv run python bench_analsysis/run_tests.py --tier hard
uv run python bench_analsysis/run_tests.py --strict
```

Default **offline** mode performs no model/API calls. It executes real `final_agent` tool wrappers with resolved fixture inputs, checks route distance/room sequence or stop order, closure persistence, explicit unreachable errors, source-file preservation, asset lookup, and safe ambiguity rejection. It also runs six focused format checks through the unchanged `benchmark.score`.

`PASS` means that particular component assertion passed. `GAP` means the exposed capability is missing or insufficient; it **does not** count as a passing request. The current missing-tool map is an audit snapshot, not automatic discovery of future implementations. Default exit is nonzero for `FAIL`; `--strict` also exits nonzero for `GAP`. The hard duplicate-name case checks safe rejection, not successful completion of its labelled route.

The scored fixtures can also execute through a real answer callable. This path sends **only the original question text and building directory** to the production adapter, then scores its reply with the official scorer. It selects **23 scored cases** across the tiers; warm-up labels use a different contract and are excluded. This mode may consume API credits with the default adapter and was **not run** for this audit:

```bash
uv run --env-file .env python bench_analsysis/run_tests.py --mode agent --tier easy --agent final_agent.benchmark:answer --results bench_analsysis/live-easy.json
```

Remove `--tier easy` for all 23 scored representatives. A future deterministic `module:function` with signature `(building_directory, question_text) -> reply` can use the same mode without a model. `--question ID` restricts either mode to selected IDs and is repeatable. If Matplotlib cannot write its default cache in a sandbox, prefix the command with `MPLCONFIGDIR=/tmp/bench-analsysis-mpl`. If uv's normal cache is read-only, set `UV_CACHE_DIR=/tmp/bench-analsysis-uv`; the catalog command was also verified with this setting and `uv run --offline`.

## Verification recorded

On **24 October 2026**, using the existing `.venv/bin/python`:

| Check actually run | Result |
|---|---|
| Catalog rebuild and exact annotation/source coverage | **280/280 rows**, 20 buildings, 15 kinds; all representative IDs resolve |
| `bench_analsysis/run_tests.py` | **45 cases: 17 PASS, 28 GAP, 0 FAIL** |
| Official-scorer format regressions | **6/6 PASS** |
| Existing `python -m unittest discover -s tests -v` | **11/11 PASS** |

The 28 gaps comprise **23 scored cases and five exact-inventory-count cases**. All selected resolved-input lookup/route/closure/tour/safe-ambiguity probes pass. The reports also document additional label-informed geometry and route diagnostics performed by the subagents; those calculations do not add missing production tools.

No paid live benchmark, scored end-to-end accuracy, UI route review, new building ingestion, or Synera automatic-route compliance is claimed. The warm-up oracle cannot establish natural-language interpretation, and some source text cannot uniquely resolve its labelled answer. `results.json` records hashes of the inspected final-agent modules and official scorer so the audit can be compared with later changes.

## Rebuild and maintain

`buildings.json` is the fixed sample. The three `reviews/*_annotations.json` files preserve every subagent classification and note. `build_catalog.py` checks exact source coverage, normalizes subtype vocabulary, and regenerates the CSV/Markdown catalogs and test table; it never edits production data or the scorer. `test_cases.json` owns the representative selection and difficulty tiers, which are analysis judgments rather than organizer fields.

All inputs are from `data/dev`; no hidden labels or building-specific production answers were created. Building IDs, source paths and line numbers allow verification against the original data. Preserve the dataset attribution in [ATTRIBUTION.md](../ATTRIBUTION.md), especially if redistributing the OSM-derived fixtures. Root [README](../README.md) and [BACKLOG](../BACKLOG.md) remain the product requirements and task reference; the proposed tool APIs here are analysis recommendations.

## Update after implementation (24 Oct 2026)

The audit above is a snapshot from before the tools existed; its text is unchanged. After the feature work the same runner was rerun offline (no model or API calls, no credentials), now that all nine scored kinds have registered tools in `final_agent`:

| Run | Result |
|---|---|
| `python bench_analsysis/run_tests.py` (45 representatives, offline) | **45/45 PASS**, 0 GAP, 0 FAIL; 6/6 scorer-format checks |
| `python bench_analsysis/run_tests.py --mode components --split data/dev` | **138/138** scored dev questions |
| `python bench_analsysis/run_tests.py --mode components --split data/train` | **517/517** scored train questions |

Per kind, in the order dev / train: `largest_room` 20/20, 76/76; `floor_area_total` 31/31, 150/150; `straight_line_3d` 13/13, 17/17; `room_stacked` 9/9, 17/17; `shared_walls_count` 24/24, 119/119; `wide_delivery_count` 19/19, 61/61; `step_free_reachable_count` 1/1, 1/1; `errand` 19/19, 74/74; `what_if_door` 2/2, 2/2.

`--mode components` reads each labelled question's resolved `inputs`, calls the production tool and compares the result with the label, so it checks the tools only. It does not test question interpretation, the system prompt or the model's `Answer:` formatting, and it is not a live benchmark score; `--mode agent` (live, uses credits) was not run. The earlier gap table, tool plan and "missing tool" counts describe the audit-time state; the tool names are now registered (see [final_agent/README.md](../final_agent/README.md#tools)), and [BENCHMARK.md](../BENCHMARK.md) lists the commands and the remaining unverified live checks.
