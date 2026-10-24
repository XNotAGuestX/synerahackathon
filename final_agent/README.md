# Project agent

`final_agent` is independently runnable. Its CLI, conversation layer, tools, viewer,
evaluator, building map and storage all use package-local imports. It has no runtime
dependency on `starter_agent`; the wheel includes both packages so the starter remains
available as a baseline.

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

The benchmark runner defaults to the starter; select the project explicitly with
`--agent final_agent.benchmark:answer`. Each adapter call loads a fresh map and
conversation and uses its own temporary output directory, removed after the reply.
The runner retains replies and scores. The adapter does not add the nine missing
scored-analysis tools or establish a live benchmark score.

Interactive edits and route images use `agent_output/`, or the directory passed
with `--output`. Closure snapshots and added doors are saved to `building_edited.json`.
Pass that file as the building argument to resume an edited map. Use distinct output
directories for concurrent interactive sessions.

`final_agent.storage` owns atomic JSON saves and per-floor spatial indexes. Invalid
map operations use the same `final_agent.building_map.MapError` class throughout the
agent tools and evaluator. Storage tests target this project implementation; the
original starter map retains its original storage/spatial limitations.

Verified after rewiring: **11 tests pass**, **369/369 oracle warm-up questions pass**,
and the built wheel's CLI, evaluator and benchmark adapter load with the starter
package removed. Integration tests reject starter imports, exercise actual tools
and image generation, and verify isolated benchmark edits. No live API evaluation
was performed.

- [Complete challenge and implementation reference](../README.md)
- [Remaining implementation work](../BACKLOG.md)
- [Grading and submission](../README.md#1-the-challenge)
