# Wayfinder demo script

Five minutes. Start the main API with `uv run --env-file .env python -m final_agent.api`, then `npm run dev` in `frontend/`. Configure backend Anthropic credentials for chat. Static samples in Debug are previews, not live agent answers. This script has not been rerun after integration because UI testing was deferred.

1. **Locate.** Open the app. Show the category row, not a random list. Open Machines, then Cnc Mill. Click a mill name so the map focuses that floor and equipment.
2. **Route.** Choose a start, then with Step-free on click Route here on CNC mill H-A1-A. The tape and the calculated distance appear; routes use the kit 1.1.0 door-to-door geometry. Zoom in, drag the plan, then Reset.
3. **Clarify.** Open debug below the map. Load “Where is the desk?”. The guide asks which desk and does not draw a guessed route. Pick one option; it fills the composer.
4. **Closure.** Load “Close the office lift”. Confirm and Cancel are separate. Confirm, then show the closed highlight and the revision note.
5. **Unreachable.** Load “Unreachable step-free route”. The alert explains the closed lift and the map has no tape.

The app always uses the main API. An API error shows `code`, `message`, `trace_id`, and `X-Request-Id`.
