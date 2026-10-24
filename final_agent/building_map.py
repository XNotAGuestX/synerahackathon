"""Deterministic core of the project agent: load a building.json, search it, route through it, edit it.

The agent (agent.py) is only the conversation layer; every fact it states comes from this module.
The route cost model matches the one used to compute the dataset's expected answers."""

import contextlib
import itertools
import math
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, nearest_points

from .storage import BuildingSpatialIndex, JsonBuildingStore

OUTSIDE = "outside"
DOOR_PREFIX = "door:"
LIFT = "lift"
STAIRS_COST_PER_FLOOR_M = 12.0
LIFT_WAIT_COST_M = 15.0
LIFT_COST_PER_FLOOR_M = 6.0
MAX_SEARCH_RESULTS = 15
SHARED_WALL_TOLERANCE_M = 0.35
NEW_DOOR_WIDTH_M = 0.9
KIT_DISTANCE_MODEL = "kit"
GEOMETRY_EPSILON = 1e-9


class MapError(ValueError):
    """Raised for anything the user should be told about (unknown place, no route, ...)."""


def check_number(name: str, value: float, minimum: float | None = None) -> float:
    """Validate a numeric tool argument at the boundary: finite and, optionally, at least minimum."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise MapError(f"{name} must be a finite number, got {value!r}.")
    if minimum is not None and value < minimum:
        raise MapError(f"{name} must be at least {minimum}, got {value}.")
    return float(value)


def normalize_type(value: str) -> str:
    """Canonical type name: 'Meeting Room', 'meeting-room' and 'meeting_room' all give 'meeting_room'."""
    return "_".join(value.strip().lower().replace("-", " ").replace("_", " ").split())


@dataclass
class RouteResult:
    """A computed route. Lengths are unrounded; round only when presenting.

    node_path holds the graph nodes (spaces, 'door:<opening id>', 'outside'). element_path has one entry
    per traversed edge: the opening id for space/door and outside/door edges, the connector id for
    stair/lift edges. min_width_m and entrance are the requested constraints. The length follows the
    kit model (anchor-to-door distances); an entrance only has to be valid, it adds no length.
    """

    start_space_id: str
    destination_space_id: str
    length_m: float
    space_path: list[str]
    steps: list[str]
    step_free: bool
    closed: list[str] = field(default_factory=list)
    stops: list[str] = field(default_factory=list)
    node_path: list[str] = field(default_factory=list)
    element_path: list[str] = field(default_factory=list)
    legs: list[dict] = field(default_factory=list)
    floor_segments: list[dict] = field(default_factory=list)
    min_width_m: float = 0.0
    entrance: str | None = None
    distance_model: str = KIT_DISTANCE_MODEL


class BuildingMap:
    def __init__(self, building: dict) -> None:
        self.data = building
        self.floors = {floor["id"]: floor for floor in building["floors"]}
        self.spaces = {space["id"]: space for space in building["spaces"]}
        self.assets = {asset["id"]: asset for asset in building["assets"]}
        self.connectors = {connector["id"]: connector for connector in building["vertical_connectors"]}
        self.openings = {opening["id"]: opening for opening in building["openings"]}
        self.closed: set[str] = set(building.get("navigation_state", {}).get("closed", []))
        self._spatial_index: BuildingSpatialIndex | None = None
        self.last_route: RouteResult | None = None
        self.active_request: dict | None = None
        self.located_asset_ids: list[str] = []

    @classmethod
    def load(cls, path: Path) -> "BuildingMap":
        return cls(JsonBuildingStore.load(path))

    # ---------- descriptions ----------

    def floor_name(self, floor_id: str) -> str:
        return self.floors[floor_id]["name"]

    def describe_space(self, space_id: str) -> str:
        space = self.spaces[space_id]
        return f"{space['name']} [{space_id}] on {self.floor_name(space['floor_id'])}"

    def overview(self) -> dict:
        info = self.data["building"]
        floors = []
        for floor in sorted(self.floors.values(), key=lambda item: item["level"]):
            rooms = [space for space in self.spaces.values() if space["floor_id"] == floor["id"]]
            floors.append({"level": floor["level"], "name": floor["name"], "spaces": len(rooms)})
        return {
            "name": info["name"],
            "source": info["source"],
            "floors": floors,
            "stairs_and_lifts": [
                {
                    "id": connector["id"],
                    "name": connector["name"],
                    "kind": connector["kind"],
                    "floors": [self.floor_name(floor_id) for floor_id in connector["floor_ids"]],
                }
                for connector in self.connectors.values()
            ],
            "entrances": [
                {
                    "id": opening["id"],
                    "into": self.describe_space(self.other_side(opening, OUTSIDE)),
                    "step_free": opening["step_free"],
                }
                for opening in self.openings.values()
                if OUTSIDE in opening["space_ids"]
            ],
            "asset_count": len(self.assets),
            "closed": sorted(self.closed),
        }

    @staticmethod
    def other_side(opening: dict, space_id: str) -> str:
        first, second = opening["space_ids"]
        return second if first == space_id else first

    # ---------- shared lookups and geometry ----------

    def floor_by_level(self, floor_level: int) -> dict:
        """The floor record with this level; unknown levels list the valid ones."""
        for floor in self.floors.values():
            if floor["level"] == floor_level:
                return floor
        levels = sorted(floor["level"] for floor in self.floors.values())
        raise MapError(f"Unknown floor level {floor_level!r}. This building has floor levels {levels}.")

    def floor_level(self, floor_id: str) -> int:
        return self.floors[floor_id]["level"]

    def space_polygon(self, space_id: str) -> Polygon:
        return Polygon(self.spaces[space_id]["polygon"])

    def space_area_m2(self, space_id: str) -> float:
        """Unrounded polygon area in square metres."""
        return self.space_polygon(space_id).area

    def space_summary(self, space_id: str) -> dict:
        """Compact identity of a space for tool results."""
        space = self.spaces[space_id]
        floor = self.floors[space["floor_id"]]
        return {
            "id": space_id, "name": space["name"], "ref": space.get("ref"),
            "type": space["type"], "room_type": space["room_type"],
            "floor_level": floor["level"], "floor": floor["name"],
        }

    def filter_spaces(
        self, floor_level: int | None = None, room_type: str | None = None, space_type: str | None = None
    ) -> list[dict]:
        """Every space matching exact, normalized filters, sorted by floor level, name and id.

        room_type is the space's subtype (office, lobby, warehouse_zone, ...); space_type is its broad
        source type (room, hall, corridor, stair, lift, outdoor). Never a substring match.
        """
        floor_id = self.floor_by_level(floor_level)["id"] if floor_level is not None else None
        wanted_room_type = normalize_type(room_type) if room_type else None
        wanted_space_type = normalize_type(space_type) if space_type else None
        matches = [
            space for space in self.spaces.values()
            if (floor_id is None or space["floor_id"] == floor_id)
            and (wanted_room_type is None or normalize_type(space["room_type"]) == wanted_room_type)
            and (wanted_space_type is None or normalize_type(space["type"]) == wanted_space_type)
        ]
        return sorted(matches, key=lambda space: (self.floor_level(space["floor_id"]), space["name"], space["id"]))

    def room_types(self, floor_level: int | None = None) -> list[str]:
        """Sorted distinct normalized room types, optionally on one floor; helps correct a wrong type name."""
        return sorted({normalize_type(space["room_type"]) for space in self.filter_spaces(floor_level)})

    # ---------- search ----------

    def search(self, query: str, floor_level: int | None = None) -> list[dict]:
        """Spaces and assets whose name, ref or type contains every word of the query."""
        words = [word for word in query.lower().replace("_", " ").split() if word]
        results = []
        for space in self.spaces.values():
            room_type = space["room_type"].replace("_", " ")
            text = f"{space['name']} {space.get('ref') or ''} {room_type} {space['id']}"
            if self.matches(text, words, space["floor_id"], floor_level):
                results.append(
                    {
                        "kind": "space",
                        "id": space["id"],
                        "name": space["name"],
                        "room_type": space["room_type"],
                        "floor": self.floor_name(space["floor_id"]),
                    }
                )
        for asset in self.assets.values():
            text = f"{asset['name']} {asset['type'].replace('_', ' ')} {asset['id']}"
            if self.matches(text, words, asset["floor_id"], floor_level):
                results.append(
                    {
                        "kind": "asset",
                        "id": asset["id"],
                        "name": asset["name"],
                        "type": asset["type"],
                        "in": self.describe_space(asset["space_id"]),
                    }
                )
        if any(result["kind"] == "asset" for result in results):
            self.located_asset_ids = [result["id"] for result in results if result["kind"] == "asset"]
        return results

    def spatial_search(
        self, x_m: float, y_m: float, floor_level: int, radius_m: float = 0,
        kind: str = "all",
    ) -> list[dict]:
        """Find nearby spaces, assets and openings in the building's local metre frame."""
        if self._spatial_index is None:
            self._spatial_index = BuildingSpatialIndex(self.data)
        try:
            return self._spatial_index.search(x_m, y_m, floor_level, radius_m, kind)
        except ValueError as error:
            raise MapError(str(error)) from error

    def matches(self, text: str, words: list[str], floor_id: str, floor_level: int | None) -> bool:
        if floor_level is not None and self.floors[floor_id]["level"] != floor_level:
            return False
        lowered = text.lower()
        return all(word in lowered for word in words)

    def resolve_space(self, reference: str) -> str:
        """Accept a space id, asset id, exact room ref/name or asset name; return a space id."""
        if reference in self.spaces:
            return reference
        if reference in self.assets:
            return self.assets[reference]["space_id"]
        lowered = reference.strip().lower()
        exact_spaces = [
            space["id"]
            for space in self.spaces.values()
            if lowered in ((space.get("ref") or "").lower(), space["name"].lower())
        ]
        if len(exact_spaces) == 1:
            return exact_spaces[0]
        exact_assets = [
            asset["space_id"] for asset in self.assets.values() if asset["name"].lower() == lowered
        ]
        if len(exact_assets) == 1:
            return exact_assets[0]
        candidates = self.search(reference)[:MAX_SEARCH_RESULTS]
        if not candidates:
            raise MapError(f"No place matches '{reference}'. Try search_building with fewer words.")
        raise MapError(
            f"'{reference}' is ambiguous or not exact. Use one of these ids: "
            + "; ".join(f"{item['id']} ({item['name']})" for item in candidates)
        )

    # ---------- routing ----------

    def anchor(self, space_id: str) -> tuple[float, float]:
        point = Polygon(self.spaces[space_id]["polygon"]).representative_point()
        return (point.x, point.y)

    def graph(self, step_free: bool = False, min_width_m: float = 0.0) -> nx.MultiGraph:
        """Kit routing graph without closed elements, steps (if step_free) or openings narrower than min_width_m.

        Connectors have no width: only the doors that give access to them are filtered by width.
        """
        min_width_m = check_number("min_width_m", min_width_m, 0)
        # MultiGraph: a stair and a lift may join the same two spaces; both edges must be kept.
        graph = nx.MultiGraph()
        anchors = {space_id: self.anchor(space_id) for space_id in self.spaces if space_id not in self.closed}
        graph.add_nodes_from(anchors)
        for opening in self.openings.values():
            if (
                opening["id"] in self.closed
                or (step_free and not opening["step_free"])
                or opening["width_m"] < min_width_m
            ):
                continue
            door = DOOR_PREFIX + opening["id"]
            for space_id in opening["space_ids"]:
                if space_id == OUTSIDE:
                    graph.add_edge(OUTSIDE, door, weight=0.0, via=opening["id"])
                elif space_id in anchors:
                    distance = math.dist(anchors[space_id], opening["position"])
                    graph.add_edge(space_id, door, weight=distance, via=opening["id"])
        levels = {floor_id: floor["level"] for floor_id, floor in self.floors.items()}
        for connector in self.connectors.values():
            if connector["id"] in self.closed or (step_free and not connector["step_free"]):
                continue
            stops = sorted(
                zip(connector["floor_ids"], connector["space_ids"], strict=True),
                key=lambda stop: levels[stop[0]],
            )
            for (low_floor, low_space), (high_floor, high_space) in itertools.pairwise(stops):
                if low_space not in anchors or high_space not in anchors:
                    continue
                span = abs(levels[high_floor] - levels[low_floor])
                cost = (
                    LIFT_WAIT_COST_M + LIFT_COST_PER_FLOOR_M * span
                    if connector["kind"] == LIFT
                    else STAIRS_COST_PER_FLOOR_M * span
                )
                graph.add_edge(low_space, high_space, weight=cost, via=connector["id"])
        return graph

    def constraints_text(self, step_free: bool, min_width_m: float, entrance: str | None) -> str:
        """Every requested route constraint, repeated in failure messages."""
        return (
            f"Constraints: step_free={step_free}, min_width_m={min_width_m:g}, "
            f"entrance={entrance or 'any'}, closed={sorted(self.closed)}."
        )

    def entrances_into(self, space_id: str) -> list[dict]:
        """Openings that join the outside directly to this space, sorted by id."""
        return sorted(
            (
                opening for opening in self.openings.values()
                if OUTSIDE in opening["space_ids"] and space_id in opening["space_ids"]
            ),
            key=lambda opening: opening["id"],
        )

    def validate_entrance(
        self, entrance_id: str, space_id: str, step_free: bool = False, min_width_m: float = 0.0
    ) -> dict:
        """The entrance opening, if it opens into the space and satisfies the route constraints.

        Raises MapError with the concrete reason otherwise. Being inside the room does not bypass these
        checks: an entrance that is closed, has steps (when step_free) or is too narrow is unusable.
        """
        min_width_m = check_number("min_width_m", min_width_m, 0)
        opening = self.openings.get(entrance_id)
        if opening is None:
            raise MapError(f"Unknown entrance '{entrance_id}'.")
        if OUTSIDE not in opening["space_ids"]:
            raise MapError(f"{entrance_id} is not an entrance: it does not lead outside.")
        if space_id not in opening["space_ids"]:
            valid = [entrance["id"] for entrance in self.entrances_into(space_id)]
            raise MapError(
                f"Entrance {entrance_id} does not open into {self.describe_space(space_id)}. "
                f"Entrances into it: {valid}."
            )
        if entrance_id in self.closed:
            raise MapError(f"Entrance {entrance_id} is closed.")
        if step_free and not opening["step_free"]:
            raise MapError(f"Entrance {entrance_id} has steps, but a step-free route is required.")
        if opening["width_m"] < min_width_m:
            raise MapError(
                f"Entrance {entrance_id} is {opening['width_m']:g} m wide, narrower than the "
                f"required {min_width_m:g} m."
            )
        return opening

    def floor_segments(self, space_path: list[str]) -> list[dict]:
        """Contiguous runs of the path on one floor; 'outside' is its own segment, revisits stay separate."""
        segments: list[dict] = []
        for space_id in space_path:
            floor_id = self.spaces[space_id]["floor_id"] if space_id in self.spaces else None
            if floor_id is not None and segments and segments[-1]["floor_id"] == floor_id:
                segments[-1]["space_ids"].append(space_id)
            else:
                level = self.floor_level(floor_id) if floor_id is not None else None
                segments.append({"floor_level": level, "floor_id": floor_id, "space_ids": [space_id]})
        return segments

    @staticmethod
    def select_edges(graph: nx.MultiGraph, nodes: list[str]) -> list[tuple[str, float]]:
        """The (element id, weight) of the edge used between each consecutive node pair.

        Parallel edges (two doors, a stair and a lift) are resolved once here: minimum weight, ties by id.
        """
        selected = []
        for previous, current in itertools.pairwise(nodes):
            weight, element = min((edge["weight"], edge["via"]) for edge in graph[previous][current].values())
            selected.append((element, weight))
        return selected

    def compute_route(
        self, start: str, destination: str, step_free: bool = False, via: list[str] | None = None,
        min_width_m: float = 0.0, entrance: str | None = None,
    ) -> RouteResult:
        """Shortest kit route through the stops in order. Pure: changes no state, so it is safe for comparisons.

        entrance, if given, must be a usable entrance into the start space (see validate_entrance).
        """
        min_width_m = check_number("min_width_m", min_width_m, 0)
        stops = [self.resolve_space(reference) for reference in [start, *(via or []), destination]]
        constraints = self.constraints_text(step_free, min_width_m, entrance)
        for stop in stops:
            if stop in self.closed:
                raise MapError(f"{self.describe_space(stop)} is closed. {constraints}")
        if entrance is not None:
            try:
                self.validate_entrance(entrance, stops[0], step_free, min_width_m)
            except MapError as error:
                raise MapError(f"{error} {constraints}") from error
        graph = self.graph(step_free, min_width_m)
        legs: list[dict] = []
        nodes: list[str] = []
        edges: list[tuple[str, float]] = []
        for number, (leg_start, leg_end) in enumerate(itertools.pairwise(stops), start=1):
            try:
                leg_length, leg_nodes = nx.single_source_dijkstra(graph, leg_start, leg_end, weight="weight")
            except nx.NetworkXNoPath as error:
                raise MapError(
                    f"No route from {self.describe_space(leg_start)} to {self.describe_space(leg_end)} "
                    f"(leg {number} of {len(stops) - 1}). {constraints}"
                ) from error
            leg_edges = self.select_edges(graph, leg_nodes)
            legs.append({
                "from_space_id": leg_start, "to_space_id": leg_end, "length_m": leg_length,
                "space_path": [node for node in leg_nodes if not node.startswith(DOOR_PREFIX)],
                "element_path": [element for element, _ in leg_edges],
            })
            nodes += leg_nodes if not nodes else leg_nodes[1:]
            edges += leg_edges
        space_path = [node for node in nodes if not node.startswith(DOOR_PREFIX)]
        return RouteResult(
            start_space_id=stops[0],
            destination_space_id=stops[-1],
            length_m=sum(leg["length_m"] for leg in legs),
            space_path=space_path,
            steps=self.directions(nodes, edges),
            step_free=step_free,
            closed=sorted(self.closed),
            stops=stops,
            node_path=nodes,
            element_path=[element for element, _ in edges],
            legs=legs,
            floor_segments=self.floor_segments(space_path),
            min_width_m=min_width_m,
            entrance=entrance,
        )

    def route(
        self, start: str, destination: str, step_free: bool = False, via: list[str] | None = None,
        min_width_m: float = 0.0, entrance: str | None = None,
    ) -> RouteResult:
        """compute_route, then make the result the active route. Any earlier route is cleared first."""
        self.last_route = None
        self.active_request = None
        result = self.compute_route(start, destination, step_free, via, min_width_m, entrance)
        self.last_route = result
        self.active_request = {
            "start": start, "destination": destination, "step_free": step_free,
            "via": list(via) if via else None, "min_width_m": min_width_m, "entrance": entrance,
        }
        return result

    def recompute_active_route(self) -> RouteResult:
        """Re-run the active request with its original references and constraints after a map change.

        On failure last_route stays None and the request is kept, so a later change can revive it.
        """
        if self.active_request is None:
            raise MapError("There is no active route to recompute.")
        self.last_route = None
        self.last_route = self.compute_route(**self.active_request)
        return self.last_route

    def directions(self, nodes: list[str], edges: list[tuple[str, float]]) -> list[str]:
        """Turn a node path and its selected edges into followable steps: one line per room or floor change."""
        steps = [f"Start in {self.describe_space(nodes[0])}."]
        walked = 0.0
        for current, (element, weight) in zip(nodes[1:], edges, strict=True):
            walked += weight
            if element in self.connectors:
                connector = self.connectors[element]
                verb = "Take" if connector["kind"] == LIFT else "Use"
                steps.append(
                    f"{verb} {connector['name']} ({connector['kind']}) to "
                    f"{self.floor_name(self.spaces[current]['floor_id'])}."
                )
                walked = 0.0
            elif current == OUTSIDE:
                steps.append(f"Walk about {walked:.0f} m and leave the building through the entrance.")
                walked = 0.0
            elif not current.startswith(DOOR_PREFIX):
                opening = self.openings[element]
                passage = {"door": "through the door", "entrance": "outside to the entrance and in"}.get(
                    opening["kind"], "through the opening"
                )
                steps.append(f"Walk about {walked:.0f} m {passage} into {self.spaces[current]['name']}.")
                walked = 0.0
        steps.append(f"You have arrived at {self.describe_space(nodes[-1])}.")
        return steps

    # ---------- inspection ----------

    # ---------- reachability ----------

    # ---------- largest room ----------

    # ---------- floor area totals ----------

    # ---------- straight-line 3D distance ----------

    # ---------- stacked rooms ----------

    # ---------- shared walls ----------

    # ---------- errands ----------

    # ---------- tours ----------

    # ---------- what-if analysis ----------

    # ---------- navigation landmarks ----------

    # ---------- changes ----------

    def find_element(self, reference: str) -> str:
        """Connector, opening or space id/name that can be closed."""
        if reference in self.connectors or reference in self.openings or reference in self.spaces:
            return reference
        lowered = reference.strip().lower()
        named = [
            connector["id"] for connector in self.connectors.values() if connector["name"].lower() == lowered
        ]
        if len(named) == 1:
            return named[0]
        return self.resolve_space(reference)

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        """Undo closures, added openings, the active route and the spatial index if the block raises.

        Wrap an edit together with its save: a failed save then leaves the map exactly as it was.
        """
        closed, openings = set(self.closed), dict(self.openings)
        opening_list, last_route = list(self.data["openings"]), self.last_route
        try:
            yield
        except BaseException:
            self.closed.clear()
            self.closed.update(closed)
            self.openings.clear()
            self.openings.update(openings)
            self.data["openings"][:] = opening_list
            self.last_route = last_route
            self._spatial_index = None
            raise

    def set_closed(self, reference: str, closed: bool) -> str:
        element = self.find_element(reference)
        if closed:
            self.closed.add(element)
        else:
            self.closed.discard(element)
        self.last_route = None
        return element

    def shared_wall(
        self, first_id: str, second_id: str, tolerance_m: float = SHARED_WALL_TOLERANCE_M
    ) -> dict:
        """The part of the first space's outline that lies within tolerance_m of the second space.

        Walls have thickness, so rooms that share a wall have outlines up to about tolerance_m apart.
        Returns total_length_m, runs (contiguous stretches with length_m, start and end, longest first)
        and midpoint: the middle of the longest run, halfway between both polygons (None if no contact).
        Corner-only contact gives only short runs. Both spaces must be on the same floor.
        """
        tolerance_m = check_number("tolerance_m", tolerance_m, 0)
        if first_id == second_id:
            raise MapError("A space does not share a wall with itself.")
        if self.spaces[first_id]["floor_id"] != self.spaces[second_id]["floor_id"]:
            raise MapError("Spaces on different floors cannot share a wall or a door.")
        first, second = self.valid_polygon(first_id), self.valid_polygon(second_id)
        near = first.exterior.intersection(second.buffer(tolerance_m))
        parts = getattr(near, "geoms", [near])
        lines = [part for part in parts if isinstance(part, LineString) and part.length > 0]
        merged = linemerge(lines) if lines else None
        pieces = list(getattr(merged, "geoms", [merged])) if merged is not None else []
        pieces.sort(key=lambda piece: (-piece.length, piece.coords[0]))
        runs = [
            {"length_m": piece.length, "start": list(piece.coords[0]), "end": list(piece.coords[-1])}
            for piece in pieces
        ]
        midpoint = None
        if pieces:
            on_first = pieces[0].interpolate(0.5, normalized=True)
            on_second = nearest_points(second, on_first)[0]
            midpoint = [(on_first.x + on_second.x) / 2, (on_first.y + on_second.y) / 2]
        return {
            "first_space_id": first_id, "second_space_id": second_id, "tolerance_m": tolerance_m,
            "total_length_m": sum(run["length_m"] for run in runs), "runs": runs, "midpoint": midpoint,
        }

    def valid_polygon(self, space_id: str) -> Polygon:
        try:
            polygon = self.space_polygon(space_id)
        except ValueError as error:
            raise MapError(f"The outline of {self.describe_space(space_id)} is malformed: {error}") from error
        if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
            raise MapError(f"The outline of {self.describe_space(space_id)} is not a valid polygon.")
        return polygon

    def add_door(
        self, first: str, second: str, step_free: bool = True, width_m: float = NEW_DOOR_WIDTH_M
    ) -> dict:
        """Add a door at the middle of the wall two neighbouring same-floor spaces share."""
        first_id, second_id = self.resolve_space(first), self.resolve_space(second)
        if first_id == second_id:
            raise MapError("A door must join two different spaces.")
        width_m = check_number("width_m", width_m)
        if width_m <= 0:
            raise MapError(f"width_m must be greater than 0, got {width_m}.")
        wall = self.shared_wall(first_id, second_id)
        longest = wall["runs"][0]["length_m"] if wall["runs"] else 0.0
        if longest < width_m - GEOMETRY_EPSILON:
            raise MapError(
                f"{self.describe_space(first_id)} and {self.describe_space(second_id)} do not share a wall "
                f"long enough for a {width_m:g} m door (longest shared stretch {longest:.2f} m)."
            )
        # Micrometre precision drops floating-point noise such as -4e-16 from the stored coordinates.
        position = [round(value, 6) + 0.0 for value in wall["midpoint"]]
        for existing in self.openings.values():
            if set(existing["space_ids"]) == {first_id, second_id} and (
                math.dist(position, existing["position"]) <= width_m
            ):
                raise MapError(f"{existing['id']} already joins these spaces within {width_m:g} m of that spot.")
        floor_id = self.spaces[first_id]["floor_id"]
        taken = {*self.openings, *self.spaces, *self.assets, *self.connectors, *self.floors}
        number = len(self.openings) + 1
        while f"{floor_id}-O-new{number}" in taken:
            number += 1
        opening = {
            "id": f"{floor_id}-O-new{number}",
            "floor_id": floor_id,
            "space_ids": [first_id, second_id],
            "kind": "door",
            "position": position,
            "width_m": width_m,
            "step_free": step_free,
            "synthetic": True,
        }
        self.openings[opening["id"]] = opening
        self.data["openings"].append(opening)
        self._spatial_index = None
        self.last_route = None
        return opening

    def save(self, path: Path) -> None:
        snapshot = {
            **self.data,
            "navigation_state": {
                **self.data.get("navigation_state", {}), "closed": sorted(self.closed)
            },
        }
        JsonBuildingStore.save(path, snapshot)
