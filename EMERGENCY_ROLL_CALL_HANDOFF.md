# Emergency mode — handoff

Status, 25 October 2026: **emergency mode implemented** (FR-17, [ADR-0004](docs/adr/ADR-0004-emergency-mode.md)).
It replaces the earlier roll-call mock (safe/pending/unsafe with a 2-minute deadline). Independent of the scored
benchmark: `final_agent.benchmark:answer` never gets these tools. Whether real phones could do this (opt-in app,
enterprise Wi-Fi triangulation, law): [EMERGENCY_MOCK_REASONING.md](EMERGENCY_MOCK_REASONING.md).

## What it does

An admin taps **Emergency** in the top bar, enters their name and the admin password (`EMERGENCY_ADMIN_PIN`)
and presses *Activate emergency*. Nothing else is asked.

While the alarm is active:

- Every phone shows an alarm banner and is asked once for a display name (the admin's name is reused).
- Every phone shows the people still **inside** as red dots with their names on the floor plan; the floor buttons
  show how many are inside per floor.
- Anyone can open the live list (Emergency button): counts and who is **inside**, **outside** or **marked
  outside**, people still inside first. Phones whose last position is older than 15 s are flagged *stale* and still
  count as inside. Tapping a name inside switches the plan to that person's floor and rings them.
- *Mark outside* (with a note), *Undo* and *End emergency* need an admin: a device that is not unlocked asks for
  name and admin password once, then carries out the action.
- Showcase: three simulated people are already outside, marked by the "Assembly point warden".
- *End emergency* deletes every position and mark.

| Piece | Where |
|---|---|
| Inside/outside rule, simulated evacuation, showcase marks, real phones, manual marks | `final_agent/emergency.py` |
| Admin PIN/token, per-building state | `SessionService` in `final_agent/api_session.py` |
| HTTP routes | `final_agent/api.py`, contract in `openapi.yaml` (tag `Emergency`) |
| App UI | `frontend/src/features/emergency/` |
| Terminal-chat tools `start_emergency_mode`, `emergency_status`, `mark_person_outside`, `end_emergency_mode` | `make_emergency_tools` in `final_agent/tools.py` |
| PNG overlay for the terminal chat | `draw_emergency` in `final_agent/viewer.py` |
| Tests | `tests/test_emergency.py`, emergency test in `tests/test_api.py` |

Inside means the position lies in any space of the building, balconies included. Outside means it lies in no
space on a floor with an entrance (the lowest floor if the building has none).

## What is simulated

- Twelve people per building, seeded from the building id. They start in rooms, never on stairs, in lifts or
  outdoors. Three are already outside and marked when the alarm starts. Most others walk the shortest route to the
  nearest entrance after 2–12 s at a demo pace of 3 m/s and stop 2.5 m outside; the list is down to the stayers
  after about 45 s. A quarter (at least one) never leave: their phone stays inside, so every demo has someone to
  mark by hand.
- Real phones are app sessions that send positions. In the demo the position comes from the walking figure; it can
  now step 2.5 m out of each entrance. No Wi-Fi infrastructure is connected.
- Nothing is persisted; a server restart ends the alarm and logs admins out.

## Demo

```bash
EMERGENCY_ADMIN_PIN=2468 uv run python -m final_agent.api
cd frontend && npm run dev
```

1. Phone A: *Emergency* → name → password `2468` → *Activate emergency*. Three people are already marked outside.
2. Phone B (second browser or phone, same building): the banner appears; enter a name; red dots with names appear
   on the plan. Walk the figure out of an entrance: B switches from inside to outside.
3. Watch the simulated people leave. On phone B open the list, tap a name to find them on the map, mark one
   outside: B is asked for name and password once.
4. *End emergency*: the list empties and the banner disappears on every phone.

## Limits

- One admin role, no user accounts. Anyone with the password is an admin.
- The list and the map are visible to every app user during an alarm (team decision; a real deployment needs
  works-council and data-protection approval).
- An app session that sent a position in the 10 minutes before the alarm stays listed as "inside, no signal" even
  if its tab was closed; a server restart clears old sessions.
- Positions come from the app (opt-in). Phones without the app are invisible.
- No audit log or export of the final list.
- The HTTP chat does not get the emergency tools; the terminal chat only sees simulated people.
