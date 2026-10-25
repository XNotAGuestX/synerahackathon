"""Emergency mode: while an admin keeps the alarm active, every tracked phone is listed as inside or outside the building.

Two kinds of phones are tracked:
- Simulated people (seeded from the building id, so a demo replays the same way). Three are already outside and
  marked by the assembly point warden when the alarm starts. Most others walk to the nearest entrance after a short
  delay and step outside; a quarter (at least one) never leave, standing for a phone left inside.
- Real app sessions that share their position (PUT /sessions/{id}/position). The HTTP layer hands their latest fix in
  through observe(); session ids never leave this module, every phone gets an opaque D-id.

An admin may mark a person as outside by hand, for example someone at the assembly point without their phone.
Nothing is saved; ending the alarm discards every position and mark.

How a real system would locate phones, best first:
- Opt-in app: the phone reports its own position (what the app's position endpoint models).
- No opt-in: the enterprise Wi-Fi hardware triangulates every connected phone; several metres accurate.
- Nothing works (phone left inside, battery empty): an admin marks the person by hand.
EMERGENCY_MOCK_REASONING.md has the full reasoning, including the legal limits.
"""

import math
import random
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace

import networkx as nx
from shapely.geometry import Point

from .building_map import DOOR_PREFIX, OUTSIDE, BuildingMap, normalize_type, outline

INSIDE, OUTSIDE_AUTO, OUTSIDE_MANUAL = "inside", "outside", "outside_manual"
STATUS_ORDER = (INSIDE, OUTSIDE_AUTO, OUTSIDE_MANUAL)
SIMULATED, SESSION = "simulated", "session"

SIMULATED_PEOPLE = 12
STAY_SHARE = 0.25  # at least one simulated phone stays inside, so every demo has someone to mark by hand
# Showcase: these people are already outside and confirmed at the assembly point when the alarm starts.
PRE_MARKED = 3
PRE_MARKED_BY = "Assembly point warden"
PRE_MARKED_NOTE = "Checked in at the assembly point"
# Demo pace, not real walking speed: the list should visibly empty within a short demo.
FIRST_LEAVE_S, LAST_LEAVE_S = 2.0, 12.0
WALK_SPEED_M_S = 3.0
CONNECTOR_S = 5.0  # time spent on a staircase or in a lift between two floors
OUTSIDE_STEP_M = 2.5  # how far beyond the entrance door a person stops
STALE_S = 15.0  # same threshold as a live position fix
PRESENCE_S = 600.0  # a session counts as present if it sent a fix this long before the alarm, or any since
MAX_PEOPLE = 200
# Nobody starts on stairs, in lifts or outdoors: people pass through those spaces rather than stay there.
UNOCCUPIED_TYPES = ("stair", "lift", "outdoor")
POSITION_ATTEMPTS = 50

FIRST_NAMES = ("Alex", "Maria", "Jonas", "Lea", "Deniz", "Sofia", "Lukas", "Mia", "Elias", "Hannah", "Noah", "Emma")
LAST_NAMES = ("Weber", "Schmidt", "Becker", "Yilmaz", "Novak", "Fischer", "Wagner", "Rossi", "Kaya", "Hoffmann",
              "Klein", "Wolf")

Point2 = tuple[float, float]
TrackPoint = tuple[float, str, Point2]  # (seconds after leaving, floor id, position)


class EmergencyError(Exception):
    """An emergency request that cannot be carried out; the message says why."""


class EmergencyNotActive(EmergencyError):
    """No alarm is running."""


class EmergencyAlreadyActive(EmergencyError):
    """An alarm is already running."""


class PersonNotFound(EmergencyError):
    """The person reference matches nobody in the current alarm."""


@dataclass
class Person:
    """A simulated phone owner: starts in a room, leaves after leave_after_s along track (None = stays inside)."""

    id: str
    name: str
    space_id: str
    start: Point2
    leave_after_s: float | None
    track: list[TrackPoint] = field(default_factory=list)
    out_from_start: bool = False  # pre-marked showcase person: already at the end of the track


@dataclass
class PhoneFix:
    """The latest position of a real app session. key is the session id; measured_at is a Unix timestamp."""

    key: str
    name: str | None
    floor_id: str
    point: Point2
    measured_at: float


@dataclass
class ManualExit:
    marked_at: float
    marked_by: str
    note: str


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def entrance_floor_ids(building_map: BuildingMap) -> set[str]:
    """Floors with a door to the outside; without any, the lowest floor is where people leave."""
    floors = {opening["floor_id"] for opening in building_map.openings.values() if OUTSIDE in opening["space_ids"]}
    if not floors and building_map.floors:
        floors = {min(building_map.floors, key=building_map.floor_level)}
    return floors


def classify(building_map: BuildingMap, floor_id: str, point: Point2) -> tuple[str, str | None]:
    """(inside or outside, containing space id) for a position.

    Any space counts as inside, outdoor ones included: a balcony or terrace is still part of the building and
    rescuers must go in to reach it. A point in no space is outside only on a floor people can leave from;
    elsewhere it is an imprecise fix (between rooms, inside a wall) of someone who is still in the building.
    """
    from .waypoints import space_containing  # waypoints -> viewer -> this module

    if floor_id not in building_map.floors:
        return INSIDE, None
    space_id = space_containing(building_map, floor_id, point)
    if space_id is not None:
        return INSIDE, space_id
    return (OUTSIDE_AUTO if floor_id in entrance_floor_ids(building_map) else INSIDE), None


def point_in_room(building_map: BuildingMap, space_id: str, rng: random.Random) -> Point2:
    """A random point inside the room outline (rejection sampling), else the room's anchor point."""
    polygon = outline(building_map.spaces[space_id]["polygon"])
    min_x, min_y, max_x, max_y = polygon.bounds
    for _ in range(POSITION_ATTEMPTS):
        x, y = rng.uniform(min_x, max_x), rng.uniform(min_y, max_y)
        if polygon.contains(Point(x, y)):
            return x, y
    return building_map.anchor(space_id)


def exit_track(building_map: BuildingMap, space_id: str, start: Point2) -> list[TrackPoint]:
    """Timed walk from start to the nearest entrance and OUTSIDE_STEP_M beyond it; [] if no entrance is reachable."""
    from .viewer import route_polylines  # viewer imports this module

    graph = building_map.graph()
    entrances = {DOOR_PREFIX + opening["id"] for opening in building_map.openings.values()
                 if OUTSIDE in opening["space_ids"] and DOOR_PREFIX + opening["id"] in graph}
    if not entrances or space_id not in graph:
        return []
    try:
        _, nodes = nx.multi_source_dijkstra(graph, entrances, target=space_id, weight="weight")
    except nx.NetworkXNoPath:
        return []
    nodes = nodes[::-1]
    route = SimpleNamespace(node_path=nodes, edge_path=[element for element, _ in building_map.select_edges(graph, nodes)])
    polylines = [(floor_id, points) for floor_id, points in route_polylines(building_map, route) if points]
    if not polylines:
        return []
    door = building_map.openings[nodes[-1].removeprefix(DOOR_PREFIX)]
    door_point = (door["position"][0], door["position"][1])
    last_points = polylines[-1][1]
    before = next((point for point in reversed(last_points) if math.dist(point, door_point) > 1e-6),
                  building_map.anchor(space_id))
    length = math.dist(before, door_point) or 1.0
    outside = (door_point[0] + (door_point[0] - before[0]) / length * OUTSIDE_STEP_M,
               door_point[1] + (door_point[1] - before[1]) / length * OUTSIDE_STEP_M)
    polylines[-1] = (polylines[-1][0], [*last_points, outside])

    first_floor = building_map.spaces[space_id]["floor_id"]
    track: list[TrackPoint] = [(0.0, first_floor, start)]
    for floor_id, points in polylines:
        t, previous_floor, previous = track[-1]
        if floor_id != previous_floor:
            t += CONNECTOR_S  # stairs or lift: the phone reappears on the next floor after a pause
            previous = points[0]
        for point in points:
            t += math.dist(previous, point) / WALK_SPEED_M_S
            track.append((t, floor_id, point))
            previous = point
    return track


def position_at(person: Person, elapsed: float) -> tuple[str, Point2]:
    """(floor id, position) of a simulated person this many seconds into the alarm."""
    if person.out_from_start and len(person.track) >= 2:
        return person.track[-1][1], person.track[-1][2]
    if person.leave_after_s is None or not person.track or elapsed <= person.leave_after_s:
        return person.track[0][1] if person.track else "", person.start
    t = elapsed - person.leave_after_s
    for (t0, floor0, point0), (t1, floor1, point1) in zip(person.track, person.track[1:]):
        if t < t1:
            if floor0 != floor1 or t1 <= t0:
                return floor0, point0  # on the stairs: last seen where the floor was left
            share = (t - t0) / (t1 - t0)
            return floor0, (point0[0] + (point1[0] - point0[0]) * share, point0[1] + (point1[1] - point0[1]) * share)
    return person.track[-1][1], person.track[-1][2]


def simulate_people(building_map: BuildingMap, count: int = SIMULATED_PEOPLE) -> list[Person]:
    """Simulated phone owners in occupiable rooms, with leave times seeded from the building id."""
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
    staying = set(rng.sample(range(count), max(1, math.ceil(count * STAY_SHARE))))
    people = []
    for index, name in enumerate(names):
        space_id = rng.choice(rooms)
        start = point_in_room(building_map, space_id, rng)
        leave = None if index in staying else round(rng.uniform(FIRST_LEAVE_S, LAST_LEAVE_S), 1)
        track = exit_track(building_map, space_id, start)
        if len(track) < 2:
            leave, track = None, [(0.0, building_map.spaces[space_id]["floor_id"], start)]
        people.append(Person(f"P{index + 1:02d}", name, space_id, start, leave, track))
    # Showcase people come from those who would leave anyway; without any exit route (no entrance) any will do.
    leavers = [person for person in people if person.leave_after_s is not None]
    pool = leavers if len(leavers) >= PRE_MARKED else [person for index, person in enumerate(people) if index not in staying]
    for person in rng.sample(pool, min(PRE_MARKED, len(pool))):
        person.out_from_start = True
    return people


class EmergencyMode:
    """The alarm of one building. It exposes everyone's location, so callers must restrict it to admins."""

    def __init__(self, building_map: BuildingMap, clock: Callable[[], float] = time.time) -> None:
        self.map = building_map
        self.clock = clock
        self.reason = ""
        self.started_at: float | None = None
        self.skipped_s = 0.0
        self.people: dict[str, Person] = {}
        self.phones: dict[str, PhoneFix] = {}  # D-id -> latest fix
        self.device_ids: dict[str, str] = {}  # session key -> D-id
        self.marks: dict[str, ManualExit] = {}

    @property
    def active(self) -> bool:
        return self.started_at is not None

    def require_active(self) -> None:
        if not self.active:
            raise EmergencyNotActive("No emergency is active. Start one first.")

    def start(self, reason: str = "Emergency") -> dict:
        if self.active:
            raise EmergencyAlreadyActive(f"An emergency is already active ('{self.reason}'). End it first.")
        self.people = {person.id: person for person in simulate_people(self.map)}
        self.reason = reason.strip() or "Emergency"
        self.started_at = self.clock()
        self.skipped_s = 0.0
        self.marks = {person_id: ManualExit(self.started_at, PRE_MARKED_BY, PRE_MARKED_NOTE)
                      for person_id, person in self.people.items() if person.out_from_start}
        return self.report()

    def end(self) -> dict:
        """Close the alarm and return the final report; every position and mark is discarded."""
        final = {**self.report(), "ended": True}
        self.reason, self.started_at, self.skipped_s = "", None, 0.0
        self.people, self.phones, self.device_ids, self.marks = {}, {}, {}, {}
        return final

    def elapsed_s(self) -> float:
        self.require_active()
        return self.clock() - self.started_at + self.skipped_s

    def fast_forward(self, seconds: float) -> None:
        """Demo only: move the simulated people ahead so the evacuation can be shown without waiting."""
        self.require_active()
        if not math.isfinite(seconds) or seconds < 0:
            raise EmergencyError(f"fast_forward_s must be a finite number of seconds >= 0, got {seconds}.")
        self.skipped_s += seconds

    def observe(self, phones: Iterable[PhoneFix]) -> None:
        """Take in the latest fixes of real sessions. A session that stops reporting keeps its last fix (stale)."""
        self.require_active()
        for fix in phones:
            if fix.key not in self.device_ids and fix.measured_at < self.started_at - PRESENCE_S:
                continue  # left the building or closed the app long before the alarm
            phone_id = self.device_ids.setdefault(fix.key, f"D{len(self.device_ids) + 1:02d}")
            known = self.phones.get(phone_id)
            if known is None or fix.measured_at >= known.measured_at:
                self.phones[phone_id] = fix
            else:
                known.name = fix.name

    def find_person(self, reference: str) -> str:
        """A person id by id ('P03', 'D01') or exact name, case-insensitive."""
        wanted = reference.strip().casefold()
        names = {**{pid: person.name for pid, person in self.people.items()},
                 **{pid: fix.name for pid, fix in self.phones.items()}}
        for person_id, name in names.items():
            if wanted == person_id.casefold() or (name and wanted == name.casefold()):
                return person_id
        known = "; ".join(f"{pid} ({name or 'unnamed phone'})" for pid, name in names.items())
        raise PersonNotFound(f"No person '{reference}' in this emergency. Use one of: {known}.")

    def mark_outside(self, reference: str, note: str, by: str) -> dict:
        """An admin confirms someone is outside, e.g. at the assembly point after leaving their phone inside."""
        self.require_active()
        person_id = self.find_person(reference)
        mark = self.marks.get(person_id)
        if mark is None:
            self.marks[person_id] = ManualExit(self.clock(), by.strip() or "admin", note.strip())
        else:
            mark.note = note.strip() or mark.note
        return self.record(person_id)

    def clear_mark(self, reference: str) -> None:
        """Undo a manual mark; the person's status follows their phone again."""
        self.require_active()
        self.marks.pop(self.find_person(reference), None)

    def located(self, person_id: str) -> dict:
        """kind, name, floor, position, automatic status, containing space, last seen and staleness."""
        now = self.clock()
        if person_id in self.people:
            person = self.people[person_id]
            floor_id, point = position_at(person, self.elapsed_s())
            status, space_id = classify(self.map, floor_id, point)
            return {"kind": SIMULATED, "name": person.name, "floor_id": floor_id, "point": point, "auto": status,
                    "space_id": space_id, "last_seen": now, "stale": False}
        fix = self.phones[person_id]
        status, space_id = classify(self.map, fix.floor_id, fix.point)
        known_floor = fix.floor_id in self.map.floors
        return {"kind": SESSION, "name": fix.name, "floor_id": fix.floor_id if known_floor else None,
                "point": fix.point if known_floor else None, "auto": status, "space_id": space_id,
                "last_seen": fix.measured_at, "stale": now - fix.measured_at > STALE_S}

    def record(self, person_id: str) -> dict:
        place = self.located(person_id)
        mark = self.marks.get(person_id)
        space_id = place["space_id"]
        return {
            "id": person_id, "name": place["name"], "kind": place["kind"],
            "status": OUTSIDE_MANUAL if mark else place["auto"], "auto_status": place["auto"],
            "floor_id": place["floor_id"],
            "position": [round(place["point"][0], 2), round(place["point"][1], 2)] if place["point"] else None,
            "space_id": space_id, "space_name": self.map.spaces[space_id]["name"] if space_id else None,
            "last_seen_at": iso(place["last_seen"]), "stale": place["stale"],
            "manual": {"marked_at": iso(mark.marked_at), "marked_by": mark.marked_by, "note": mark.note} if mark else None,
        }

    def report(self) -> dict:
        """Everyone in the alarm: inside first (stale fixes first among them), then outside, then marked outside."""
        self.require_active()
        records = sorted(
            (self.record(person_id) for person_id in [*self.people, *self.phones]),
            key=lambda record: (STATUS_ORDER.index(record["status"]), not record["stale"],
                                (record["name"] or "~").casefold(), record["id"]),
        )
        counts = {status: sum(record["status"] == status for record in records) for status in STATUS_ORDER}
        return {
            "building_id": self.map.data["building"]["id"], "active": True, "reason": self.reason,
            "started_at": iso(self.started_at), "elapsed_s": round(self.elapsed_s(), 1),
            "counts": {**counts, "stale": sum(record["stale"] and record["status"] == INSIDE for record in records),
                       "total": len(records)},
            "people": records[:MAX_PEOPLE],
        }

    def markers(self) -> list[dict]:
        """Current position and status of each located person, for drawing on the floor plans."""
        return [
            {"name": record["name"] or record["id"], "status": record["status"], "floor_id": record["floor_id"],
             "position": tuple(record["position"])}
            for record in self.report()["people"] if record["floor_id"] is not None
        ]
