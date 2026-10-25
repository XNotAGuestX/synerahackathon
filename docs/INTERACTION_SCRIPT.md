# Interaction script outcomes

## Live rerun — 25 October 2026

One process, model Haiku, building `proc-factory-dev-003` (Fertigung Ost 27). Workspace `agent_output/acceptance/workspaces/2f962a0f5653`. Full replies and tool names are in `agent_output/acceptance/evidence.json`. Elapsed 69.98 seconds for the scripted turns, campus turn and plan imports.

1. “Where is the CNC mill?” called `search_building` and named CNC mill H-A1-A, H-A1-B and H-A1-C in Production zone H-A1. It did not draw a route.
2. “Where is the desk?” called `search_building` and asked which of 51 desks, listing Desk 0.23, Desk 0.25-A, Desk 0.26-A and Desk 0.30-A. It did not guess.
3. “I am at Warehouse zone H-C2.” called `confirm_location`. The reply says the location is recorded. No route tape.
4. “How do I get to CNC mill H-A1-A without stairs?” called `find_route`. Step-free, 37.27 m, Warehouse zone H-C2 to Production zone H-A1, no stairs.
5. “Now go to the kitchen instead.” called `search_building` and asked which of seven kitchens. It kept the step-free constraint and did not guess.
6. “Close the office lift.” called `search_building` and `set_closed`. The Office lift was closed and saved. The active 37.27 m route does not use that lift, so it stayed.
7. “Reopen the office lift.” called `set_closed`. The lift was reopened and saved.
8. “Visit Warehouse zone H-C2, then Production zone H-A1, in that order, and finish at Assembly zone H-A2.” called `find_route`. Order kept. Step-free, 54.37 m.
9. “Where is room 9.99?” called `search_building` twice, named no room, and drew no route.

A resumed turn in the same workspace then said “Close the opening between Main aisle H-B1 and Production zone H-A1, then update my route.” The agent closed opening `proc-factory-dev-003-F0-O0001` and recomputed the tour at **58.8 m**, no longer using that opening.

Search now returns connector names. Before that fix, “Office lift” was missed because search listed only rooms and assets.

Historical fixture-mode outcomes, building Fertigung Ost 27, remain below.

1. Locate “where is the desk?” asks which desk. The options include the building name.
2. “I am at Warehouse zone H-C2” stores the location and draws no tape.
3. “how do I reach the CNC mill” uses that location. The saved step-free route appears only when the start, destination, and step-free preference match it.
4. “no stairs” turns step-free on for later routes and does not draw a new tape.
5. “now go to the kitchen instead” changes the destination and keeps the stored start.
6. “visit Warehouse zone H-C2 then Production zone H-A1” keeps that order and states that no multi-stop distance is saved.
7. “close Office lift” asks for confirmation. After confirm, a route that crossed that place is not replaced with a guessed path.
8. Reopen asks for confirmation and clears that closure.
9. “where is room 9.99” names no room and draws no tape.
10. Switching to Other building drops the previous plan, selection, and route.
