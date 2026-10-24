# Project agent

`final_agent` is independently runnable. Its CLI, conversation layer, tools, viewer,
evaluator, building map and storage all use package-local imports. It is the only
agent package: the kit's `starter_agent` was removed on 24 October 2026 after this
package was verified to contain all of its files, map functions and tools.

```bash
# Conversation (requires Claude API credentials)
uv run python -m final_agent data/dev/proc-factory-dev-003

# Free deterministic warm-up evaluation
uv run python -m final_agent.evaluate data/dev --oracle

# Scored benchmark using the project agent (uses API credits)
uv run python -m benchmark.evaluate data/dev --agent final_agent.benchmark:answer --name final-dev

# Storage and integration checks (no API calls)
uv run python -m unittest discover -s tests -v
```

The benchmark runner uses `final_agent.benchmark:answer` by default (`--agent` selects
another callable). Each adapter call loads a fresh map and
conversation and uses its own temporary output directory, removed after the reply.
The runner retains replies and scores. The adapter itself does not establish a live benchmark score; the map/tools now include
dedicated analyses for all nine scored question kinds.

Interactive edits and route images use `agent_output/`, or the directory passed
with `--output`. Closure snapshots and added doors are saved to `building_edited.json`.
Pass that file as the building argument to resume an edited map. Use distinct output
directories for concurrent interactive sessions.

`final_agent.storage` owns atomic JSON saves and per-floor spatial indexes. Invalid
map operations use the same `final_agent.building_map.MapError` class throughout the
agent tools and evaluator. Storage tests target this project implementation.

Historical verification after rewiring: **11 tests pass**, **369/369 oracle warm-up questions pass**,
and the built wheel's CLI, evaluator and benchmark adapter load without the starter
package. Integration tests reject starter imports, exercise actual tools
and image generation, and verify isolated benchmark edits. No live API evaluation
was performed.

Kit **1.1.0** is now integrated: corrected train/dev answers, door-to-door walking with
wall clearance, height-based stairs/lifts, direct lift rides and no outside shortcut.
Route outputs identify `distance_model="kit-1.1.0"`; every traversed space and selected
opening/connector is retained. The corrected dev oracle passes **369/369**. See the
root README for inherited geometry limitations. Current regressions: **176 run,
173 passed, 3 credential-dependent skips**; four sampled dev errands and all four
labelled what-if doors also pass with the corrected answers.

## Run library (retrieved worked examples)

A **run** is one answered benchmark question, kept in `final_agent/run_library.jsonl`
(committed, keyed by `question_id`): skill, kind, the agent's declared kind and
building-agnostic semantic translation, the full question, its tool calls (names and
arguments only, no results) and the reply. Runs never store the `answer`/`inputs` labels.
A run is **accepted** only if `benchmark.score.score_reply` marks the reply correct
**and** the agent's first `recall_examples` call declared the question's real kind.

`final_agent.benchmark:answer` gives the agent a `recall_examples(kind,
semantic_translation)` tool that it calls first. That call declares the kind and returns
up to three accepted runs of that kind, nearest by translation similarity: FastEmbed
`BAAI/bge-small-en-v1.5` vectors, cached in `~/.cache/fastembed`, in an in-memory Qdrant
collection that is rebuilt from the JSONL once per process. Chat has no recall tool.
`final_agent/embedding.py` is the adapter: to use a dedicated embedding server, add a
class implementing `Embedder` and return it from `default_embedder()`.

```bash
# Build (paid; the only code that reads answer labels). Only questions without an
# accepted run are pending, so a rerun retries rejected ones.
uv run python -m final_agent.train_runs                 # small: 1 train question per kind
uv run python -m final_agent.train_runs --all           # small sample from train + dev
uv run python -m final_agent.train_runs --full          # every pending question, after typing 'yes'
uv run python -m final_agent.train_runs --model claude-opus-5-5   # default claude-sonnet-5-5

# A/B on the same dev sample (keep the library train-only for this comparison)
uv run python -m benchmark.evaluate data/dev --agent final_agent.benchmark:answer_without_examples --per-kind 2 --name dev-runs-baseline
uv run python -m benchmark.evaluate data/dev --agent final_agent.benchmark:answer --per-kind 2 --name dev-runs-examples
```

Measured 24 October 2026. The committed library came from the small build on
claude-sonnet-5-5: all 9 train runs (one per kind) were accepted, estimated at $0.81. That
estimate uses the claude-opus-5-5 price table in `benchmark/evaluate.py`. The A/B ran on the same 17-question dev sample (2 per
kind, 1 `step_free_reachable_count`): the baseline scored **17/17** and the run with
examples **17/17**. This is a small sample, not a scored result. The baseline is already
perfect on it, so it shows no measurable effect of the examples. The evaluate log keeps
replies only, so it does not show whether `recall_examples` was called in each A/B
answer.

- [Complete challenge and implementation reference](../README.md)
- [Remaining implementation work](../BACKLOG.md)
- [Grading and submission](../README.md#1-the-challenge)
