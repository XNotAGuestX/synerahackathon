# Emergency mode — handoff

Status, 25 October 2026: **emergency mode implemented** (FR-17, [ADR-0004](docs/adr/ADR-0004-emergency-mode.md)).
It replaces the earlier roll-call mock (safe/pending/unsafe with a 2-minute deadline). Independent of the scored
benchmark: `final_agent.benchmark:answer` never gets these tools. Whether real phones could do this (opt-in app,
enterprise Wi-Fi triangulation, law): [EMERGENCY_MOCK_REASONING.md](EMERGENCY_MOCK_REASONING.md).

## What it does

An admin activates emergency mode for a building from the app's **Emergency** tab:

1. Unlock with the PIN from `EMERGENCY_ADMIN_PIN` (plus the admin's name, shown as "marked by").
2. Enter a reason, press *Prepare*, type the six-digit code shown on screen and press *Activate*.

While the alarm is active:

- Every phone shows an alarm banner and is asked once for a display name.
- The admin sees a live list with counts: who is **inside**, **outside** or **marked outside**. People still
  inside come first. Phones whose last position is older than 15 s are flagged *stale* and still count as inside.
- Coloured dots on the floor plan show where everyone is (red inside, green outside, blue marked outside).
- *Mark outside* (with a note) covers people who left without their phone. *Undo* removes the mark.
- *End emergency* deletes every position and mark.

| Piece | Where |
|---|---|
| Inside/outside rule, simulated evacuation, real phones, manual marks | `final_agent/emergency.py` |
| Admin PIN/token, challenge code, per-building state | `SessionService` in `final_agent/api_session.py` |
| HTTP routes | `final_agent/api.py`, contract in `openapi.yaml` (tag `Emergency`) |
| App UI | `frontend/src/features/emergency/` |
| Terminal-chat tools `start_emergency_mode`, `emergency_status`, `mark_person_outside`, `end_emergency_mode` | `make_emergency_tools` in `final_agent/tools.py` |
| PNG overlay for the terminal chat | `draw_emergency` in `final_agent/viewer.py` |
| Tests | `tests/test_emergency.py`, emergency test in `tests/test_api.py` |

Inside means the position lies in any space of the building, balconies included. Outside means it lies in no
space on a floor with an entrance (the lowest floor if the building has none).

## What is simulated

- Twelve people per building, seeded from the building id. They start in rooms, never on stairs, in lifts or
  outdoors. Most walk the shortest route to the nearest entrance after 5–60 s and stop 2.5 m outside. A quarter
  (at least one) never leave: their phone stays inside, so every demo has someone to mark by hand.
- Real phones are app sessions that send positions. In the demo the position comes from the walking figure; it can
  now step 2.5 m out of each entrance. No Wi-Fi infrastructure is connected.
- Nothing is persisted; a server restart ends the alarm and logs admins out.

## Demo

```bash
EMERGENCY_ADMIN_PIN=2468 uv run python -m final_agent.api
cd frontend && npm run dev
```

1. Phone A: Emergency tab → PIN `2468` → reason → *Prepare* → type the code → *Activate*.
2. Phone B (second browser or phone, same building): the banner appears; enter a name; walk the figure out of an
   entrance. On phone A, B switches from inside to outside.
3. Watch the simulated people leave; mark one of the remaining ones outside, then undo.
4. *End emergency*: the list empties and the banner disappears on every phone.

## Limits

- One admin role, no user accounts. Anyone with the PIN is an admin.
- Positions come from the app (opt-in). Phones without the app are invisible.
- No audit log or export of the final list.
- The HTTP chat does not get the emergency tools; the terminal chat only sees simulated people.
