# Working in this repository

## Goal and priorities

Build **Talk to Your Building**: an agent that finds rooms and equipment, shows them
on a map, computes valid routes, reacts to closures, and creates or updates buildings
from plans. This is a hackathon. Ship the smallest complete solution that works;
keep the codebase small and easy for teammates to understand.

- Read the consolidated [README.md](README.md) for requirements, data contracts,
  scoring rules and the 25 October compliance status. Use [BACKLOG.md](BACKLOG.md)
  for stable task IDs. Execute open challenge gaps from
  [docs/TODOLIST-2026-10-25.md](docs/TODOLIST-2026-10-25.md). Update these when
  behavior or verified status changes; avoid duplicating the backlog here.
- Prioritize working functionality (55 points), usable interaction (25), then
  creativity (10) and a clear submission demo (10).
- Deliver in small end-to-end slices: locate on a usable 2D map; constrained routing
  and closure/reroute; multiple floors and buildings; plan ingestion, correction and
  export. Levels 1–4 are required. Finish one optional extension only if time allows.
- Work on deterministic benchmark tools alongside the usable app. Cover all nine
  scored question kinds; start with areas and straightforward geometry for quick,
  measurable progress. A benchmark score alone does not complete the product.

## Keep implementation simple and clean

- Make the smallest coherent change that meets the task's acceptance criteria.
  Complete input → computation → usable output before expanding scope.
- Use clear names, short focused functions, explicit inputs/outputs and type hints
  for interfaces. Follow existing Python conventions and module boundaries.
- Keep responsibilities clear: conversation in `agent.py`, tool interfaces in
  `tools.py`, deterministic geometry/routing in `building_map.py`, persistence in
  `storage.py`, rendering in `viewer.py`. Prefer extending these over new layers.
- Keep facts, counts, areas, distances and paths in deterministic tools. The language
  model interprets requests and explains results; it must not invent map facts.
- Prefer plain functions and existing data structures. Extract shared logic when
  actual duplication makes changes harder; avoid speculative abstractions, generic
  frameworks, plugin systems, microservices and unnecessary configuration.
- Reuse the standard library and installed dependencies. Add a dependency or service
  only when it clearly saves implementation time for a concrete requirement.
- Validate external inputs at boundaries. Handle expected failures with actionable
  errors; do not swallow exceptions or silently fall back to incorrect answers.
- Comment on intent, constraints and non-obvious geometry rules. Avoid comments
  that restate the code, unused helpers, dead code and unrelated refactors.

## Project boundaries and correctness

- `final_agent/` is the project implementation and the only agent package; the kit's
  `starter_agent/` was removed on 24 October 2026 after `final_agent` was verified to
  contain all of it. Keep imports package-local. `benchmark.evaluate` runs
  `final_agent.benchmark:answer` by default.
- Use the existing building JSON schema and metre coordinates. Preserve IDs,
  custom fields, floor elevations and source/licence metadata. Keep persistence
  local and file-based unless a concrete feature requires more.
- Route constraints are correctness requirements: accessibility, widths, closures,
  real connectivity and unreachable cases. Preserve selected openings/connectors
  so the displayed path and directions match the computed route.
- Use the kit 1.1.0 route model documented in the README: door-to-door walking,
  wall clearance, height-based stair/lift costs and no outside shortcut. Keep its
  inherited disconnected-geometry fallback explicit. Forklift restrictions and
  destination-only production bays remain additional Synera automatic-check rules;
  never silently mix scoring models or use the old 1.0.0 labels in data_old/.
- Isolate buildings, conversations and benchmark questions. In the HTTP app,
  confirmed room-object edits share persistent state per dataset/building;
  structural edits and closures remain session-local. What-if analysis must not
  persist edits or leak state. Relevant edits must invalidate routes and spatial
  indexes; save failures must not leave an unexplained partial change.
- Generate answers from building data and the actual question. Use train/dev labels
  for verification only; never hard-code building-specific answers or read expected
  answers in the production answer path.
- Keep `benchmark/score.py` unchanged when improving answers. Public submissions
  use UTF-8 `question_id,answer` CSV and the required final `Answer:` line. Numeric
  answers contain exactly one number; room answers name the selected room first,
  with its area when required. Follow the README's exact tolerances and coverage.
- The Sunday input/output contract is organizer-dependent. Use the announced
  schema when available; do not invent missing requirements or release times.
- Keep credentials out of source control and preserve data attribution obligations
  described in [ATTRIBUTION.md](ATTRIBUTION.md).

## Agent coordination

- Before editing, read the shared `live_agents.md` in the primary checkout (the
  first `worktree` path from `git worktree list --porcelain`). This is the single
  live registry for every worktree; do not maintain independent copies.
- Add your own entry with a unique agent/task name, absolute worktree path,
  repository-relative working files and current status. Register planned files
  before editing them; update the entry when your scope or worktree changes.
- Prefer an isolated Git worktree for implementation when practical. Inspect the
  current checkout and reuse a suitable task worktree, or create one from the
  intended base. Preserve existing uncommitted work; do not reset, stash or copy
  teammates' changes without coordination.
- Do not edit files claimed by another active agent in the same checkout. Pick
  non-overlapping work or coordinate ownership first. When separate worktrees
  change the same files, coordinate integration and review the combined diff.
- Re-read the registry before each update and change only your own entry,
  preserving other agents' entries. Remove your entry when finished, including
  after a handoff or abandoned task; leave the registry and its instructions in place.

## Practical workflow and verification

- Inspect the relevant code and working-tree changes first. Preserve teammates'
  unrelated work. Fix the cause of a defect without widening the task unnecessarily.
- Pick a concrete acceptance criterion, implement it, then run the smallest checks
  that prove it works. Keep test-writing time and token use low for now: reuse
  existing tests and add only a minimal regression test when needed for a meaningful
  correctness bug. Defer broad coverage, new test infrastructure and trivial tests.
- Exercise the real user flow for UI/interaction changes. A feature is done when
  its result is visible and usable, including failure or unreachable cases.
- Select the relevant checks below from the repository root. Run the full suite or
  oracle evaluation only when the change's scope or a failure warrants it:

  ```bash
  uv sync
  uv run python -m unittest discover -s tests -v
  uv run python -m final_agent.evaluate data/dev --oracle
  uv run python -m final_agent data/dev/proc-factory-dev-003
  ```

- For changes to agent interpretation or scored answers, start with a small dev
  sample, inspect failures, then broaden when justified. Live runs require configured
  Anthropic credentials and consume API credits:

  ```bash
  uv run python -m benchmark.evaluate data/dev --agent final_agent.benchmark:answer --per-kind 1 --name final-dev-smoke
  ```

- Report what changed, what actually passed, and any remaining limitation. The
  oracle warm-up supplies expected-answer information; it is not evidence of live
  conversational accuracy or a scored benchmark result. Do not claim unrun checks.
- Keep launch/submission commands reproducible. Before delivery, verify the
  documented `BENCHMARK.md` command, generated answer coverage, demo and technical
  explanation against the README checklist. Keep generated scratch files and
  bytecode out of changes; retain required submission artifacts deliberately.
