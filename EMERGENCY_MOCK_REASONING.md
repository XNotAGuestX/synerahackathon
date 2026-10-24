# Emergency roll call — mock reasoning

Why the mock in `final_agent/emergency.py` looks the way it does, and whether a real
version could work on employees' smartphones. Researched in October 2026; sources
at the end. These are platform and legal summaries, not legal advice. Implementation
status and open items: [EMERGENCY_ROLL_CALL_HANDOFF.md](EMERGENCY_ROLL_CALL_HANDOFF.md).

## Short answer

A real roll call is feasible as **alert → "I'm safe" → fallbacks**. How well a person
can be located depends on whether they opted in:

| Tier | Who | Position | Needs |
|---|---|---|---|
| 1. Opt-in app | Employees who installed the app and allowed location | Best: a phone fix taken when they tap "I'm safe" (1–2 m on Android with compatible access points) | App, location and notification permissions |
| 2. Enterprise Wi-Fi | Every phone connected to the company Wi-Fi, no app needed | Several metres, estimated by the access points | Wi-Fi location features in the network, company Wi-Fi login (802.1X) |
| 3. RFID badge | Badge holders | Only the last door reader passed; a reader at the assembly point confirms safety | Badge readers linked to the roll call |
| 4. Manual | Anyone, e.g. phone left inside | None; an admin or warden confirms them in person | A person at the assembly point |

Only tier 2 can silently locate everyone at once. The phone app (tier 1) cannot
reliably be made to report its position without the person's help.

How the mock maps to this:
- `smartphone` people have a position inside a room: tier 1, or a tier 2 estimate.
- `rfid_badge` people sit at their last door reader: tier 3. Their "I'm safe" is a
  badge scan at the assembly-point reader.
- `mark_person_safe` is tier 4.
- The 2-minute deadline turns everyone not reached by any tier into **unsafe**.

## Tier 1: opt-in app (the best tracking)

Opting in means installing the company app and granting notifications and location.
Use on private phones should be voluntary: a German state labour court (Thuringia,
2018) ruled that employees generally need not hand over their private number.

- **When the position is taken:**
  - The reliable moment is when the person opens the alert and taps "I'm safe". The
    app is then in the foreground, so "while using the app" permission is enough
    on both platforms.
  - Taking it on the alert alone, without a tap, needs "Always" (iOS) or "Allow all
    the time" (Android) location permission, and still is not guaranteed:
    - On iOS, silent pushes are throttled and "not guaranteed", and never reach an
      app the user force-quit. Apple's Location Push Service Extension works with
      the app closed, but needs "Always" permission plus an entitlement meant for
      location-sharing apps, and how to obtain that entitlement was unclear in 2026.
    - On Android 14+, a high-priority push can start a foreground service, but
      location from it effectively needs "Allow all the time". Google Play also
      requires a background-location declaration, though "physical safety" is an
      accepted reason.
- **Accuracy indoors:**
  - GPS is about 5 m under open sky and much worse inside.
  - Android can measure distance to Wi-Fi access points (round-trip time, about
    1–2 m) when the access points support it. iOS gives ordinary apps no Wi-Fi
    scanning; its own location estimate is all an app gets.
  - The floor level is the weak spot: even the US 911 rule allows ±3 m, about one
    storey.

## Tier 2: no opt-in — triangulation by enterprise Wi-Fi hardware

The company's Wi-Fi network can estimate where every connected device is from the
signal strength several access points measure. Examples are Cisco Spaces, HPE Aruba
and Juniper Mist.

- **Advantages:**
  - Nothing runs on the phone, so the iOS and Android background limits don't
    apply.
  - It is the realistic way to see everyone's position at the moment of the alarm.
- **Limits:**
  - Accuracy is usually several metres and depends on access-point density; floors
    and walls cause errors.
  - Phones randomise their Wi-Fi hardware (MAC) address. Identifying the person
    needs the company Wi-Fi login (802.1X/RADIUS), not the address.
  - The phone must have Wi-Fi on. The access points need backup power, or they go
    dark with the building.
  - **It finds the phone, not the person.** A phone left on a desk still shows up
    "inside", which is why manual confirmation (tier 4) exists.
- **Legal:** this is tracking without an app opt-in. The works-council and
  data-protection limits below apply even more strictly: only while an alarm is
  active, and visible only to admins.
- Unlike the rest of this document, the tier 2 claims are general knowledge and were
  not checked against sources. Verify vendor accuracy before relying on them.

## Tiers 3 and 4: badges and people

- **Badges:** an RFID badge only knows the last reader it passed; access-control
  reports show the "time/location of the last access event". Show "last seen near",
  never a live dot.
- **Assembly-point readers:** access-control products already do badge mustering at
  readers in the assembly area, e.g. Genetec Security Center's "Mustering" task.
- **People:** the warden's headcount at the assembly point stays mandatory. DGUV
  205-033, a German workplace-safety guideline, requires it, including visitors.

## Reaching people: the alert itself

Getting the alert through silent mode and Do Not Disturb is possible, but not
guaranteed:

- **iOS:**
  - *Critical Alerts* sound even when the phone is muted or in a Focus mode. They
    need an Apple entitlement granted "extremely rare[ly]", mostly to public
    agencies and health or home apps. Everbridge has it; a company app should not
    count on it.
  - *Time-sensitive* notifications need no approval and break through Focus, but
    not through the mute switch.
- **Android:**
  - High-priority FCM wakes the phone even in battery-saving Doze mode.
  - Getting past Do Not Disturb needs the user to grant that access, or to turn on
    "Override Do Not Disturb" for the alert channel. Full-screen alerts on Android
    14+ also need a user grant. Onboarding must ask for these settings up front.
- **Delivery is best-effort:**
  - Apple's push service is "a best-effort service" and keeps only one pending
    notification per app while the phone is offline. FCM gives no delivery
    guarantee either.
  - So the app is never the only channel. Keep sirens or the public-address system,
    SMS or voice fallback, badge mustering and the warden.
- **Cell Broadcast:** the government warning channel (DE-Alert) is reserved for
  authorities under §164a TKG; companies cannot use it.

## Law in Germany

- Employee location is personal data. Consent is weak in employment. The sounder
  legal basis is the employer's evacuation duty (§10 ArbSchG, ASR A2.3) under Art.
  6(1)(c)/(f) GDPR. §26(1) BDSG is largely displaced since CJEU C-34/21.
- Any location-capable system, app or Wi-Fi, is a technical monitoring device, so
  the works council has co-determination rights (§87(1) Nr. 6 BetrVG). Expect a
  works agreement that:
  - permits collection **only while an alarm is active**,
  - restricts access to admins,
  - deletes the data afterwards.
- Admin-only access is therefore a legal requirement, not just a product choice. The
  app has no user roles yet (see the handoff), which blocks any real deployment.

## Verdict

A real version is feasible for a company app (Android, and iOS with time-sensitive
alerts or a Critical Alerts approval). Build it as an alert plus "I'm safe" that
records the opt-in position at that moment. Enterprise Wi-Fi can add positions for
people who did not opt in or did not answer. Badge mustering and the warden's
headcount cover everything the phones miss. The mock simulates exactly this chain.

## Sources

Apple docs on
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
