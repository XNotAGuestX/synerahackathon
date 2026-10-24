# Benchmark request analysis — 20 dev buildings plus scarce-kind supplements

The original review covered **280 dev questions: 93 scored and 187 warm-ups**, with three subagents dividing OSM, procedural campus/factory, and Swiss/ResPlan review. The family-balanced dev sample has **four buildings from each of five families**, **1–8 floors**, negative and nonconsecutive levels, **5–1,623 spaces**, and **20–5,250 assets**. Selection is deliberately varied, not random or weighted to estimate public-test accuracy. The current ledger adds **three labelled train questions from one additional OSM building**, for **283 questions across 21 buildings**. Train supplements cover the two kinds whose dev supply is exhausted; they are explicitly marked and are development fixtures, not held-out evaluation.

**All 15 documented kinds occur; no new official kind was found.** All nine scored kinds still lack a complete exposed deterministic solution in the current `final_agent`. The six warm-up kinds have search/routing primitives, with exact inventory counts only partially supported. The important new findings concern expected-result semantics, eligibility, ambiguous source text, and missing route provenance.

| Deliverable | File |
|---|---|
| Question types, implemented status, existing and missing tools, expected results | [Coverage table](question_types.md), [CSV](question_types.csv) |
| Consolidated subtypes and overlapping edge characteristics | [Subtype table](question_subtypes.md), [CSV](question_subtypes.csv) |
| Necessary tools, suggested inputs/outputs and implementation order | [Tool plan](tools_needed.md) |
| Under-documented results, source ambiguities and remaining uncertainties | [Findings](new_request_types.md) |
| Representative tests: 20 easy, 28 medium, 23 hard | [Test table](tests.md), [machine-readable manifest](test_cases.json), [runner](run_tests.py) |
| Complete source-backed classification of every question | [283-row ledger](questions.csv) |
| Original 20-building dev selection and reasons | [20-building CSV](building_sample.csv), [JSON](buildings.json) |
| Recorded offline outcomes and implementation fingerprints | [Results](results.json), [sample counts](summary.json) |
| Independent subagent evidence | [OSM](reviews/osm.md), [procedural](reviews/procedural.md), [residential](reviews/residential.md) |

## Question balance

The original runnable selection was uneven: `count` and `route` had five cases each, but `step_free_reachable_count` had one and four other kinds had only two. **26 cases were added**, preserving all original cases, to bring the runnable selection from **45 to 71**:

- **13 of 15 kinds now have five distinct questions each.**
- **Lift-outage reachability: two cases**, all labelled train/dev examples available (one dev, one train).
- **Door what-if: four cases**, all labelled train/dev examples available (two dev, two train).

The target is five per kind; the remaining shortages are dataset limits. No invented labels or duplicate IDs fill them. Difficulty tiers follow the operation rather than equal quotas. [The balance table](tests.md#selection-balance), `question_types.csv` and `summary.json` show selected counts, labelled availability and remaining shortages. The catalog builder enforces this target on every rebuild.

The complete ledger retains all questions from the original dev buildings, so its raw distribution remains uneven (for example, 60 ordinary routes versus two lift-outage counts). **The runnable selection is the balanced analysis set**; the complete ledger is the source inventory. Neither is a live accuracy estimate.

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

The scored fixtures can also execute through a real answer callable. This path sends **the question text, supplied public kind and building directory** to the production adapter, then scores its reply with the official scorer. The kind is included in the question message; labelled inputs and expected answers are not sent. It selects **41 scored cases** across the tiers; warm-up labels use a different contract and are excluded. This mode may consume API credits with the default adapter and was **not run** for this audit:

```bash
uv run --env-file .env python bench_analsysis/run_tests.py --mode agent --tier easy --agent final_agent.benchmark:answer --results bench_analsysis/live-easy.json
```

Remove `--tier easy` for all 41 scored representatives. A future deterministic `module:function` with signature `(building_directory, question_text) -> reply` can use the same mode without a model. `--question ID` restricts either mode to selected IDs and is repeatable. If Matplotlib cannot write its default cache in a sandbox, prefix the command with `MPLCONFIGDIR=/tmp/bench-analsysis-mpl`. If uv's normal cache is read-only, set `UV_CACHE_DIR=/tmp/bench-analsysis-uv`; the catalog command was also verified with this setting and `uv run --offline`.

## Verification recorded

On **24 October 2026**, using the existing `.venv/bin/python`:

| Check actually run | Result |
|---|---|
| Catalog rebuild and exact annotation/source coverage | **283/283 rows**, 21 buildings, 15 kinds; all 71 representative IDs resolve |
| `bench_analsysis/run_tests.py` | **71 cases: 25 PASS, 46 GAP, 0 FAIL** |
| Official-scorer format regressions | **6/6 PASS** |
| Existing `python -m unittest discover -s tests -v` (original audit; not rerun for this selection change) | **11/11 PASS** |

The 46 gaps comprise **41 scored cases and five exact-inventory-count cases**. All selected resolved-input lookup/route/closure/tour/safe-ambiguity probes pass. The reports also document additional label-informed geometry and route diagnostics performed by the subagents; those calculations do not add missing production tools.

No paid live benchmark, scored end-to-end accuracy, UI route review, new building ingestion, or Synera automatic-route compliance is claimed. The warm-up oracle cannot establish natural-language interpretation, and some source text cannot uniquely resolve its labelled answer. `results.json` records hashes of the inspected final-agent modules and official scorer so the audit can be compared with later changes.

## Rebuild and maintain

`buildings.json` is the original fixed dev sample. The three `reviews/*_annotations.json` files preserve every subagent classification and note. `supplemental_annotations.json` records the three additional train questions and their source paths. `build_catalog.py` checks exact source coverage, case metadata/uniqueness and per-kind balance against all labelled train/dev supply, normalizes subtype vocabulary, and regenerates the CSV/Markdown catalogs and test table; it never edits production data or the scorer. `test_cases.json` owns the representative selection and difficulty tiers, which are analysis judgments rather than organizer fields.

Inputs are from `data/dev` plus the three explicitly marked `data/train` supplements; no hidden labels or building-specific production answers were created. Building IDs, source paths and line numbers allow verification against the original data. Preserve the dataset attribution in [ATTRIBUTION.md](../ATTRIBUTION.md), especially if redistributing the OSM-derived fixtures. Root [README](../README.md) and [BACKLOG](../BACKLOG.md) remain the product requirements and task reference; the proposed tool APIs here are analysis recommendations.
