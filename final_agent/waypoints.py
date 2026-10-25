"""Spoken-navigation geometry: a route's waypoints (doors, turns, connectors, stops, arrival) and the drawn walk.

Pure geometry on top of BuildingMap. The per-edge loop mirrors viewer.route_polylines so that distances match the
drawn route; the kit's length_m is never used.
"""

import math
from dataclasses import dataclass

from shapely.geometry import Point

from .building_map import DOOR_PREFIX, BuildingMap, RouteResult, door_landing, outline, walking_path
from .viewer import node_location

Point2 = tuple[float, float]

TURN_MIN_DEG = 35.0
TURN_PLAIN_DEG = 60.0
TURN_SHARP_DEG = 135.0
TURN_WINDOW_M = 3.0
DOOR_FOLD_M = 2.0


@dataclass(frozen=True)
class Waypoint:
    index: int
    kind: str  # "turn" | "door" | "connector_entry" | "connector_exit" | "stop" | "arrival"
    floor_id: str
    at: Point2  # plan metres, y up
    space_id: str  # room the user walks through toward this waypoint
    next_space_id: str | None  # room entered (door/stop/arrival); landing room for connector_exit
    name: str | None  # next room (door/stop), destination (arrival), connector name
    side: str | None  # turn/door exit side: left, right, slight_*, sharp_*
    distance_m: float  # drawn walking distance from the previous waypoint (or the walk start)
    arc_m: float  # cumulative drawn distance from the walk start
    connector_kind: str | None = None
    direction: str | None = None  # "up" | "down" for connector_* kinds
    target_floor_id: str | None = None
    target_floor_name: str | None = None


@dataclass(frozen=True)
class WalkSegment:
    floor_id: str
    space_id: str
    points: tuple[Point2, ...]  # drawn polyline of one room edge
    arc_start_m: float  # cumulative arc at points[0]


@dataclass(frozen=True)
class RouteWalk:
    waypoints: tuple[Waypoint, ...]
    segments: tuple[WalkSegment, ...]
    total_m: float
    space_ids: frozenset[str]  # every space on the route

    def project(self, floor_id: str, point: Point2, arc_min: float, arc_max: float) -> tuple[float, float] | None:
        """(arc_m, lateral_m) of the nearest point on the drawn walk of floor_id within [arc_min, arc_max]."""
        best: tuple[float, float] | None = None
        for segment in self.segments:
            if segment.floor_id != floor_id:
                continue
            arc = segment.arc_start_m
            for first, second in zip(segment.points, segment.points[1:]):
                length = math.dist(first, second)
                low, high = max(arc, arc_min), min(arc + length, arc_max)
                if low <= high and length > 0:
                    # Clip the leg to the allowed arc range, then drop the point on the clipped piece.
                    a = _lerp(first, second, (low - arc) / length)
                    b = _lerp(first, second, (high - arc) / length)
                    along = _clamped_fraction(a, b, point)
                    candidate = (low + along * (high - low), math.dist(_lerp(a, b, along), point))
                    if best is None or candidate[1] < best[1]:
                        best = candidate
                arc += length
        return best


def _lerp(first: Point2, second: Point2, fraction: float) -> Point2:
    return (first[0] + (second[0] - first[0]) * fraction, first[1] + (second[1] - first[1]) * fraction)


def _clamped_fraction(first: Point2, second: Point2, point: Point2) -> float:
    dx, dy = second[0] - first[0], second[1] - first[1]
    squared = dx * dx + dy * dy
    if squared == 0:
        return 0.0
    return min(1.0, max(0.0, ((point[0] - first[0]) * dx + (point[1] - first[1]) * dy) / squared))


def spoken_distance(metres: float) -> str:
    if metres < 4:
        return "a few metres"
    if metres < 20:
        return f"{math.floor(metres + 0.5)} metres"
    return f"about {5 * math.floor(metres / 5 + 0.5)} metres"


def turn_label(degrees: float) -> str | None:
    """Label of a signed heading change in degrees (positive = left, y up); None below the turn threshold."""
    size = abs(degrees)
    if size < TURN_MIN_DEG:
        return None
    side = "left" if degrees > 0 else "right"
    if size < TURN_PLAIN_DEG:
        return f"slight_{side}"
    return side if size <= TURN_SHARP_DEG else f"sharp_{side}"


def detect_turns(points: list[Point2]) -> list[tuple[int, str]]:
    """(vertex index, side) of every turn: >= 35 degrees accumulated within a 3 m window, filtered sequentially.

    Once a turn is reported the window restarts, so a later bend never cancels an earlier turn.
    """
    turns: list[tuple[int, str]] = []
    window: list[tuple[float, float]] = []  # (arc at the bend vertex, signed bend in degrees)
    arc = 0.0
    previous_heading: float | None = None
    for index in range(1, len(points)):
        length = math.dist(points[index - 1], points[index])
        if length == 0:
            continue
        heading = math.atan2(points[index][1] - points[index - 1][1], points[index][0] - points[index - 1][0])
        if previous_heading is not None:
            bend = math.degrees((heading - previous_heading + math.pi) % (2 * math.pi) - math.pi)
            window = [(at, value) for at, value in window if arc - at <= TURN_WINDOW_M]
            window.append((arc, bend))
            label = turn_label(sum(value for _, value in window))
            if label is not None:
                turns.append((index - 1, label))
                window = []
        previous_heading = heading
        arc += length
    return turns


def space_containing(building_map: BuildingMap, floor_id: str, point: Point2, prefer=()) -> str | None:
    """The space strictly containing the point on this floor; a preferred space wins, then the smallest. No fallback."""
    level = building_map.floor_level(floor_id)
    candidates = []
    for result in building_map.spatial_search(point[0], point[1], level, radius_m=0, kind="space"):
        polygon = outline(building_map.spaces[result["id"]]["polygon"])
        if polygon.contains(Point(point)):
            candidates.append((result["id"] not in prefer, polygon.area, result["id"]))
    return min(candidates)[2] if candidates else None


def _stop_nodes(route: RouteResult) -> dict[int, str]:
    """Node index to via-stop space: the stop room's entry door when the route crosses one, else its anchor."""
    nodes, elements = route.node_path, route.edge_path
    found: dict[int, str] = {}
    cursor = 0
    for stop in route.stops[1:-1]:
        while cursor < len(nodes) and nodes[cursor] != stop:
            cursor += 1
        if cursor >= len(nodes):
            break
        entry = cursor - 1
        door = entry >= 0 and nodes[entry].startswith(DOOR_PREFIX) and elements[entry] == stop
        found[entry if door else cursor] = stop
        cursor += 1
    return found


def route_walk(building_map: BuildingMap, route: RouteResult, start_point: Point2 | None = None) -> RouteWalk:
    nodes, elements = route.node_path, route.edge_path
    spaces = building_map.spaces
    segments: list[WalkSegment] = []
    # Vertices for turn detection: (point, arc, space id, phase). A run breaks at connectors and kit-fallback edges.
    runs: list[list[tuple[Point2, float, str, int]]] = []
    run: list[tuple[Point2, float, str, int]] | None = None
    arc_at_node: list[float] = []
    phase = 0  # number of connectors crossed so far; keeps events ordered across floors
    arc = 0.0
    for index, (first, second, element) in enumerate(zip(nodes, nodes[1:], elements)):
        arc_at_node.append(arc)
        if element in building_map.connectors:
            run = None
            phase += 1
            continue
        space = spaces[element]
        polygon = outline(space["polygon"])
        start, end = node_location(building_map, first)[1], node_location(building_map, second)[1]
        landing_start = door_landing(polygon, start) if first.startswith(DOOR_PREFIX) else start
        landing_end = door_landing(polygon, end) if second.startswith(DOOR_PREFIX) else end
        walk: list[Point2] = []
        if start_point is not None and index == 0:
            walk = walking_path(polygon, tuple(start_point), landing_end)
            if walk:
                start = tuple(start_point)
        if not walk:
            walk = walking_path(polygon, landing_start, landing_end)
        points: list[Point2] = []
        for point in [start, *walk, end]:
            if not points or points[-1] != point:
                points.append(point)
        segments.append(WalkSegment(space["floor_id"], element, tuple(points), arc))
        if not walk:
            run = None  # a straight kit-fallback line has no validated bends
        elif run is None:
            run = []
            runs.append(run)
        vertex_arc = arc
        for offset, point in enumerate(points):
            if offset:
                vertex_arc += math.dist(points[offset - 1], point)
            if run is not None and not (run and run[-1][0] == point):
                run.append((point, vertex_arc, element, phase))
        arc = vertex_arc
    arc_at_node.append(arc)
    total = arc

    events: list[tuple[tuple[int, float, int], dict]] = []  # ((phase, arc, rank), waypoint fields)

    def add(event_phase: int, at_arc: float, rank: int, **fields) -> None:
        events.append(((event_phase, at_arc, rank), {"arc_m": at_arc, "side": None, **fields}))

    stops = _stop_nodes(route)
    phase = 0
    for index, element in enumerate(elements):
        node = nodes[index + 1]
        if element in building_map.connectors:
            connector = building_map.connectors[element]
            before_floor, before_point = node_location(building_map, nodes[index])
            after_floor, after_point = node_location(building_map, node)
            shared = {"connector_kind": connector["kind"], "name": connector["name"],
                      "direction": "up" if building_map.floor_level(after_floor) > building_map.floor_level(before_floor) else "down"}
            add(phase, arc_at_node[index], 2, kind="connector_entry", floor_id=before_floor, at=before_point,
                space_id=nodes[index], next_space_id=None, target_floor_id=after_floor,
                target_floor_name=building_map.floor_name(after_floor), **shared)
            phase += 1
            add(phase, arc_at_node[index + 1], -1, kind="connector_exit", floor_id=after_floor, at=after_point,
                space_id=node, next_space_id=node, target_floor_id=before_floor,
                target_floor_name=building_map.floor_name(before_floor), **shared)
        elif node.startswith(DOOR_PREFIX) and index + 1 < len(elements) and elements[index + 1] != element:
            into = elements[index + 1]
            floor_id, point = node_location(building_map, node)
            add(phase, arc_at_node[index + 1], 0, kind="stop" if index + 1 in stops else "door", floor_id=floor_id,
                at=point, space_id=element, next_space_id=into, name=spaces[into]["name"])
    for node_index, stop in stops.items():
        if not nodes[node_index].startswith(DOOR_PREFIX):
            floor_id, point = node_location(building_map, nodes[node_index])
            crossed = sum(1 for element in elements[:node_index] if element in building_map.connectors)
            add(crossed, arc_at_node[node_index], 0, kind="stop", floor_id=floor_id, at=point, space_id=stop,
                next_space_id=stop, name=spaces[stop]["name"])
    destination = route.destination_space_id
    floor_id, point = node_location(building_map, nodes[-1])
    add(phase, total, 5, kind="arrival", floor_id=floor_id, at=point,
        space_id=elements[-1] if elements and elements[-1] in spaces else destination,
        next_space_id=destination, name=spaces[destination]["name"])

    for vertices in runs:
        for vertex, side in detect_turns([item[0] for item in vertices]):
            point, at_arc, space_id, event_phase = vertices[vertex]
            door = next((fields for key, fields in reversed(events)
                         if fields["kind"] in ("door", "stop") and fields["side"] is None and key[0] == event_phase
                         and 0 <= at_arc - key[1] <= DOOR_FOLD_M), None)
            if door is not None:
                door["side"] = side  # the turn right after a door is how to leave through it
            else:
                add(event_phase, at_arc, 1, kind="turn", floor_id=spaces[space_id]["floor_id"], at=point,
                    space_id=space_id, next_space_id=None, name=None, side=side)

    waypoints: list[Waypoint] = []
    previous = 0.0
    for position, (_, fields) in enumerate(sorted(events, key=lambda item: item[0])):
        waypoints.append(Waypoint(index=position, distance_m=fields["arc_m"] - previous, **fields))
        previous = fields["arc_m"]
    space_ids = frozenset(route.space_path) | {element for element in elements if element in spaces}
    return RouteWalk(tuple(waypoints), tuple(segments), total, space_ids)
