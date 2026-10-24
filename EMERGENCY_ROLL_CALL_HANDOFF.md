# Emergency roll call — handoff

Status, 24 October 2026: **mock implemented** on branch `feature/emergency-roll-call`.
Independent of the scored benchmark: `final_agent.benchmark:answer` never gets these tools.

## What it does

In an emergency an admin asks the chat guide to trigger a roll call. Every employee
is alerted and their last known location is shared on the floor plans. Everyone
must confirm "I'm safe" within **2 minutes** (tap in the phone app, or a badge scan
at the assembly-point reader). Anyone still unconfirmed at the deadline is marked
**unsafe**. Admins can mark people safe by hand, for example someone who is at the
assembly point but left their smartphone inside.

| Piece | Where |
|---|---|
| Simulation, 2-minute rule, manual confirmation | `final_agent/emergency.py` |
| Agent tools `trigger_emergency_roll_call`, `emergency_roll_call_status`, `mark_person_safe`, `end_emergency_roll_call` | `make_emergency_tools` in `final_agent/tools.py` |
| Map overlay: green safe, amber pending, red unsafe; circle = phone fix, square = badge reader | `draw_emergency` / `draw_floor(people=...)` in `final_agent/viewer.py` |
| Enabled for interactive chat only, plus a short prompt section | `BuildingAgent(emergency=True)` in `final_agent/agent.py` |
| Regression tests | `tests/test_emergency.py` |

Status rule: **safe** = confirmed by the person or an admin; **pending** = no reply
and the deadline has not passed; **unsafe** = no confirmation within 120 s. A late
manual confirmation turns unsafe into safe. Results give each person's
`last_seen.id`, so the existing `find_route` can send a responder there.

## What is fake

Everything about the people, deliberately:

- Twelve fake employees, seeded from the building id, so a building replays
  identically. They are placed in rooms and halls, never on stairs, in lifts or
  outdoors.
- Tracking is either a **smartphone location fix** (a point inside the room) or an
  **RFID security badge**. A badge only knows the door reader it last passed, so its
  position is that door.
- Reply times are seeded within 8–110 s. A quarter of the people (rounded up, at
  least one) never reply, so every demo reaches the unsafe case.
- No device is contacted, nothing is persisted, and ending the roll call discards
  the data. `emergency_roll_call_status(fast_forward_s=...)` moves the simulated
  clock for demos; the real clock otherwise runs at wall time.

## Demo

```bash
uv run python -m final_agent data/dev/proc-factory-dev-003
```

1. "Fire alarm in the production hall — trigger the emergency roll call."
2. "Skip to the deadline. Who is unaccounted for and where were they last seen?"
   On this building three people are unsafe: Hannah Klein (Quality lab 0.21),
   Jonas Fischer and Sofia Kaya (badge readers in main aisles H-B3 / H-B1).
3. "Jonas Fischer is with me at the assembly point, mark him safe."
4. "Route me from Hall access 0.19 to Sofia Kaya's last known location." (existing
   routing; 25.4 m to Main aisle H-B1)
5. "End the roll call."

Maps are written to `agent_output/emergency_<floor level>.png`.

## Open: user roles are not implemented

The requirement is that **only admins** may trigger, view, correct and end a roll
call; it shows everyone's location. The app has **no user accounts or roles yet**,
so for now **every user counts as an admin** and anyone in the chat can use all four
tools. No role check exists in the code, and nothing pretends to authenticate.

When roles exist:

- Pass the session user into `make_emergency_tools` and refuse the four tools for
  non-admins with a clear `ToolError`. Keep the rule in that one place.
- Give non-admins the employee side, which the mock only simulates: receive the
  alert and confirm their own safety.
- Add a test that a non-admin cannot trigger the roll call or see anyone's location.

## Other limitations

- Positions are the **last known** fix or badge reader, not live tracking.
- One roll call per chat session; no audit log or export of the final report.
- No live (API) conversation check was run for this feature; the tools, the
  rendering and the 2-minute rule are covered by `tests/test_emergency.py` and a
  scripted tool-level run on `proc-factory-dev-003`.
