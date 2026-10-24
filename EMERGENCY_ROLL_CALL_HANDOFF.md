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

## Could this run on real smartphones?

**Short answer: yes as an alert-and-confirm system; no as a silent "pull everyone's
location" button.** Commercial products already do the first:

- Everbridge sends push alerts that override silent mode and Do Not Disturb.
- AlertMedia offers two-way check-ins with opt-in location sharing.
- Genetec Security Center has badge "mustering" at assembly-point readers.

The mock's model (alert, tap "I'm safe", badge fallback, manual correction) matches
what is realistic. The hard parts are reaching every phone, getting a location and
the law. Status as researched in October 2026:

**1. Getting the alert through silent mode and Do Not Disturb is possible, but not
guaranteed.**

- *iOS Critical Alerts* sound even when the phone is muted or in a Focus mode.
  They need an Apple entitlement that Apple grants "extremely rare[ly]", mostly to
  public agencies and health or home apps. Everbridge has it, but a company app
  should not count on getting it.
- *iOS time-sensitive notifications* need no approval and break through Focus, but
  not through the mute switch.
- *Android* high-priority FCM (Firebase Cloud Messaging) wakes the phone even in
  battery-saving Doze mode. Getting past Do Not Disturb needs the user to grant
  that access, or to turn on "Override Do Not Disturb" for the alert channel.
  Full-screen alerts on Android 14+ also need a user grant. So onboarding must ask
  for these settings up front.

**2. Pulling a location without the person's help is unreliable, especially on
iOS.**

- On iOS, silent pushes are throttled, are "not guaranteed", and never reach an app
  the user has force-quit.
- Apple's Location Push Service Extension can answer a location request while the
  app is closed. It needs "Always" location permission plus an entitlement meant
  for location-sharing apps, and in 2026 the way to request that entitlement was
  unclear.
- On Android 14+, a high-priority message can start a foreground service, but
  location from it effectively needs "Allow all the time" permission. Google Play
  also requires a background-location declaration; "physical safety" is an
  accepted reason.
- Practical design: **record the location when the person opens the alert and taps
  "I'm safe"** (the app is then in the foreground). For people who don't respond,
  use the last badge reader or last known fix, which is exactly what the mock shows.

**3. Indoor positions are coarse.**

- GPS is about 5 m under open sky and much worse inside.
- Wi-Fi round-trip-time ranging reaches 1–2 m, but only with compatible access
  points.
- The floor level is the weak spot: even the US 911 rule allows ±3 m, about one
  storey.
- An RFID badge only knows the last reader it passed. Show "last seen near",
  never a live dot.

**4. Delivery is best-effort, so the app can never be the only channel.**

- APNs (Apple's push service) is "a best-effort service" and keeps only one pending
  notification per app while the phone is offline. FCM gives no delivery guarantee
  either.
- Phones can be dead, left behind or without network, which is the mock's "left
  the phone inside" case.
- Keep sirens or the public-address system, SMS or voice fallback, badge readers
  at the muster point, and the warden's headcount at the assembly point.
  DGUV 205-033, a German workplace-safety guideline, requires that headcount,
  including visitors.
- Cell Broadcast (DE-Alert) is reserved for authorities under §164a TKG; companies
  cannot use it.

**5. Law in Germany allows it only narrowly.**

- Employee location is personal data. Consent is weak in employment. The sounder
  legal basis is the employer's evacuation duty (§10 ArbSchG, ASR A2.3) under Art.
  6(1)(c)/(f) GDPR. §26(1) BDSG is largely displaced since CJEU C-34/21.
- A location-capable app is a technical monitoring device, so the works council
  has co-determination rights (§87(1) Nr. 6 BetrVG). Expect a works agreement
  that permits collection **only while an alarm is active**, restricts who can see
  it (admins) and deletes the data afterwards.
- Installing the app on private phones should be voluntary. The Thuringia state
  labour court (2018) ruled that employees generally need not hand over their
  private number.

**Verdict:** a real version is feasible for a company app (Android, and iOS with
time-sensitive alerts or a Critical Alerts approval). It must be built as
alert, plus "I'm safe" with the location captured at that moment, plus badge
mustering and warden fallback. Admin-only access is a legal requirement, not just
a product choice, which makes the missing user roles (above) a blocker for any
real deployment.

Main sources: Apple docs on
[Critical Alerts](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.usernotifications.critical-alerts),
[background pushes](https://developer.apple.com/documentation/usernotifications/pushing-background-updates-to-your-app),
[location push](https://developer.apple.com/documentation/corelocation/creating-a-location-push-service-extension) and
[APNs](https://developer.apple.com/documentation/usernotifications/sending-notification-requests-to-apns);
Android docs on [FCM priority](https://firebase.google.com/docs/cloud-messaging/android-message-priority),
[background location](https://developer.android.com/develop/sensors-and-location/location/permissions/background),
[Android 14 changes](https://developer.android.com/about/versions/14/behavior-changes-14) and
[Wi-Fi RTT](https://developer.android.com/develop/connectivity/wifi/wifi-rtt);
[Genetec mustering](https://techdocs.genetec.com/r/en-US/Mustering-Task-Guide-3.1/Using-the-Mustering-task-to-move-cardholders-to-mustering-areas-by-badging);
[§164a TKG](https://www.gesetze-im-internet.de/tkg_2021/__164a.html),
[§10 ArbSchG](https://www.gesetze-im-internet.de/arbschg/__10.html),
[§87 BetrVG](https://www.gesetze-im-internet.de/betrvg/__87.html),
[§26 BDSG](https://www.gesetze-im-internet.de/bdsg_2018/__26.html).
These are platform and legal summaries, not legal advice.

## Other limitations

- Positions are the **last known** fix or badge reader, not live tracking.
- One roll call per chat session; no audit log or export of the final report.
- No live (API) conversation check was run for this feature; the tools, the
  rendering and the 2-minute rule are covered by `tests/test_emergency.py` and a
  scripted tool-level run on `proc-factory-dev-003`.
