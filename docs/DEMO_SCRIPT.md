# Wayfinder demo script

Five minutes. Use fixture mode. Start with `npm run dev` in `frontend/`.

1. **Locate.** Open the app. Show the category row, not a random list. Open Machines, then Cnc Mill. Click a mill name so the map focuses that floor and equipment.
2. **Route.** With Step-free on, click Route here on CNC mill H-A1-A. The tape and the 46.1 m direction list appear. Zoom in, drag the plan, then Reset.
3. **Clarify.** Open debug below the map. Load “Where is the desk?”. The guide asks which desk and does not draw a guessed route. Pick one option; it fills the composer.
4. **Closure.** Load “Close the office lift”. Confirm and Cancel are separate. Confirm, then show the closed highlight and the revision note.
5. **Unreachable.** Load “Unreachable step-free route”. The alert explains the closed lift and the map has no tape.

If the API server is running, switch `VITE_DATA_MODE=http` and repeat route and clarify. An API error shows `code`, `message`, `trace_id`, and `X-Request-Id`.
