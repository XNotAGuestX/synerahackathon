# Project agent

`final_agent` is independently runnable. Its CLI, conversation layer, tools, viewer,
evaluator, building map and storage all use package-local imports. It is the only
agent package: the kit's `starter_agent` was removed on 24 October 2026 after this
package was verified to contain all of its files, map functions and tools.

```bash
# Conversation (requires Claude API credentials)
uv run python -m final_agent data/dev/proc-factory-dev-003

# Frontend HTTP API (only /messages needs model credentials)
uv run python -m final_agent.api

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
opening/connector is retained. The warm-up evaluator shares only immutable walking lengths between fresh question maps.
The corrected dev oracle passes **369/369**. See the
root README for inherited geometry limitations. Current regressions: **177 run,
174 passed, 3 credential-dependent skips**; four sampled dev errands and all four
labelled what-if doors also pass with the corrected answers.

## Run library (retrieved worked examples)

A **run** is one answered benchmark question, kept in `final_agent/run_library.jsonl`
(committed, keyed by `question_id`): skill, kind, the agent's declared kind and
building-agnostic semantic translation, the full question, its tool calls (names and
arguments only, no results) and the reply. Runs never store the `answer`/`inputs` labels.
A run is **accepted** only if `benchmark.score.score_reply` marks the reply correct
**and** the agent's first `recall_examples` call declared the question's real kind with a
non-blank semantic translation.

Training builds, normal benchmark runs (including `answer_without_examples`) and
the analysis runner's agent mode now include the supplied public `kind` in the
model's question message. The agent uses that kind for `recall_examples` rather
than inferring it. Labelled `inputs` and expected `answer` stay outside the model
request. Saved questions retain their original wording. Direct Python callers can
use `answer(building_directory, question_text, kind="wide_delivery_count")`; calls
without a kind retain their previous behavior. Missing, null or empty kinds send
the original question text without a kind header, including in sampling and result
logging. Training uses the agent's recalled kind when no kind was supplied; if
neither supplies a valid kind, it logs a skip instead of indexing an unclassified
example. The two-argument callable contract
remains supported: benchmark runners include kind in the question text.

Verified 25 October 2026: 21 focused offline checks pass, including scripted model
requests from the actual training and benchmark entry points, baseline runs and
public test-shaped records without labels and omitted/null/empty kinds. No paid
model rerun is claimed.

`final_agent.benchmark:answer` gives the agent a `recall_examples(kind,
semantic_translation)` tool that it calls first. That call declares the kind and returns
up to three accepted runs of that kind, nearest by translation similarity: FastEmbed
`BAAI/bge-small-en-v1.5` vectors, cached in `~/.cache/fastembed`, in a Qdrant collection
saved in `final_agent/run_library.qdrant/` (git-ignored, next to the `--library` file).
Later runs reuse it while the accepted runs and the embedding model are unchanged and
rebuild it otherwise. Local Qdrant allows one process per folder, so a second concurrent
run warns and uses an in-memory copy. Chat has no recall tool.
`final_agent/embedding.py` is the adapter: to use a dedicated embedding server, add a
class implementing `Embedder` and return it from `default_embedder()`.

```bash
# Build (paid; the only code that reads answer labels). Only questions without an
# accepted run are pending, so a rerun retries rejected ones.
uv run python -m final_agent.train_runs                 # small: 1 train question per kind
uv run python -m final_agent.train_runs --all           # small sample from train + dev
uv run python -m final_agent.train_runs --full          # every pending question, after typing 'yes'
uv run python -m final_agent.train_runs --model sonnet  # opus, sonnet or haiku (default)

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

On 25 October 2026 `answer` on claude-haiku-5-5 also scored **17/17** on that sample, for
about $0.04 in total (about 1/20 of Sonnet's cost), so Haiku is now the default model for
every command. Pick another one with `--model opus` or `--model sonnet`. Haiku has no
server-side fallback, so only Opus and Sonnet requests send `fallbacks`.

- [Complete challenge and implementation reference](../README.md)
- [Remaining implementation work](../BACKLOG.md)
- [HTTP API configuration, contract and frontend fixtures](../docs/api/README.md)
- [Grading and submission](../README.md#1-the-challenge)
