# Feature shortlist

[BACKLOG.md](BACKLOG.md) owns task priorities, implementation status and acceptance
criteria.

## Location updates when the mobile app is implemented

For **L1-01 / L1-04**, update current location from reliable mobile location events.
A requested destination alone does not update location. When tracking is unavailable
or uncertain, use the last confirmed location and ask when needed for routing.

- Keep current location separate from destination in building/session state.
- Include building, floor, position or resolved space, timestamp and accuracy in
  location events. Reject events from other buildings/sessions and stale events.
- Resolve positions through deterministic map tools. Ask when the floor or room
  remains ambiguous; do not infer arrival from route generation.
- Use accepted location updates as the start of subsequent routes. Recompute an
  active route when movement requires rerouting, retaining accessibility needs.
- Verify movement and arrival without chat confirmation, plus unavailable,
  uncertain, stale and wrong-building events. Keep explicit confirmation as the
  fallback for the CLI and sessions without tracking.
