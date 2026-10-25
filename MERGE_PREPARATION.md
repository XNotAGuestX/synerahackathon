# Main / Wayfinder integration record

Finalized on 25 October 2026 from main `4680cef24582554bfdd475cc4c5701dc4046e7ff`
and frontend `e26f79caf03a32129c0d2da6153accf5c74f113c`.
All 11 textual conflicts are resolved. The user authorized committing the merge
and chose main's agent for every live answering path. No ambiguous merge decision remains.

## Final decisions

- Agent: the entire tracked `final_agent/` package matches the main parent exactly, including prompts, model choices, retrieval, benchmark adapters, geometry, tools, room reports, emergency mock and campus/plan workspace.
- Auth: retain main's standard Anthropic SDK client; remove the branch-specific custom proxy URL and configuration example.
- Benchmark: retain main's agent adapter and its existing retrieval/no-retrieval variants; remove the frontend template-answer adapter and duplicate scored geometry methods.
- Web chat: use main's HTTP API exclusively; remove the Python demo interpreter, browser fixture interpreter, simulated gateway and automatic fixture-answer fallback.
- Launch: `scripts/serve_api.py` is a compatibility launcher for the same main API, not a separate implementation.

## Frontend and contract integration

Discovery, text/transcript input, clarification, session recovery, confirmed
closures, route playback, floor stacking, map controls, plan import, selected-room
highlighting and the walker/speed slider are retained. Canvas, walker and styles
match the latest frontend parent. The App and gateway use main's session body,
cursor pagination, nested action results and clarification `place_id` values.
A current-location statement updates local UI context only after the main agent
returns one verified room; other requests stay in the agent conversation.
API failures remain visible. Static debug previews remain for inspection.

The root OpenAPI contract is authoritative; the frontend copy has the same paths
and component schemas. Both static fixture families remain reproducible, with
37 indexed examples validated against the main API contract. The colliding main
example names are retained as `backend-session.json` and `backend-route.json`.
Fixture routes use the main API's selected door-to-door geometry. No fixture
answers are used to answer live user messages.

## Verification of the final implementation

- Backend suite: 263 tests run, 260 passed, 3 credential-dependent skips.
- Frontend TypeScript and production build: passed; Vite reports its existing large-bundle warning.
- API fixtures: all 37 examples validated; reproducibility is covered by the backend suite.
- Main-package comparison: every tracked file in `final_agent/` matches the main parent byte for byte.
- Remaining conflict entries/markers: none.
- Integration edits pass whitespace checks. The full merge retains inherited Markdown hard-break spaces and trailing blank lines from the frontend branch.

The earlier oracle run passed 369/369 with the unchanged main router. It uses
expected fixture inputs and is not a live-model benchmark score. No live Claude
request was made. Browser/UI tests remain stopped at the user's request; final
UI acceptance and live conversational behavior have not been measured.

## Reproduce

```bash
uv sync
uv run python -m unittest discover -s tests -v
uv run python scripts/generate_api_fixtures.py
uv run python scripts/validate_api_fixtures.py
uv run --env-file .env python -m final_agent.api
# In another terminal:
cd frontend
npm ci
npm run build
npm run dev
```

Configure Claude credentials in the backend environment. `.env` loading is
explicit, and `API_TOKEN` separately protects the local HTTP API. Search,
floor plans and route calculations do not require Claude credentials.
