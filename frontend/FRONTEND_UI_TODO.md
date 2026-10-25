# Frontend UX/UI TODO

Goal: make Talk to Your Building a map-first building navigation workspace while preserving routing, voice, live position, editing, and import behavior.

## P0 - Baseline quality

- [x] Replace user-visible mojibake with readable text or CSS labels.
- [x] Keep stable `aria-label` values on icon and utility buttons.
- [x] Use clear labels for hide-route, close, send, play, and stop-guidance actions.

## P1 - Information architecture

- [x] Treat the map as the primary workspace and chat as the intent and explanation layer.
- [x] Keep the active route summary near the map instead of only inside chat messages.
- [x] Reduce chat bubble weight and emphasize the active message and active action.
- [x] Keep voice controls focused on input state rather than duplicating route details.
- [x] Give editing mode a distinct visual state from navigation mode.
- [x] Keep import and revision metadata below the main map hierarchy.

## P1 - Map and navigation feedback

- [x] Add a unified visual level for the current destination and route state.
- [x] Strengthen floor controls so the active floor reads as navigation state.
- [x] Align map, route summary, and next-step colors.
- [x] Preserve static fallbacks under `prefers-reduced-motion`.

## P1 - Responsive and accessible behavior

- [x] Keep chat/details below the map on small screens and avoid competing fixed panels.
- [x] Keep the map, current instruction, and primary action visible on narrow screens.
- [x] Preserve dialog Escape handling, focus containment, and live announcements.
- [ ] Verify with Playwright at 320, 390, 768, 1024, and 1440px; browser automation is not configured in this checkout.

## P2 - Verification

- [x] `npm run build` passes.
- [x] `npm run test:effects` passes.
- [x] `npm run test:walk` passes.
- [x] Record bundle warning: main entry is about 561KB and `FloorStack3D` is about 734KB; further code splitting remains optional follow-up work.
