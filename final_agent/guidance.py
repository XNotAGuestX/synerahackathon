"""Turn-by-turn guidance for an active route: checkpoints, spoken phrasing and the walk-through state.

Plan coordinates are metres with y up, so a counter-clockwise bend is a left turn. Everything here is
deterministic: no model call and no network. The voice session reads the text handed out by drain().
"""

import itertools
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from .building_map import (
    DOOR_PREFIX, OUTSIDE, BuildingMap, MapError, Point2, RouteResult, check_number, door_landing, outline, walking_path,
)
from .viewer import node_location

CHECKPOINT_RADIUS_M = 2.5      # reached when this close; a worse fix widens the radius up to MAX_ACCURACY_RADIUS_M
MAX_ACCURACY_RADIUS_M = 6.0
DOOR_REACHED_M = 1.0           # a door is reached this close or in the room behind it; accuracy does not widen this
STALE_POSITION_S = 15.0        # an older position means tracking is "lost"
TURN_MIN_DEGREES = 35.0        # smaller bends are not announced
TURN_MIN_SEGMENT_M = 1.5       # a bend after a shorter segment is not announced
MERGE_RADIUS_M = 2.0           # a turn this close to a neighbouring checkpoint is dropped
OFF_ROUTE_UPDATES = 2          # consecutive fixes outside the route before rerouting
SAME_POINT_M = 1e-6            # vertices this close together are one vertex
DEPARTURE_WINDOW_M = 2.0       # the heading before and after a checkpoint is measured over this much path
DEPARTURE_MIN_PATH_M = 0.5     # a departure turn needs this much path on both sides of the checkpoint

OPENERS = {
    "en": ("", "Okay, ", "Now, ", "Next, "),
    "de": ("", "Okay, ", "Jetzt ", "Als Nächstes "),
}
TEXT = {
    "en": {
        "few_metres": "a few metres", "metres": "{value} metres", "about_metres": "about {value} metres",
        "left": "left", "right": "right", "slight": "slightly", "sharp": "sharp", "up": "up", "down": "down",
        "turn": "go straight for {distance}, then turn {side}.",
        "turn_in": "in {distance}, turn {side}.",
        "door": "walk {distance} and go through the door into {name}.",
        "door_in": "in {distance}, head into {name} through the door.",
        "door_turn": "turn {side}, then walk {distance} to the door into {name}.",
        "connector": "take {name} {direction} to {floor}.",
        "approach": "it's {distance} to {name} — you'll be there.",
        "approach_walk": "walk {distance} to {name} and you're there.",
        "approach_turn": "turn {side} — {name} is {distance} ahead.",
        "arrived": "You've arrived — this is {name}.",
        "prompt": " Tell me when you're there.",
        "stay": " I'll be here if you need me.",
        "stopped": "Okay, stopping navigation.",
        "reroute": "No problem, let me reroute you. ",
        "changed": "The route changed — ",
        "blocked": "That way is blocked now and I can't find another route.",
        "failed": "Sorry, I can't find another way to {name} from here, so I'm stopping navigation.",
        "lost": "I've lost your position for a moment — just tell me when you get there.",
    },
    "de": {
        "few_metres": "ein paar Meter", "metres": "{value} Meter", "about_metres": "etwa {value} Meter",
        "left": "links", "right": "rechts", "slight": "leicht", "sharp": "scharf", "up": "nach oben", "down": "nach unten",
        "turn": "geh {distance} geradeaus und dann {side}.",
        "turn_in": "geh {distance}, dann biege {side} ab.",
        "door": "geh {distance} bis zur Tür und dann in {name}.",
        "door_in": "geh {distance}, dann durch die Tür in {name}.",
        "door_turn": "bieg {side} ab und geh {distance} bis zur Tür in {name}.",
        "connector": "nimm {name} {direction} zu {floor}.",
        "approach": "geh {distance} bis {name}, dann bist du da.",
        "approach_walk": "geh noch {distance} bis {name}.",
        "approach_turn": "bieg {side} ab — {name} ist {distance} entfernt.",
        "arrived": "Du bist da — das ist {name}.",
        "prompt": " Sag Bescheid, wenn du da bist.",
        "stay": " Ich bin hier, falls du mich brauchst.",
        "stopped": "Okay, ich beende die Navigation.",
        "reroute": "Kein Problem, ich berechne die Route neu. ",
        "changed": "Die Route hat sich geändert — ",
        "blocked": "Dieser Weg ist jetzt blockiert, und ich finde keine andere Route.",
        "failed": "Tut mir leid, von hier finde ich keinen anderen Weg nach {name}, deshalb beende ich die Navigation.",
        "lost": "Ich habe deine Position kurz verloren — sag mir einfach Bescheid, wenn du da bist.",
    },
}


@dataclass
class Checkpoint:
    kind: str                  # "turn" | "door" | "connector" | "arrival"
    floor_id: str
    position: Point2
    space_id: str              # space walked through while approaching it
    distance_m: float          # walking distance from the previous checkpoint (or start)
    name: str                  # door: next space name; connector: connector name; arrival: destination name; turn: ""
    next_space_id: str | None = None    # door/connector: space entered after it
    turn: str | None = None             # turn: "left" | "right" | "slight left" | "slight right" | "sharp left" | "sharp right"
    connector_kind: str | None = None   # "stairs" | "lift"
    target_floor_id: str | None = None  # connector only
    departure: str | None = None        # door/arrival: turn made at the previous checkpoint to head here


@dataclass
class _Fix:
    """The latest position report: plan metres on one floor, and when it arrived."""
    floor_level: int
    floor_id: str
    point: Point2
    accuracy_m: float | None
    seen_at: float


def route_checkpoints(building_map: BuildingMap, route: RouteResult) -> list[Checkpoint]:
    """Turns and doors along each walk, connectors, then arrival, in travel order.

    Walks are computed exactly as viewer.route_polylines draws them, so spoken turns match the map.
    """
    nodes = route.node_path
    timed: list[tuple[Checkpoint, float, int]] = []  # checkpoint, metres walked to it, index of its segment
    segments: list[list[tuple[float, Point2]]] = [[]]  # walked path as (metres, point); cut at connectors and outside
    walked = 0.0
    for index, (first, second, element) in enumerate(zip(nodes, nodes[1:], route.edge_path)):
        if OUTSIDE in (first, second):
            segments.append([])  # outside has no place on a plan
            continue
        if element in building_map.connectors:
            timed.append((_connector_checkpoint(building_map, element, first, second), walked, len(segments) - 1))
            segments.append([])  # the path resumes on another floor
            continue
        points = _walk_points(building_map, first, second, element)
        floor_id = building_map.spaces[element]["floor_id"]
        for metres, corner, label in _walk_turns(points):
            turn = Checkpoint(kind="turn", floor_id=floor_id, position=corner, space_id=element,
                              distance_m=0.0, name="", turn=label)
            timed.append((turn, walked + metres, len(segments) - 1))
        walked = _extend_segment(segments[-1], walked, points)
        if second.startswith(DOOR_PREFIX):
            # A door is never the last node: the route ends in a space, so the next edge walks the space beyond.
            door = _door_checkpoint(building_map, second, element, route.edge_path[index + 1])
            timed.append((door, walked, len(segments) - 1))
    destination = route.destination_space_id
    floor_id, point = node_location(building_map, destination)
    arrival = Checkpoint(
        kind="arrival", floor_id=floor_id, position=point, space_id=destination, distance_m=0.0,
        name=building_map.spaces[destination]["name"],
    )
    timed.append((arrival, walked, len(segments) - 1))
    return _measure(timed, segments)


def _connector_checkpoint(building_map: BuildingMap, connector_id: str, boarding: str, arriving: str) -> Checkpoint:
    connector = building_map.connectors[connector_id]
    floor_id, point = node_location(building_map, boarding)
    return Checkpoint(
        kind="connector", floor_id=floor_id, position=point, space_id=boarding, distance_m=0.0,
        name=connector["name"], next_space_id=arriving, connector_kind=connector["kind"],
        target_floor_id=node_location(building_map, arriving)[0],
    )


def _door_checkpoint(building_map: BuildingMap, door_node: str, space_id: str, next_space_id: str) -> Checkpoint:
    floor_id, point = node_location(building_map, door_node)
    return Checkpoint(
        kind="door", floor_id=floor_id, position=point, space_id=space_id, distance_m=0.0,
        name=building_map.spaces[next_space_id]["name"], next_space_id=next_space_id,
    )


def _walk_points(building_map: BuildingMap, first: str, second: str, space_id: str) -> list[Point2]:
    """The walk through one space between two nodes: doors are entered 30 cm inside the room, as on the map."""
    polygon = outline(building_map.spaces[space_id]["polygon"])
    start = node_location(building_map, first)[1]
    end = node_location(building_map, second)[1]
    landing_start = door_landing(polygon, start) if first.startswith(DOOR_PREFIX) else start
    landing_end = door_landing(polygon, end) if second.startswith(DOOR_PREFIX) else end
    walk = walking_path(polygon, landing_start, landing_end)
    if not walk:
        name = building_map.spaces[space_id]["name"]
        raise MapError(f"There is no walkable path through {name}, so I can't give directions for this route.")
    return _distinct([start, *walk, end])


def _distinct(points: list[Point2]) -> list[Point2]:
    """Drop repeated vertices so every bend has a real direction in and out."""
    result: list[Point2] = []
    for point in points:
        if not result or math.dist(result[-1], point) > SAME_POINT_M:
            result.append(point)
    return result


def _walk_turns(points: list[Point2]) -> list[tuple[float, Point2, str]]:
    """Announced bends of one walk as (metres walked to the bend, its position, turn label)."""
    turns = []
    walked = 0.0
    for before, corner, after in zip(points, points[1:], points[2:]):
        segment = math.dist(before, corner)
        walked += segment
        label = _turn_label(_bend_degrees(before, corner, after))
        if label and segment >= TURN_MIN_SEGMENT_M:
            turns.append((walked, corner, label))
    return turns


def _bend_degrees(before: Point2, corner: Point2, after: Point2) -> float:
    """Heading change at `corner` in degrees; positive is a left turn (counter-clockwise with y up)."""
    ax, ay = corner[0] - before[0], corner[1] - before[1]
    bx, by = after[0] - corner[0], after[1] - corner[1]
    return math.degrees(math.atan2(ax * by - ay * bx, ax * bx + ay * by))


def _turn_label(degrees: float) -> str | None:
    """English turn words for a bend of this size, or None when it is too small to announce."""
    size = abs(degrees)
    if size < TURN_MIN_DEGREES:
        return None
    side = "left" if degrees > 0 else "right"
    if size < 60:
        return f"slight {side}"
    if size <= 135:
        return side
    return f"sharp {side}"


def _extend_segment(segment: list[tuple[float, Point2]], metres: float, points: list[Point2]) -> float:
    """Append one walk to a continuous path and return the metres walked at its end.

    A walk starts where the previous one ended, so its first point is only added to a new segment.
    """
    if not segment:
        segment.append((metres, points[0]))
    for before, after in itertools.pairwise(points):
        metres += math.dist(before, after)
        segment.append((metres, after))
    return metres


def _measure(timed: list[tuple[Checkpoint, float, int]], segments: list[list[tuple[float, Point2]]]) -> list[Checkpoint]:
    """Drop turns within MERGE_RADIUS_M of a neighbouring checkpoint (the door or arrival already says where to go),
    then give each kept checkpoint its distance and departure turn from the previous kept one."""
    kept = []
    for index, entry in enumerate(timed):
        neighbours = [timed[i][0] for i in (index - 1, index + 1) if 0 <= i < len(timed)]
        if entry[0].kind == "turn" and any(_near(entry[0], other) for other in neighbours):
            continue
        kept.append(entry)
    previous = None
    for entry in kept:
        checkpoint, metres, _ = entry
        checkpoint.distance_m = metres - (previous[1] if previous else 0.0)
        checkpoint.departure = _departure(previous, checkpoint, segments)
        previous = entry
    return [checkpoint for checkpoint, _, _ in kept]


def _near(first: Checkpoint, second: Checkpoint) -> bool:
    return first.floor_id == second.floor_id and math.dist(first.position, second.position) <= MERGE_RADIUS_M


def _departure(
    previous: tuple[Checkpoint, float, int] | None, current: Checkpoint, segments: list[list[tuple[float, Point2]]],
) -> str | None:
    """The turn made at the previous checkpoint to head for `current`.

    Orientation is unknown after stairs or a lift, and a turn checkpoint has already announced its own bend,
    so neither gives a departure turn.
    """
    if previous is None or current.kind == "turn" or previous[0].kind in ("connector", "turn"):
        return None
    _, metres, segment = previous
    return _heading_change(segments[segment], metres)


def _heading_change(segment: list[tuple[float, Point2]], metres: float) -> str | None:
    """Turn words for the heading change at `metres` along one continuous path, or None when either side of the
    point has less than DEPARTURE_MIN_PATH_M of path."""
    if len(segment) < 2 or metres - segment[0][0] < DEPARTURE_MIN_PATH_M or segment[-1][0] - metres < DEPARTURE_MIN_PATH_M:
        return None
    before = _point_at(segment, metres - DEPARTURE_WINDOW_M)
    here = _point_at(segment, metres)
    after = _point_at(segment, metres + DEPARTURE_WINDOW_M)
    return _turn_label(_bend_degrees(before, here, after))


def _point_at(segment: list[tuple[float, Point2]], metres: float) -> Point2:
    """The point `metres` along one continuous path, clamped to its ends."""
    metres = min(max(metres, segment[0][0]), segment[-1][0])
    for (start, first), (end, second) in itertools.pairwise(segment):
        if metres <= end:
            share = (metres - start) / (end - start)
            return (first[0] + (second[0] - first[0]) * share, first[1] + (second[1] - first[1]) * share)
    return segment[-1][1]


def spoken_distance(metres: float, language: str = "en") -> str:
    """Rounded for speech: 'a few' under 4 m, whole metres under 20 m, then the nearest 5 m."""
    if metres < 4:
        return _text(language, "few_metres")
    if metres < 20:
        return _text(language, "metres", value=str(round(metres)))
    return _text(language, "about_metres", value=str(5 * round(metres / 5)))


def instruction(checkpoint: Checkpoint, index: int, building_map: BuildingMap, language: str = "en") -> str:
    """The sentence that walks the user to `checkpoint`. `index` picks the opener and wording, so repeats vary."""
    distance = spoken_distance(checkpoint.distance_m, language)
    variant = index % 2
    if checkpoint.kind == "turn":
        side = _side_words(checkpoint.turn, language)
        body = _text(language, "turn_in" if variant else "turn", distance=distance, side=side)
    elif checkpoint.kind == "door" and checkpoint.departure:
        side = _side_words(checkpoint.departure, language)
        body = _text(language, "door_turn", distance=distance, side=side, name=checkpoint.name)
    elif checkpoint.kind == "door":
        body = _text(language, "door_in" if variant else "door", distance=distance, name=checkpoint.name)
    elif checkpoint.kind == "connector":
        up = building_map.floor_level(checkpoint.target_floor_id) > building_map.floor_level(checkpoint.floor_id)
        floor = _floor_words(building_map.floor_name(checkpoint.target_floor_id), language)
        body = _text(
            language, "connector", name=_with_the(checkpoint.name, language),
            direction=_text(language, "up" if up else "down"), floor=_with_the(floor, language),
        )
    elif checkpoint.departure:
        side = _side_words(checkpoint.departure, language)
        body = _text(language, "approach_turn", distance=distance, side=side, name=checkpoint.name)
    else:
        body = _text(language, "approach_walk" if variant else "approach", distance=distance, name=checkpoint.name)
    return _opened(body, index, language)


def _lang(language: str) -> str:
    return "de" if language.lower().startswith("de") else "en"


def _text(language: str, key: str, **values: str) -> str:
    return TEXT[_lang(language)][key].format(**values)


def _side_words(turn: str, language: str) -> str:
    """Turn words in the phrase language, word by word: 'slight left' is 'slightly left' in English."""
    return " ".join(TEXT[_lang(language)][word] for word in turn.split())


def _opened(body: str, index: int, language: str) -> str:
    """Prefix an opener chosen by index; without one the sentence starts with a capital."""
    openers = OPENERS[_lang(language)]
    opener = openers[index % len(openers)]
    return opener + body if opener else body[:1].upper() + body[1:]


def _floor_words(name: str, language: str) -> str:
    """English floor names always read as a floor ('Ground floor', 'Floor 1', 'First floor')."""
    if _lang(language) == "de" or "floor" in name.lower():
        return name
    return f"{name} floor"


def _with_the(phrase: str, language: str) -> str:
    """English 'the' before a place, but not after a name ending in a number ('take Lift 2', 'to Floor 1')."""
    if _lang(language) == "de" or phrase[-1:].isdigit():
        return phrase
    return f"the {phrase}"


def _reached(checkpoint: Checkpoint, fix: _Fix, space_id: str | None, radius: float) -> bool:
    """Whether the latest fix shows the user has got to this checkpoint.

    A connector counts only once the user is on its far floor: standing at the boarding point is not yet taking it.
    A door counts only in the room behind it or right at it: the first door is often within the checkpoint radius
    of the start, so a loose fix there must not skip it.
    """
    if checkpoint.kind == "connector":
        return fix.floor_id == checkpoint.target_floor_id
    goal = checkpoint.space_id if checkpoint.kind == "arrival" else checkpoint.next_space_id
    if space_id is not None and space_id == goal:
        return True
    limit = DOOR_REACHED_M if checkpoint.kind == "door" else radius
    return fix.floor_id == checkpoint.floor_id and math.dist(fix.point, checkpoint.position) <= limit


class Guidance:
    """Walks one user along a route: speaks each step, advances on confirmation or live position, reroutes off the route.

    Speech is queued and handed out by drain(). Nothing here calls a model or the network.
    """

    def __init__(self, building_map: BuildingMap, clock: Callable[[], float] = time.monotonic) -> None:
        self.building_map = building_map
        self.clock = clock
        self.language = "en"
        self.confirm_each_step = True
        self.route: RouteResult | None = None
        self._checkpoints: list[Checkpoint] = []
        self._index = 0
        self._off_route_updates = 0
        self._fix: _Fix | None = None
        self._was_live = False
        self._queue: list[str] = []

    @property
    def active(self) -> bool:
        return self.route is not None

    def tracking(self) -> str:
        if self._fix is None:
            return "none"
        return "live" if self.clock() - self._fix.seen_at <= STALE_POSITION_S else "lost"

    def drain(self) -> list[str]:
        """Speech queued since the last drain, in order."""
        queued, self._queue = self._queue, []
        return queued

    def start(self, route: RouteResult) -> None:
        self._begin(route)
        if not self.active:
            return
        if not self.confirm_each_step and self.tracking() != "live":
            # No position and no confirmations: read the whole route once. confirm() after that ends guidance.
            self._index = len(self._checkpoints) - 1
            reading = " ".join(
                instruction(step, index, self.building_map, self.language) for index, step in enumerate(self._checkpoints)
            )
            self._queue.append(reading + _text(self.language, "stay"))
        else:
            self._queue.append(self._announce(0))

    def stop(self) -> bool:
        if not self.active:
            return False
        self._queue.append(_text(self.language, "stopped"))
        self._clear()
        return True

    def confirm(self) -> None:
        """The user says they reached the next checkpoint: move on, or finish after the last one."""
        if not self.active:
            return
        if self._index == len(self._checkpoints) - 1:
            self._finish()
        else:
            self._move_to(self._index + 1)

    def repeat(self) -> None:
        if self.active:
            self._queue.append(self._announce(self._index))

    def adopt(self, route: RouteResult | None) -> None:
        """The map's active route changed (for example a closure). None means the destination is now unreachable."""
        if not self.active or route is self.route:
            return
        if route is None:
            self._queue.append(_text(self.language, "blocked"))
            self._clear()
        elif route.destination_space_id == self.route.destination_space_id:
            self._begin(route)
            if self.active:
                first = self._announce(0)
                self._queue.append(_text(self.language, "changed") + first[:1].lower() + first[1:])

    def update_position(self, floor_level: int, x_m: float, y_m: float, accuracy_m: float | None = None) -> None:
        """A position report. Only the latest one counts; it is kept even while guidance is off."""
        floor_id = self.building_map.floor_by_level(floor_level)["id"]
        x_m, y_m = check_number("x_m", x_m), check_number("y_m", y_m)
        if accuracy_m is not None:
            accuracy_m = check_number("accuracy_m", accuracy_m, 0)
        self._fix = _Fix(floor_level, floor_id, (x_m, y_m), accuracy_m, self.clock())
        self._was_live = True
        if self.active:
            self._follow()

    def tick(self) -> None:
        """Call regularly. Announces once when a live position goes stale during guidance."""
        if self.tracking() == "lost" and self._was_live:
            self._was_live = False
            if self.active:
                self._queue.append(_text(self.language, "lost"))

    def status(self) -> dict:
        destination = None
        upcoming = None
        remaining = 0.0
        if self.active:
            destination = {"id": self.route.destination_space_id, "name": self._checkpoints[-1].name}
            step = self._checkpoints[self._index]
            upcoming = {
                "index": self._index, "kind": step.kind, "name": step.name,
                "floor_level": self.building_map.floor_level(step.floor_id), "position": list(step.position),
                "instruction": instruction(step, self._index, self.building_map, self.language),
            }
            remaining = sum(checkpoint.distance_m for checkpoint in self._checkpoints[self._index:])
        return {
            "active": self.active, "destination": destination, "next": upcoming,
            "progress": [self._index, len(self._checkpoints)], "remaining_m": round(remaining, 1),
            "tracking": self.tracking(), "confirm_each_step": self.confirm_each_step, "language": self.language,
        }

    def _begin(self, route: RouteResult) -> None:
        """Make `route` the one being walked, from its first checkpoint. Raises MapError before changing anything."""
        checkpoints = route_checkpoints(self.building_map, route)
        self.route, self._checkpoints, self._index, self._off_route_updates = route, checkpoints, 0, 0
        if len(checkpoints) == 1:
            self._finish()  # start and destination share a space: there is nothing to walk

    def _announce(self, index: int) -> str:
        """The instruction for checkpoint `index`, plus a prompt to confirm it while no live position is available."""
        text = instruction(self._checkpoints[index], index, self.building_map, self.language)
        if index < 2 and self.confirm_each_step and self.tracking() != "live":
            text += _text(self.language, "prompt")
        return text

    def _move_to(self, index: int) -> None:
        self._index = index
        self._off_route_updates = 0
        self._queue.append(self._announce(index))

    def _finish(self) -> None:
        self._queue.append(_text(self.language, "arrived", name=self._checkpoints[-1].name))
        self._clear()

    def _clear(self) -> None:
        self.route, self._checkpoints, self._index, self._off_route_updates = None, [], 0, 0

    def _follow(self) -> None:
        """Advance past the checkpoints the latest fix reaches; otherwise count it towards going off the route."""
        fix = self._fix
        space_id = self.building_map.space_at(fix.floor_level, *fix.point)
        radius = max(CHECKPOINT_RADIUS_M, min(fix.accuracy_m or 0.0, MAX_ACCURACY_RADIUS_M))
        checkpoints, last = self._checkpoints, len(self._checkpoints) - 1
        index = self._index
        if space_id is not None and space_id != checkpoints[index].space_id:
            # The user is already in a space the route enters later, so the checkpoints before it were passed.
            passed = [k for k in range(index, last) if checkpoints[k].next_space_id == space_id]
            if passed:
                index = passed[0] + 1
        while index < last and _reached(checkpoints[index], fix, space_id, radius):
            index += 1
        if index == last and _reached(checkpoints[last], fix, space_id, radius):
            self._finish()
        elif index != self._index:
            self._move_to(index)
        else:
            self._check_route(space_id)

    def _check_route(self, space_id: str | None) -> None:
        """Reroute from the user's space after OFF_ROUTE_UPDATES fixes in a space the route no longer uses."""
        if space_id is None or space_id in self._spaces_ahead():
            self._off_route_updates = 0
            return
        self._off_route_updates += 1
        if self._off_route_updates >= OFF_ROUTE_UPDATES:
            self._reroute(space_id)

    def _spaces_ahead(self) -> set[str]:
        """Spaces of the walk to the next checkpoint and beyond. The previous checkpoint's space counts too,
        because a door is reached by distance while the user may still stand in the room before it."""
        spaces: set[str] = set()
        for checkpoint in self._checkpoints[max(self._index - 1, 0):]:
            spaces.add(checkpoint.space_id)
            if checkpoint.next_space_id is not None:
                spaces.add(checkpoint.next_space_id)
        return spaces

    def _reroute(self, space_id: str) -> None:
        old = self.route
        try:
            new = self.building_map.route(
                space_id, old.destination_space_id, step_free=old.step_free, min_width_m=old.min_width_m,
            )
            self._begin(new)
        except MapError:
            self._queue.append(_text(self.language, "failed", name=self._checkpoints[-1].name))
            self._clear()
            return
        if self.active:
            self._queue.append(_text(self.language, "reroute") + self._announce(0))
