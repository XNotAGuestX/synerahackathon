"""Mock emergency roll call: an admin alerts everyone, who must confirm they are safe within two minutes.

Everything about the people is simulated: who is inside, where their smartphone or RFID security badge last placed
them, and when (or whether) they confirm. The simulation is seeded from the building id, so a demo replays the same
way every time. Nothing is saved; ending the roll call discards it.

How a real system would locate people, best first:
- Opt-in app: a phone fix taken when the person taps "I'm safe" (the only reliable moment to ask the phone).
- No opt-in: the enterprise Wi-Fi hardware triangulates every connected phone; no app needed, several metres
  accurate, but it finds the phone, not the person.
- RFID badge: only the last door reader passed; a scan at the assembly-point reader confirms safety.
- Nothing works (e.g. phone left inside): an admin confirms the person by hand.
Here a "smartphone" fix stands for the first two tiers. EMERGENCY_MOCK_REASONING.md has the full reasoning.

The roll call is meant for admins only, but the app has no user roles yet, so every user counts as an admin.
EMERGENCY_ROLL_CALL_HANDOFF.md tracks that gap.
"""

import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from shapely.geometry import Point

from .building_map import BuildingMap, normalize_type, outline

ROLL_CALL_WINDOW_S = 120.0

SMARTPHONE = "smartphone"
RFID_BADGE = "rfid_badge"
SAFE, PENDING, UNSAFE = "safe", "pending", "unsafe"
STATUS_ORDER = (UNSAFE, PENDING, SAFE)

SIMULATED_PEOPLE = 12
BADGE_SHARE = 0.3
NO_REPLY_SHARE = 0.25  # at least one person never replies, so every demo reaches the unsafe case
FIRST_REPLY_S, LAST_REPLY_S = 8.0, 110.0
# Nobody is placed on stairs, in lifts or outdoors: people pass through those spaces rather than stay there.
UNOCCUPIED_TYPES = ("stair", "lift", "outdoor")
POSITION_ATTEMPTS = 50

FIRST_NAMES = ("Alex", "Maria", "Jonas", "Lea", "Deniz", "Sofia", "Lukas", "Mia", "Elias", "Hannah", "Noah", "Emma")
LAST_NAMES = ("Weber", "Schmidt", "Becker", "Yilmaz", "Novak", "Fischer", "Wagner", "Rossi", "Kaya", "Hoffmann",
              "Klein", "Wolf")


class EmergencyError(Exception):
    """A roll-call request that cannot be carried out; the message says why."""


@dataclass
class Person:
    """A simulated employee. Positions come from a phone location fix or the badge reader last passed."""

    id: str
    name: str
    tracker: str  # SMARTPHONE or RFID_BADGE
    space_id: str
    position: tuple[float, float]
    badge_door_id: str | None  # the door whose reader last saw the badge; None for smartphones
    reply_after_s: float | None  # simulated "I'm safe" confirmation; None = never replies
    admin_marked_at_s: float | None = None
    admin_note: str = ""


def point_in_room(building_map: BuildingMap, space_id: str, rng: random.Random) -> tuple[float, float]:
    """A random point inside the room outline (rejection sampling), else the room's anchor point."""
    polygon = outline(building_map.spaces[space_id]["polygon"])
    min_x, min_y, max_x, max_y = polygon.bounds
    for _ in range(POSITION_ATTEMPTS):
        x, y = rng.uniform(min_x, max_x), rng.uniform(min_y, max_y)
        if polygon.contains(Point(x, y)):
            return x, y
    return building_map.anchor(space_id)


def simulate_people(building_map: BuildingMap, count: int = SIMULATED_PEOPLE) -> list[Person]:
    """Fake employees in occupiable rooms, with trackers and reply times seeded from the building id."""
    if not 1 <= count <= len(FIRST_NAMES):
        raise EmergencyError(f"The simulation supports 1 to {len(FIRST_NAMES)} people, got {count}.")
    rooms = sorted(
        space_id for space_id, space in building_map.spaces.items()
        if normalize_type(space.get("type") or "") not in UNOCCUPIED_TYPES
    )
    if not rooms:
        raise EmergencyError("This building has no rooms to place simulated people in.")
    rng = random.Random(building_map.data["building"]["id"])
    names = [f"{first} {last}" for first, last in zip(rng.sample(FIRST_NAMES, count), rng.sample(LAST_NAMES, count))]
    silent = set(rng.sample(range(count), max(1, math.ceil(count * NO_REPLY_SHARE))))
    people = []
    for index, name in enumerate(names):
        space_id = rng.choice(rooms)
        doors = sorted(opening_id for opening_id, opening in building_map.openings.items()
                       if space_id in opening["space_ids"])
        if doors and rng.random() < BADGE_SHARE:
            tracker, badge_door_id = RFID_BADGE, rng.choice(doors)
            x, y = building_map.openings[badge_door_id]["position"][:2]
            position = (x, y)
        else:
            tracker, badge_door_id = SMARTPHONE, None
            position = point_in_room(building_map, space_id, rng)
        reply = None if index in silent else round(rng.uniform(FIRST_REPLY_S, LAST_REPLY_S), 1)
        people.append(Person(f"P{index + 1:02d}", name, tracker, space_id, position, badge_door_id, reply))
    return people


class EmergencyRollCall:
    """The roll call of one chat session. It exposes everyone's location, so it belongs behind an admin check
    once user roles exist; until then every user may trigger, view, correct and end it."""

    def __init__(self, building_map: BuildingMap, clock: Callable[[], float] = time.monotonic) -> None:
        self.map = building_map
        self.clock = clock
        self.people: dict[str, Person] = {}
        self.reason = ""
        self.started_at: float | None = None
        self.skipped_s = 0.0

    def require_active(self) -> None:
        if self.started_at is None:
            raise EmergencyError("No emergency roll call is running. Trigger one first.")

    def trigger(self, reason: str) -> dict:
        if self.started_at is not None:
            raise EmergencyError(f"A roll call is already running ('{self.reason}'). End it before starting another.")
        self.people = {person.id: person for person in simulate_people(self.map)}
        self.reason = reason.strip() or "Emergency"
        self.started_at = self.clock()
        self.skipped_s = 0.0
        building = self.map.data["building"]["name"]
        return {
            "alert_sent": {
                "smartphones": f"EMERGENCY at {building}: {self.reason}. Leave by the nearest safe exit and tap "
                               f"'I'm safe' within {ROLL_CALL_WINDOW_S:.0f} s.",
                "rfid_badges": "Badge holders confirm by scanning their badge at the assembly-point reader.",
            },
            **self.report(),
        }

    def elapsed_s(self) -> float:
        return self.clock() - self.started_at + self.skipped_s

    def fast_forward(self, seconds: float) -> None:
        """Demo only: move the roll-call clock ahead so the deadline can be shown without waiting."""
        self.require_active()
        if not math.isfinite(seconds) or seconds < 0:
            raise EmergencyError(f"fast_forward_s must be a finite number of seconds >= 0, got {seconds}.")
        self.skipped_s += seconds

    def confirmation(self, person: Person, elapsed: float) -> tuple[float, str] | None:
        """When and how the person was first confirmed safe by `elapsed`; None while unconfirmed."""
        confirmations = []
        if person.reply_after_s is not None and person.reply_after_s <= elapsed:
            channel = "app" if person.tracker == SMARTPHONE else "assembly_point_badge_scan"
            confirmations.append((person.reply_after_s, channel))
        if person.admin_marked_at_s is not None:
            confirmations.append((person.admin_marked_at_s, "admin"))
        return min(confirmations) if confirmations else None

    def status(self, person: Person, elapsed: float) -> str:
        if self.confirmation(person, elapsed):
            return SAFE
        return PENDING if elapsed < ROLL_CALL_WINDOW_S else UNSAFE

    def find_person(self, reference: str) -> Person:
        """A person by id ('P03') or exact full name, case-insensitive."""
        wanted = reference.strip().casefold()
        for person in self.people.values():
            if wanted in (person.id.casefold(), person.name.casefold()):
                return person
        known = "; ".join(f"{person.id} ({person.name})" for person in self.people.values())
        raise EmergencyError(f"No person '{reference}' in this roll call. Use one of: {known}.")

    def mark_safe(self, reference: str, note: str) -> dict:
        """An admin confirms someone in person, e.g. at the assembly point after leaving their phone inside."""
        self.require_active()
        person = self.find_person(reference)
        if person.admin_marked_at_s is None:
            person.admin_marked_at_s = round(self.elapsed_s(), 1)
        person.admin_note = note.strip()
        return {"marked_safe": self.person_record(person, self.elapsed_s()), **self.report()}

    def end(self) -> dict:
        """Close the roll call and return its final report; the simulated data is discarded."""
        self.require_active()
        final = {"ended": True, **self.report()}
        self.people, self.reason, self.started_at, self.skipped_s = {}, "", None, 0.0
        return final

    def person_record(self, person: Person, elapsed: float) -> dict:
        confirmed = self.confirmation(person, elapsed)
        source = (f"badge reader at door {person.badge_door_id}" if person.tracker == RFID_BADGE
                  else "smartphone location fix")
        record = {
            "id": person.id, "name": person.name, "status": self.status(person, elapsed), "tracker": person.tracker,
            "confirmed": {"via": confirmed[1], "after_s": confirmed[0]} if confirmed else None,
            "last_seen": {**self.map.place_record(person.space_id), "source": source},
        }
        if person.admin_note:
            record["admin_note"] = person.admin_note
        return record

    def report(self) -> dict:
        """Status of the running roll call: unsafe people first, then pending, then safe."""
        self.require_active()
        elapsed = self.elapsed_s()
        records = sorted((self.person_record(person, elapsed) for person in self.people.values()),
                         key=lambda record: (STATUS_ORDER.index(record["status"]), record["name"]))
        counts = {status: sum(record["status"] == status for record in records) for status in STATUS_ORDER}
        return {
            "simulated": True,
            "reason": self.reason,
            "elapsed_s": round(elapsed, 1),
            "seconds_left": round(max(0.0, ROLL_CALL_WINDOW_S - elapsed), 1),
            "deadline_passed": elapsed >= ROLL_CALL_WINDOW_S,
            "counts": {**counts, "total": len(records)},
            "people": records,
        }

    def markers(self) -> list[dict]:
        """Last known position and status of each person, for drawing on the floor plans."""
        self.require_active()
        elapsed = self.elapsed_s()
        return [
            {"name": person.name, "status": self.status(person, elapsed), "tracker": person.tracker,
             "floor_id": self.map.spaces[person.space_id]["floor_id"], "position": person.position}
            for person in self.people.values()
        ]
