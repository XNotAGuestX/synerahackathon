# Run Library (retrieved few-shot from accepted benchmark runs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every benchmark question the agent answers as a *run*. Keep the scorer-accepted runs from `data/train` in a file-based library. When the agent answers a new question, hand it the most similar accepted runs of the same kind as worked examples.

**Architecture:** `final_agent/run_library.py` owns the `Run` record, JSONL load/save and ranking. A new tool `recall_examples(kind, semantic_translation)` is both the agent's kind declaration and the retrieval call. `BuildingAgent` registers it only when it is given a library, so chat is unchanged. `final_agent/train_runs.py` builds the library by running the live agent on labelled train questions. `final_agent.benchmark:answer` uses the library; `answer_without_examples` is the A/B baseline.

**Tech Stack:** Python 3.12 stdlib (`json`, `dataclasses`, `re`, `functools`), existing anthropic tool runner, `unittest` with the `ScriptedClient` from `tests/test_hull.py`.

**Spec:** the *Decisions* section below: Felix's "Task objects wip" notes plus the Q&A of 24 October 2026.

## Decisions (spec)

| Topic | Decision |
|---|---|
| Run | One semantic section. **Scope now: benchmark only, one question = one run.** Splitting a chat or a multi-target question into several runs is deferred. |
| Run fields | `question_id, building_id, skill, kind, declared_kind, semantic_translation, question, tool_calls, reply, accepted` |
| Identity | `question_id` from the data is the key. Question text, hashes and keywords are not IDs. The semantic translation is only a retrieval index. |
| "Train the model" | Retrieved few-shot; no fine-tuning. Each example handed to the agent contains its kind, skill, semantic translation, **full question**, tool calls and reply. |
| Filtering | kind first, then semantic similarity. Skill maps 1:1 to kind in train/dev, so filtering by kind also filters by skill. |
| Semantic translation | Written by Claude: one building-agnostic sentence with placeholders. |
| Similarity | Token Jaccard over semantic translations (stdlib); ties go to the lower `question_id`. |
| Accepted | `benchmark.score.score_reply` marks the reply correct **and** `declared_kind == kind` (the label). Only accepted runs reach the agent; all runs are stored for analysis. |
| Max's shared task object | Not adopted: runs are separate records aggregated at query time (kind → similarity) rather than one shared, mutable object. |
| Storage | `final_agent/run_library.jsonl`, committed, UTF-8 JSONL sorted by `question_id`. No database. |
| Qdrant (Docker) + FastEmbed | Not adopted now. The library holds ≤ 517 train runs, and the questions are template-generated, so within one kind the translations differ only in subtype words (same/other floor, step-free, above/below). Token overlap captures that, and a linear scan takes milliseconds. A Docker service would become a prerequisite for every benchmark and submission run on every teammate's machine, and AGENTS.md asks for local, file-based persistence unless a feature requires more. Upgrade path: if Task 5 shows wrong-subtype examples, replace the body of `similar_runs` with in-process FastEmbed first; add Qdrant only if the library outgrows a scan. |

## Global Constraints

- The production answer path (`final_agent.benchmark:answer`, `BuildingAgent`, `recall_examples`) never reads a question's `answer` or `inputs`. Only `final_agent/train_runs.py` reads labels, and only to accept runs.
- Build the library from `data/train` only. `data/dev` stays held out for measurement; `data/test` has no labels.
- `recall_examples` never returns a run whose `building_id` equals the current `building_map.data["building"]["id"]`.
- A stored run has no `answer` or `inputs` field.
- `benchmark/score.py` stays unchanged. Reuse `benchmark.evaluate.load_questions`, `sample_per_kind`, `cost_dollars` and `benchmark.score.score_reply`; do not copy them.
- No new dependency.
- Interactive chat (`python -m final_agent <building>`) is unchanged: without a library there is no `recall_examples` tool and no examples prompt section.
- Kinds and skills, verbatim from the data (all 9 scored kinds):
  `largest_room`: `room geometry: area` · `floor_area_total`: `room geometry: summed area` · `straight_line_3d`: `3D geometry: centroids and floor elevations` · `room_stacked`: `3D stacking: polygon overlap between floors` · `shared_walls_count`: `wall adjacency from polygons` · `wide_delivery_count`: `door widths + reachability` · `step_free_reachable_count`: `reachability under constraints` · `errand`: `chain nearest-item, area and routing` · `what_if_door`: `what-if edit with effects on another floor`
- Paid API calls happen only in Task 4 step 6 and Task 5 step 1. **Ask Felix before running either.**

## Review Focus

1. The agent never calls `recall_examples`, or calls it twice with different kinds → no declaration means not accepted; the first call is the declaration (Task 4 test).
2. `train_runs` is pointed at an unlabelled split such as `data/test` → it exits with a clear message before any API call (Task 4 test).
3. A fresh clone has no `run_library.jsonl` → `answer` still works and the tool returns no examples plus a note (Task 1 and Task 2 tests).
4. A kind has no accepted run (train has 1 `step_free_reachable_count` and 2 `what_if_door` questions) → empty examples with a note, and the agent solves the question with the building tools (Task 2 test).
5. The build is re-run → questions that already have an accepted run are skipped, so no credits are spent twice; rejected ones are retried (Task 4 test).

## File Structure

- Create `final_agent/run_library.py`: `Run`, `ScoredKind`, `SKILL_BY_KIND`, `load_runs`, `save_runs`, `similar_runs`, `example_json`. Production side; never reads labels.
- Modify `final_agent/tools.py`: add `make_recall_tool`.
- Modify `final_agent/agent.py`: `BuildingAgent(..., examples=None)`, `EXAMPLES_PROMPT`, `BuildingAgent.tool_calls()`.
- Modify `final_agent/benchmark.py`: `RUN_LIBRARY_PATH`, `library_runs`, `answer`, `answer_without_examples`.
- Create `final_agent/train_runs.py`: the label-reading library builder (CLI).
- Create `final_agent/run_library.jsonl`: generated in Task 4 and committed.
- Create `tests/test_run_library.py`: all new tests.
- Modify `final_agent/README.md` and `BACKLOG.md`: Task 5.

---

### Task 1: Run record, storage and ranking

**Files:**
- Create: `final_agent/run_library.py`
- Test: `tests/test_run_library.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `ScoredKind = Literal["largest_room", "floor_area_total", "straight_line_3d", "room_stacked", "shared_walls_count", "wide_delivery_count", "step_free_reachable_count", "errand", "what_if_door"]`
  - `SKILL_BY_KIND: dict[str, str]`: the 9 pairs from Global Constraints.
  - `@dataclass class Run` with fields in this order: `question_id: str, building_id: str, skill: str, kind: str, declared_kind: str | None, semantic_translation: str, question: str, tool_calls: list[dict], reply: str, accepted: bool`
  - `load_runs(path: Path) -> list[Run]`: a missing file gives `[]`; a malformed line raises `ValueError` whose message starts with `f"{path}:{line_number}: "`.
  - `save_runs(path: Path, runs: Iterable[Run]) -> None`: one `json.dumps(asdict(run), ensure_ascii=False)` per line, sorted by `question_id`, UTF-8.
  - `similar_runs(runs: list[Run], kind: str, semantic_translation: str, exclude_building: str, limit: int = 3) -> list[Run]`
  - `example_json(run: Run) -> dict` with exactly the keys `kind, skill, semantic_translation, question, tool_calls, reply`.

- [ ] **Step 1: Write the failing tests** in `tests/test_run_library.py`

```python
def sample_run(question_id, building="b1", kind="errand", text="nearest <asset> then largest <room_type> other floor step free", accepted=True):
    return Run(question_id, building, SKILL_BY_KIND[kind], kind, kind, text, f"question {question_id}", [], "Answer: 1", accepted)

class RunLibraryTests(unittest.TestCase):
    def test_kinds_and_skills_agree(self):
        self.assertEqual(set(get_args(ScoredKind)), set(SKILL_BY_KIND))

    def test_similar_runs_filters_kind_acceptance_building_then_ranks(self):
        runs = [
            sample_run("q1", text="nearest <asset> then largest <room_type> same floor stairs allowed"),
            sample_run("q2"),
            sample_run("q3", accepted=False),
            sample_run("q4", building="here"),
            sample_run("q5", kind="largest_room"),
            sample_run("q0"),  # identical text to q2: tie goes to the lower id
        ]
        found = similar_runs(runs, "errand", "nearest <asset> then largest <room_type> other floor step free", "here")
        self.assertEqual([run.question_id for run in found], ["q0", "q2", "q1"])
        self.assertEqual(similar_runs(runs, "what_if_door", "anything", "here"), [])

    def test_round_trip_keeps_fields_and_stores_no_labels(self):
        # save [sample_run("q2"), sample_run("q1")] to a temp file, then:
        # load_runs(path) == [sample_run("q1"), sample_run("q2")]
        # set(json.loads(first_line)) == {field.name for field in fields(Run)}; "answer" and "inputs" not in it
        ...

    def test_missing_file_is_empty_and_bad_line_names_its_location(self):
        # load_runs(tmp / "none.jsonl") == []
        # write '{"question_id": "q1"}\n' to tmp / "runs.jsonl": ValueError whose message contains "runs.jsonl:1: "
        ...
```

The two `...` tests must assert exactly what their comments state.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run python -m unittest discover -s tests -p test_run_library.py -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'final_agent.run_library'`

- [ ] **Step 3: Implement `final_agent/run_library.py`** using the Interfaces above. Tokens are `set(re.findall(r"\w+", text.lower()))`, so `<room_type>` becomes `room_type`. Score is `len(a & b) / len(a | b)`, or 0 when both sets are empty. Sort by `(-score, question_id)`. Filter in this order: `accepted`, then `kind ==`, then `building_id != exclude_building`. `load_runs` builds `Run(**record)` and turns `json.JSONDecodeError`/`TypeError` into the located `ValueError`.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `uv run python -m unittest discover -s tests -p test_run_library.py -v`
Expected: 4 tests OK

- [ ] **Step 5: Commit**

```bash
git add final_agent/run_library.py tests/test_run_library.py
git commit -m "Run library: run record, JSONL storage and kind-then-semantics ranking"
```

---

### Task 2: `recall_examples` tool and agent wiring

**Files:**
- Modify: `final_agent/tools.py` (new function after `make_tools`)
- Modify: `final_agent/agent.py` (`BuildingAgent.__init__`, new `tool_calls`, new `EXAMPLES_PROMPT`)
- Test: `tests/test_run_library.py`

**Interfaces:**
- Consumes: `Run`, `ScoredKind`, `SKILL_BY_KIND`, `similar_runs`, `example_json` (Task 1).
- Produces:
  - `make_recall_tool(runs: list[Run], building_id: str) -> ArgumentCheckedTool`. The tool is `recall_examples(kind: ScoredKind, semantic_translation: str) -> str` and returns `as_json({"kind": kind, "skill": SKILL_BY_KIND[kind], "examples": [example_json(run) for run in similar_runs(runs, kind, semantic_translation, building_id)]})`, plus a `"note"` of `"No accepted example for this kind yet; solve it with the building tools."` when `examples` is empty. A blank `semantic_translation` raises `ToolError`.
  - `BuildingAgent.__init__(self, building_map, output_directory, client=None, examples: list[Run] | None = None)`. When `examples is not None`, it appends `make_recall_tool(examples, building_map.data["building"]["id"])` to `self.tools` and appends `EXAMPLES_PROMPT` to the system text, inside the existing cached block.
  - `BuildingAgent.tool_calls(self) -> list[dict]`: `{"name": block.name, "input": block.input}` for every `tool_use` block of every assistant message in `self.messages`, in order, including `recall_examples`.

Exact copy for `EXAMPLES_PROMPT`:

```
# Worked examples
- For a question that asks for a final 'Answer:' line, first call recall_examples once
  with its kind and a building-agnostic semantic translation.
- Examples are accepted runs from other buildings. Reuse their tool sequence, argument
  style and answer format; never reuse their names, IDs or numbers.
- Every fact in your answer still comes from this building's tools.
```

Exact copy for the `semantic_translation` argument description. It must stay identical between build and retrieval, because similarity depends on a consistent style:

```
One building-agnostic sentence: the operation, its constraints and the required answer
format, with placeholders <space>, <asset>, <room_type>, <floor> instead of names and
numbers. Example: "nearest <asset> pickup from <space>, then largest <room_type> on
another floor, stairs allowed; answer total walking metres".
```

- [ ] **Step 1: Write the failing tests**, importing `ScriptedClient, call, reply, say, BUILDING` from `test_hull`

```python
def test_recall_tool_excludes_own_building_and_reports_empty_kind(self):
    tool = make_recall_tool([sample_run("q1", kind="largest_room"), sample_run("q2", building="proc-factory-dev-003", kind="largest_room")], "proc-factory-dev-003")
    result = json.loads(tool.call({"kind": "largest_room", "semantic_translation": "largest <room_type> on <floor>"}))
    self.assertEqual([example["question"] for example in result["examples"]], ["question q1"])
    self.assertEqual(result["skill"], "room geometry: area")
    empty = json.loads(tool.call({"kind": "what_if_door", "semantic_translation": "door between <space> and <space>"}))
    self.assertEqual(empty["examples"], [])
    self.assertIn("note", empty)
    for bad in ({"kind": "volume", "semantic_translation": "x"}, {"kind": "errand", "semantic_translation": "  "}):
        with self.subTest(bad=bad), self.assertRaises(ToolError):
            tool.call(bad)

def test_agent_offers_recall_only_with_examples_and_records_tool_calls(self):
    # Without examples: "recall_examples" not in [tool.name for tool in agent.tools]; "# Worked examples" not in agent.system[0]["text"].
    # With examples=[sample_run("q1", kind="largest_room")] and a ScriptedClient turn of
    #   reply(call("recall_examples", kind="largest_room", semantic_translation="largest <room_type> on <floor>; name and area")),
    #   reply(call("find_largest_room", room_type="office", floor_level=0)),
    #   reply(say("Office 0.30, 29.55 m2.\nAnswer: Office 0.30, 29.55")),
    # agent.ask("Which is the largest office on the ground floor?") then:
    #   agent.tool_calls() == [{"name": "recall_examples", "input": {...as scripted...}},
    #                          {"name": "find_largest_room", "input": {"room_type": "office", "floor_level": 0}}]
    #   client.results[0] == ("recall_examples", False, <text containing "question q1">)
    #   "# Worked examples" in agent.system[0]["text"]
    ...
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run python -m unittest discover -s tests -p test_run_library.py -v`
Expected: the 2 new tests ERROR with `ImportError` for `make_recall_tool`; Task 1 tests still OK

- [ ] **Step 3: Implement `make_recall_tool`, `EXAMPLES_PROMPT`, the `examples` parameter and `tool_calls`** as specified in Interfaces. Register the tool with `ArgumentCheckedTool`, like `make_tools` does. The `Literal` annotation gives the model an enum and makes unknown kinds a `ToolError`.

- [ ] **Step 4: Run the new tests and the existing agent tests**

Run: `uv run python -m unittest discover -s tests -p "test_*.py" -k run_library -k hull -k final_agent -v`
Expected: all OK (3 credential-dependent skips allowed in `test_hull`)

- [ ] **Step 5: Commit**

```bash
git add final_agent/tools.py final_agent/agent.py tests/test_run_library.py
git commit -m "recall_examples: declare kind and semantic translation, return similar accepted runs"
```

---

### Task 3: Benchmark adapter uses the library

**Files:**
- Modify: `final_agent/benchmark.py`
- Test: `tests/test_run_library.py`

**Interfaces:**
- Consumes: `load_runs`, `Run` (Task 1); `BuildingAgent(..., examples=)` (Task 2).
- Produces:
  - `RUN_LIBRARY_PATH = Path(__file__).with_name("run_library.jsonl")`
  - `library_runs() -> list[Run]`: `functools.cache`d `load_runs(RUN_LIBRARY_PATH)`; loaded once per process.
  - `answer(building_directory: Path, question_text: str) -> str`: passes `examples=library_runs()`.
  - `answer_without_examples(building_directory: Path, question_text: str) -> str`: passes `examples=None`; this is today's behaviour, used as the A/B baseline.
  - Both delegate to a private helper that holds the existing `TemporaryDirectory` and `MissingCredentialsError` handling, unchanged.

- [ ] **Step 1: Write the failing test**

```python
def test_answer_uses_library_and_baseline_does_not(self):
    # patch("final_agent.benchmark.library_runs", return_value=[sample_run("q1")]) and
    # patch("final_agent.benchmark.BuildingAgent") whose instance .ask returns "Answer: 1";
    # answer(BUILDING, "q") -> the mock's call kwargs["examples"] == [sample_run("q1")]
    # answer_without_examples(BUILDING, "q") -> kwargs["examples"] is None
    ...
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run python -m unittest discover -s tests -p test_run_library.py -k baseline -v`
Expected: ERROR, `ImportError` for `answer_without_examples`

- [ ] **Step 3: Implement** the Interfaces in `final_agent/benchmark.py`.

- [ ] **Step 4: Run the full suite.** `test_benchmark_callable_isolates_maps_conversations_and_outputs` and `test_benchmark_answer_stops_the_run_without_credentials` must stay green while no library file exists.

Run: `uv run python -m unittest discover -s tests -v`
Expected: OK; the only skips are the 3 credential-dependent ones

- [ ] **Step 5: Commit**

```bash
git add final_agent/benchmark.py tests/test_run_library.py
git commit -m "Benchmark adapter: answer with run-library examples; answer_without_examples baseline"
```

---

### Task 4: Build the library from train (`train_runs`)

**Files:**
- Create: `final_agent/train_runs.py`
- Create: `final_agent/run_library.jsonl` (step 6, paid)
- Test: `tests/test_run_library.py`

**Interfaces:**
- Consumes: `Run`, `load_runs`, `save_runs` (Task 1); `BuildingAgent(..., examples=)` and `.tool_calls()`, `.usage` (Task 2); `RUN_LIBRARY_PATH` (Task 3); `benchmark.evaluate.load_questions`, `sample_per_kind`, `cost_dollars`; `benchmark.score.score_reply`.
- Produces:
  - `make_run(question: dict, tool_calls: list[dict], reply: str) -> Run`. The declaration is the input of the **first** `recall_examples` call: `declared_kind=None` and `semantic_translation=""` when there is none. The stored `tool_calls` exclude `recall_examples` calls. `skill` and `kind` come from the question. `accepted = score_reply(question["answer"], reply) and declared_kind == question["kind"]`.
  - `require_labels(questions: list[tuple[Path, dict]]) -> None`: raises `SystemExit("train_runs needs labelled questions; build from data/train.")` if any question lacks `"answer"`.
  - `pending_questions(questions: list[tuple[Path, dict]], runs: list[Run]) -> list[tuple[Path, dict]]`: drops questions whose id already has an accepted run.
  - `build(directory: Path, library: Path, per_kind: int | None, kinds: list[str] | None) -> None`
  - CLI: `uv run python -m final_agent.train_runs data/train [--per-kind N] [--kinds K ...] [--library PATH]`; the default library is `RUN_LIBRARY_PATH`.

`build` loop: load and filter questions → `require_labels` → `sample_per_kind` → `pending_questions` → for each question, a fresh `BuildingMap.load` and a `BuildingAgent` in a temporary output directory with `examples=` the current accepted runs → `ask` → `make_run` → replace the record by `question_id` → `save_runs` **after every question**, so an abort keeps progress. On `anthropic.APIError`, print the error and skip the question without recording it, so it is retried next build. On `MissingCredentialsError`, raise `SystemExit`. Print `N pending of M sampled` first, then one line per question (`id`, label kind, `ACCEPTED`/`rejected`, declared kind), then accepted/total per kind and `cost_dollars` of the summed usage.

- [ ] **Step 1: Write the failing tests**

```python
QUESTION = {"id": "b1-H02", "building_id": "b1", "kind": "floor_area_total", "skill": "room geometry: summed area",
            "question": "Total generic room area on floor 4? Finish with a line 'Answer: <number>'.",
            "answer": {"type": "number", "value": 10.0, "unit": "m2", "relative_tolerance": 0.05, "absolute_tolerance": 0.0}}
DECLARE = {"name": "recall_examples", "input": {"kind": "floor_area_total", "semantic_translation": "sum <room_type> area on <floor>"}}
SUM = {"name": "sum_floor_area", "input": {"room_type": "generic_room", "floor_level": 4}}
WRONG_KIND = {"name": "recall_examples", "input": {"kind": "largest_room", "semantic_translation": "largest <room_type> on <floor>"}}

def test_make_run_accepts_only_a_correct_reply_with_the_declared_label_kind(self):
    run = make_run(QUESTION, [DECLARE, SUM], "Answer: 10.2")
    self.assertTrue(run.accepted)
    self.assertEqual((run.declared_kind, run.semantic_translation, run.tool_calls), ("floor_area_total", "sum <room_type> area on <floor>", [SUM]))
    self.assertFalse(make_run(QUESTION, [DECLARE, SUM], "Answer: 20").accepted)
    self.assertFalse(make_run(QUESTION, [WRONG_KIND, SUM], "Answer: 10.2").accepted)
    undeclared = make_run(QUESTION, [SUM], "Answer: 10.2")
    self.assertEqual((undeclared.declared_kind, undeclared.accepted), (None, False))
    self.assertEqual(make_run(QUESTION, [DECLARE, WRONG_KIND, SUM], "Answer: 10.2").declared_kind, "floor_area_total")

def test_unlabelled_questions_stop_before_any_call(self):
    with self.assertRaises(SystemExit):
        require_labels([(Path("x"), {key: value for key, value in QUESTION.items() if key != "answer"})])

def test_pending_skips_only_accepted_runs(self):
    questions = [(Path("x"), {**QUESTION, "id": question_id}) for question_id in ("q1", "q2", "q3")]
    pending = pending_questions(questions, [sample_run("q1"), sample_run("q2", accepted=False)])
    self.assertEqual([question["id"] for _, question in pending], ["q2", "q3"])
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run python -m unittest discover -s tests -p test_run_library.py -v`
Expected: the 3 new tests ERROR with `ModuleNotFoundError: final_agent.train_runs`

- [ ] **Step 3: Implement `final_agent/train_runs.py`** per Interfaces. Its module docstring must say that it reads train labels only to accept runs and is never imported by the answer path.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `uv run python -m unittest discover -s tests -p test_run_library.py -v`
Expected: all OK

- [ ] **Step 5: Commit the code**

```bash
git add final_agent/train_runs.py tests/test_run_library.py
git commit -m "train_runs: build the run library from labelled train questions"
```

- [ ] **Step 6 (paid, ask Felix first): Build and inspect the library**

Run: `uv run --env-file .env python -m final_agent.train_runs data/train --per-kind 5`
Expected: 38 questions (5 per kind; train has only 1 `step_free_reachable_count` and 2 `what_if_door`); a per-kind accepted summary and a cost line. Open `final_agent/run_library.jsonl` and check three things. Accepted semantic translations contain placeholders, not building names or numbers. No record has `answer` or `inputs`. Each kind except possibly the two scarce ones has at least one accepted run. Re-running the same command must report only the rejected questions as pending.

- [ ] **Step 7: Commit the library**

```bash
git add final_agent/run_library.jsonl
git commit -m "Run library: accepted train runs (per-kind 5)"
```

---

### Task 5: Measure on dev and document

**Files:**
- Modify: `final_agent/README.md`, `BACKLOG.md`

**Interfaces:**
- Consumes: `final_agent.benchmark:answer` and `:answer_without_examples` (Task 3), the library (Task 4).
- Produces: a recorded A/B result.

- [ ] **Step 1 (paid, ask Felix first): Run both adapters on the same dev sample**

```bash
uv run --env-file .env python -m benchmark.evaluate data/dev --agent final_agent.benchmark:answer_without_examples --per-kind 2 --name dev-runs-baseline
uv run --env-file .env python -m benchmark.evaluate data/dev --agent final_agent.benchmark:answer --per-kind 2 --name dev-runs-examples
```

Expected: both runs print the per-kind `correct / total` table for the same 17 questions (seed 7). The library is train-only, so dev stays unseen.

- [ ] **Step 2: Inspect the failures** in `agent_output/benchmark/dev-runs-examples.jsonl`. For each wrong answer, note whether the declared kind was wrong, whether the retrieved examples had the wrong subtype (which would justify the FastEmbed upgrade in `similar_runs`), or whether the cause lies elsewhere.

- [ ] **Step 3: Document.** Add a short "Run library" section to `final_agent/README.md`: what a run is, the build command, the A/B commands and the measured baseline vs. examples numbers. Add one BACKLOG line recording the measured result and its limits (a 2-per-kind sample is not a scored benchmark result). Keep both factual, with no unrun claims.

- [ ] **Step 4: Run the full suite**

Run: `uv run python -m unittest discover -s tests -v`
Expected: OK; the only skips are the 3 credential-dependent ones

- [ ] **Step 5: Commit**

```bash
git add final_agent/README.md BACKLOG.md
git commit -m "Document the run library and its dev A/B measurement"
```

## Deferred (out of scope for this plan)

- Splitting a chat, or a question with multiple semantic targets, into several runs, plus chat-side recording and user-confirmed acceptance.
- Per-kind aggregate playbooks in the system prompt.
- FastEmbed/Qdrant retrieval (upgrade path in Decisions).
