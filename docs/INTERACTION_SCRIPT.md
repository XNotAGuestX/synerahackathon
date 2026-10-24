# Interaction script outcomes

Fixture mode, building Fertigung Ost 27. Each line is what the guide does. It does not invent a route.

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
