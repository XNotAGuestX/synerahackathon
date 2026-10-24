# Run library: retrieved few-shot examples from accepted benchmark runs (revised)

## Context

Felix's meeting notes ("Task objects wip") ask for a **run**: one semantic section of work, carrying skill, kind, Claude's semantic translation of the question, the turns/tool calls after it, and whether it was accepted. Runs are filtered by skill → kind, then by semantic similarity, and only successful runs are shown to the agent. The goal is to "train" the agent on existing benchmark cases. Here that means retrieved few-shot examples, not fine-tuning. Today nothing records tool calls, nothing reuses past successes, and the repo has no embedding code (`qdrant-client`/`fastembed` are not installed).

This revision replaces the earlier plan on branch `worktree-run-library-plan` (`docs/superpowers/plans/2026-10-24-run-library.md`, commit `ddb58ca`). Changes from it: Qdrant + FastEmbed behind an embedder adapter, no same-building exclusion, the "Max" line removed, small/full/`--all` build modes, and a `--model` option.

## Decisions (from the meeting notes + Q&A, 24 Oct 2026)

| Topic | Decision |
|---|---|
| Run scope | Benchmark only for now: one question = one run. Splitting chats or multi-target questions into several runs is deferred. |
| Run record | `question_id, building_id, skill, kind, declared_kind, semantic_translation, question, tool_calls, reply, accepted`. `question_id` (from the data) is the key; question text and keywords are never IDs. |
| Kind + translation | The answering agent calls `recall_examples(kind, semantic_translation)` first. That call is its kind declaration and the retrieval query. Skill maps 1:1 to kind in the data, so filtering by kind also filters by skill. |
| Accepted | `benchmark.score.score_reply` marks the reply correct **and** `declared_kind == kind`. Only accepted runs are indexed, so only they reach the agent. |
| Example content | Each example: kind, skill, semantic translation, **full question**, tool calls, reply. Top 3. |
| Tool calls stored | Names + arguments only (no results). |
| Similarity | FastEmbed embeds the semantic translation, and Qdrant searches accepted runs with `kind` as a payload filter. No same-building exclusion. A question is only rebuilt while it is rejected, and rejected runs are never indexed, so a question never retrieves itself. |
| Embedding adapter | `Embedder` protocol; `FastEmbedEmbedder` now. A dedicated embedding server later means one new `HttpEmbedder` class plus a change to `default_embedder()`. Qdrant's built-in FastEmbed integration is deliberately not used, because it would couple the two. |
| Storage | `final_agent/run_library.jsonl` is the record, committed to git. Qdrant runs in embedded mode (`QdrantClient(":memory:")`) and is rebuilt from the JSONL once per process. Swapping the model therefore never leaves stale vectors, and moving to a Qdrant server changes one constructor line. |
| Build size | Default **small** mode: 1 question per kind (9 questions). `--full`: every pending question, after printing the count and model and waiting for a typed `yes`. Agents never run `--full`. |
| Build source | Default `data/train`. `--all` adds `data/dev` but leaves the size unchanged (small unless `--full`). A dev A/B comparison is only meaningful with a train-only library. |
| Build model | `--model`, default `claude-sonnet-5-5` (the agent's `MODEL`). |

## Global constraints

- The answer path (`final_agent.benchmark:answer`, `BuildingAgent`, `recall_examples`) never reads a question's `answer`/`inputs`. Only `final_agent/train_runs.py` reads labels, to accept runs.
- Stored runs contain no `answer`/`inputs` field. `benchmark/score.py` stays unchanged.
- Chat (`python -m final_agent <building>`) is unchanged: no index → no `recall_examples` tool and no examples prompt section.
- Reuse `benchmark.evaluate.load_questions`, `sample_per_kind`, `cost_dollars` and `benchmark.score.score_reply`; do not copy them.
- New dependencies, added via `uv add`: `qdrant-client`, `fastembed`.
- Kinds and skills, verbatim from the data: `largest_room`: `room geometry: area` · `floor_area_total`: `room geometry: summed area` · `straight_line_3d`: `3D geometry: centroids and floor elevations` · `room_stacked`: `3D stacking: polygon overlap between floors` · `shared_walls_count`: `wall adjacency from polygons` · `wide_delivery_count`: `door widths + reachability` · `step_free_reachable_count`: `reachability under constraints` · `errand`: `chain nearest-item, area and routing` · `what_if_door`: `what-if edit with effects on another floor`

## Files and interfaces

**`final_agent/embedding.py`** (new, the adapter)
- `class Embedder(Protocol)`: `dimension: int`; `embed(texts: list[str]) -> list[list[float]]`
- `class FastEmbedEmbedder`: `__init__(model_name: str = EMBEDDING_MODEL, cache_dir: Path = EMBEDDING_CACHE)`. Imports `fastembed.TextEmbedding` lazily, so chat and the offline tests don't need it. `dimension` comes from embedding one probe text once.
- `EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"`; `EMBEDDING_CACHE = Path.home() / ".cache" / "fastembed"` (FastEmbed's default temp dir is wiped on reboot).
- `default_embedder() -> Embedder`: the single swap point.

**`final_agent/run_library.py`** (new: records, file, index)
- `ScoredKind = Literal[...9 kinds...]`, `SKILL_BY_KIND: dict[str, str]`
- `@dataclass Run` with the fields above, in that order.
- `load_runs(path) -> list[Run]`: a missing file gives `[]`; a bad line raises `ValueError` starting with `f"{path}:{line}: "`. `save_runs(path, runs)`: UTF-8 JSONL sorted by `question_id`.
- `example_json(run) -> dict` with the keys `kind, skill, semantic_translation, question, tool_calls, reply`.
- `class RunIndex`: `__init__(runs: list[Run], embedder: Embedder)` creates an in-memory Qdrant collection (cosine, `size=embedder.dimension`) holding the **accepted** runs only. Point id = list position; payload = `{"kind": ...}`. `similar(kind: str, semantic_translation: str, limit: int = 3) -> list[Run]` uses `query_points` with a `FieldCondition(key="kind", match=MatchValue(value=kind))` filter.

**`final_agent/tools.py`**: `make_recall_tool(index: RunIndex) -> ArgumentCheckedTool`, registered like `make_tools` (`tools.py:62`). The tool is `recall_examples(kind: ScoredKind, semantic_translation: str) -> str` and returns `{"kind", "skill", "examples": [example_json...]}`, plus `"note": "No accepted example for this kind yet; solve it with the building tools."` when the list is empty. A blank translation raises `ToolError`.

**`final_agent/agent.py`**: `BuildingAgent.__init__(..., examples: RunIndex | None = None, model: str = MODEL)`. With an index, it registers the recall tool and appends `EXAMPLES_PROMPT` to the cached system block; `run_tool_loop` uses `self.model`. `tool_calls() -> list[dict]` returns `{"name", "input"}` for every `tool_use` block in `self.messages`, in order.

`EXAMPLES_PROMPT` (exact):
```
# Worked examples
- For a question that asks for a final 'Answer:' line, first call recall_examples once
  with its kind and a building-agnostic semantic translation.
- Examples are accepted runs from other questions. Reuse their tool sequence, argument
  style and answer format; never reuse their names, IDs or numbers.
- Every fact in your answer still comes from this building's tools.
```

`semantic_translation` argument description (exact; build and retrieval must share one style):
```
One building-agnostic sentence: the operation, its constraints and the required answer
format, with placeholders <space>, <asset>, <room_type>, <floor> instead of names and
numbers. Example: "nearest <asset> pickup from <space>, then largest <room_type> on
another floor, stairs allowed; answer total walking metres".
```

**`final_agent/benchmark.py`**: `RUN_LIBRARY_PATH = Path(__file__).with_name("run_library.jsonl")`; `run_index() -> RunIndex` (`functools.cache`, `load_runs` + `default_embedder()`); `answer(...)` passes `examples=run_index()`; `answer_without_examples(...)` passes `None` (the A/B baseline). The existing temp-dir and `MissingCredentialsError` handling moves into a shared private helper.

**`final_agent/train_runs.py`** (new CLI; reads labels, never imported by the answer path)
- `uv run python -m final_agent.train_runs [--full] [--all] [--model M] [--library PATH]`
- `make_run(question: dict, tool_calls: list[dict], reply: str) -> Run`: the **first** `recall_examples` input is the declaration (none → `declared_kind=None`, not accepted). Stored `tool_calls` exclude `recall_examples`.
- `require_labels(questions)` raises `SystemExit` if any question lacks `answer`. `pending_questions(questions, runs)` drops questions that already have an accepted run. `confirm_full(count: int, model: str, read=input) -> bool` is true only for the exact input `yes`.
- Loop: build a `RunIndex` once from the current library → for each pending question, a fresh `BuildingMap.load` and a `BuildingAgent(examples=index, model=model)` in a temp output dir → `ask` → `make_run` → replace the record by id → `save_runs` after **every** question. `anthropic.APIError` → print and skip (not recorded); `MissingCredentialsError` → exit. Print `N pending of M selected`, one line per question, then accepted/total per kind and `cost_dollars`.

**Tests** (minimal, offline, no model download). A tiny deterministic fake embedder (word-hash bag of words) proves the adapter can be swapped.
- `tests/test_run_library.py`: JSONL round trip, no label keys, missing file → `[]`, bad line names `path:line`; `RunIndex` returns only accepted runs of the requested kind, nearest first.
- `tests/test_recall_examples.py`: the tool returns examples, gives an empty list plus note for a kind without accepted runs, and raises `ToolError` for an unknown kind or blank translation. A scripted agent (`ScriptedClient` from `tests/test_hull.py`) has the tool only when given an index, and `tool_calls()` records the declaration and the next call. `answer` passes the index; `answer_without_examples` passes `None`.
- `tests/test_train_runs.py`: `make_run` accepts only a correct reply with a matching first declaration (cases: wrong number, wrong kind, no declaration, two declarations); `require_labels` exits on unlabelled questions; `pending_questions` skips accepted runs only; `confirm_full` accepts only `yes`.

## Execution: agentic workflow (≤ 5 agents, low verification)

Runs in the existing worktree `.claude/worktrees/run-library-plan` (branch `worktree-run-library-plan`). Load the `workflow-authoring` skill before writing the script. Agents do not commit; the integration agent commits per logical part.

1. **foundation** (1 agent): `uv add qdrant-client fastembed`, `embedding.py`, `run_library.py`, `tests/test_run_library.py`.
2. **in parallel after 1** (2 agents, disjoint files, coding against the interfaces above):
   - **agent-wiring**: `tools.py`, `agent.py`, `benchmark.py`, `tests/test_recall_examples.py`
   - **build-cli**: `train_runs.py`, `tests/test_train_runs.py`
3. **integration** (1 agent): full test suite and fixes; one real FastEmbed embed; paid small build (`uv run python -m final_agent.train_runs`, 9 train questions, Sonnet); paid dev A/B (`benchmark.evaluate data/dev --per-kind 2` with `:answer_without_examples` and `:answer`, 17 questions each); short "Run library" section in `final_agent/README.md` plus one BACKLOG line with the measured numbers; replace the old repo plan doc with this plan; commits.
4. **light review** (1 agent, read-only): one pass over the branch diff against the Global constraints (label isolation, no labels stored, `--full` needs a typed yes, embedder swap point, chat unchanged). It reports findings, and the main session fixes the trivial ones.

## Verification

- `uv run python -m unittest discover -s tests -v`: everything passes except the 3 existing credential-dependent skips.
- The small build prints `9 pending of 9 selected` on a fresh library. A second run lists only rejected questions as pending. `final_agent/run_library.jsonl` has no `answer`/`inputs` keys, and its accepted translations use placeholders.
- `--full` without typing `yes` exits before any API call (covered by the `confirm_full` test and one manual check with an `n` answer).
- The dev A/B prints both per-kind tables for the same 17 questions. The README records both numbers, labelled as a small sample rather than a scored result.
