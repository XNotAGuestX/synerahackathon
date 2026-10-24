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
opening/connector is retained. The corrected dev oracle passes **369/369**. See the
root README for inherited geometry limitations. Current regressions: **176 run,
173 passed, 3 credential-dependent skips**; four sampled dev errands and all four
labelled what-if doors also pass with the corrected answers.

- [Complete challenge and implementation reference](../README.md)
- [Remaining implementation work](../BACKLOG.md)
- [HTTP API configuration, contract and frontend fixtures](../docs/api/README.md)
- [Grading and submission](../README.md#1-the-challenge)
