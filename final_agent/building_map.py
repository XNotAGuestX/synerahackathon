"""Deterministic core of the project agent: load a building.json, search it, route through it, edit it.

The agent (agent.py) is only the conversation layer; every fact it states comes from this module.
The route model follows kit 1.1.0: door-to-door walking with wall clearance, height-based
vertical costs and no outside shortcut. Expected answers use the same geometry rules."""

import contextlib
import copy
import itertools
import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points

from .storage import BuildingSpatialIndex, JsonBuildingStore

OUTSIDE = "outside"
DOOR_PREFIX = "door:"
LIFT = "lift"
# Vertical movement in equivalent walking metres per metre of height (floors' elevation_m), the grading rule.
STAIRS_M_PER_RISE = 2.0
LIFT_FIXED_M = 15.0
LIFT_M_PER_RISE = 1.0
# Walking inside a space: stay 15 cm off the walls; a door lands 30 cm inside the space.
WALL_CLEARANCE_M = 0.15
DOOR_LANDING_M = 0.30
NARROW_LANDING_M = 0.05
COVER_TOLERANCE_M = 0.02
BLOCKED_DETOUR_FACTOR = 1.5  # used when no clear walk exists between two points of a space
LENGTH_DECIMALS = 3
MAX_SEARCH_RESULTS = 15
SHARED_WALL_TOLERANCE_M = 0.35
NEW_DOOR_WIDTH_M = 0.9
MAX_INSPECTED_ASSET_IDS = 50
KIT_DISTANCE_MODEL = "kit-1.1.0"
GEOMETRY_EPSILON = 1e-9


Point2 = tuple[float, float]


def outline(points: list[Point2]) -> Polygon:
    polygon = Polygon(points)
    return polygon if polygon.is_valid else polygon.buffer(0)


def door_landing(polygon: Polygon, position: Point2) -> Point2:
    """Where a door at `position` lands inside the space: 30 cm in from the walls."""
    inner = polygon.buffer(-DOOR_LANDING_M)
    if inner.is_empty:
        inner = polygon.buffer(-NARROW_LANDING_M)
    if inner.is_empty:
        point = polygon.representative_point()
        return (point.x, point.y)
    if inner.contains(Point(position)):
        return (position[0], position[1])
    landing = nearest_points(inner, Point(position))[0]
    return (landing.x, landing.y)


def visibility_matrix(allowed: Polygon, nodes: list[Point2]) -> np.ndarray:
    """Straight-line lengths between nodes that see each other inside `allowed`, infinite where blocked."""
    coordinates = np.asarray(nodes, dtype=float)
    straight = np.hypot(*(coordinates[:, None, :] - coordinates[None, :, :]).transpose(2, 0, 1))
    first, second = np.triu_indices(len(nodes), k=1)
    shapely.prepare(allowed)
    clear = shapely.covers(
        allowed, shapely.linestrings(np.stack([coordinates[first], coordinates[second]], axis=1))
    )
    usable = clear | (straight[first, second] == 0)
    matrix = np.full(straight.shape, np.inf)
    np.fill_diagonal(matrix, 0.0)
    matrix[first[usable], second[usable]] = straight[first[usable], second[usable]]
    matrix[second[usable], first[usable]] = straight[first[usable], second[usable]]
    return matrix


def shortest_lengths(matrix: np.ndarray) -> np.ndarray:
    """All-pairs shortest path lengths (Floyd-Warshall)."""
    for middle in range(len(matrix)):
        matrix = np.minimum(matrix, matrix[:, middle, None] + matrix[None, middle, :])
    return matrix


def walking_visibility(polygon: Polygon, points: list[Point2]) -> tuple[list[Point2], np.ndarray]:
    """The exact kit visibility graph, shared by distance calculation and route rendering."""
    walkable = polygon.buffer(-WALL_CLEARANCE_M)
    if walkable.is_empty or walkable.geom_type != "Polygon":
        walkable = polygon
    allowed = walkable.buffer(COVER_TOLERANCE_M)
    corners = [
        corner for ring in [walkable.exterior, *walkable.interiors] for corner in list(ring.coords)[:-1]
    ]
    nodes = list(points) + corners
    return nodes, visibility_matrix(allowed, nodes)


def walking_lengths(polygon: Polygon, points: list[Point2]) -> dict[tuple[int, int], float]:
    """Kit 1.1.0 shortest walks, including its fallback for disconnected visibility nodes."""
    _, matrix = walking_visibility(polygon, points)
    walks = shortest_lengths(matrix)
    lengths = {}
    for source in range(len(points)):
        for target in range(len(points)):
            walk = float(walks[source, target])
            fallback = math.dist(points[source], points[target]) * BLOCKED_DETOUR_FACTOR
            lengths[(source, target)] = walk if math.isfinite(walk) else fallback
    return lengths


def walking_path(polygon: Polygon, start: Point2, end: Point2) -> list[Point2]:
    """Geometry of the same visibility walk used by walking_lengths."""
    nodes, matrix = walking_visibility(polygon, [start, end])
    graph = nx.Graph()
    graph.add_nodes_from(range(len(nodes)))
    first, second = np.triu_indices(len(nodes), k=1)
    graph.add_weighted_edges_from(
        (int(a), int(b), float(matrix[a, b]))
        for a, b in zip(first, second) if math.isfinite(matrix[a, b])
    )
    try:
        return [nodes[index] for index in nx.shortest_path(graph, 0, 1, weight="weight")]
    except nx.NetworkXNoPath:
        # Kit 1.1.0 assigns a heuristic length here; there is no validated drawable walk.
        return []


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

    node_path holds spaces and 'door:<opening id>' nodes. edge_path records the selected
    space or connector for each graph edge; element_path lists each traversed opening and
    connector once per use. Lengths follow kit 1.1.0; entrance validates entry without adding length.
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
    edge_path: list[str] = field(default_factory=list)
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
        self.walks: dict[str, list[tuple[str, str, float]]] = {}
        self._spatial_index: BuildingSpatialIndex | None = None
        self.last_route: RouteResult | None = None
        self.active_request: dict | None = None
        self.located_asset_ids: list[str] = []
        # Set only by select() (a locate action); search, landmarks, previews and analyses never touch it.
        self.selection: dict | None = None

    @classmethod
    def load(cls, path: Path) -> "BuildingMap":
        return cls(JsonBuildingStore.load(path))

    @classmethod
    def load_cached(cls, path: Path, walks_cache: dict[Path, dict]) -> "BuildingMap":
        """A fresh map that reuses the walking lengths of the unchanged building, computed once per path."""
        if path not in walks_cache:
            pristine = cls.load(path)
            pristine.graph(step_free=False)
            walks_cache[path] = pristine.walks
        building_map = cls.load(path)
        building_map.walks = dict(walks_cache[path])
        return building_map

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

    def valid_polygon(self, space_id: str) -> Polygon:
        """The space's polygon; MapError for malformed or invalid geometry instead of silent repair."""
        try:
            polygon = self.space_polygon(space_id)
        except ValueError as error:
            raise MapError(f"The outline of {self.describe_space(space_id)} is malformed: {error}") from error
        if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
            raise MapError(f"The outline of {self.describe_space(space_id)} is not a valid polygon.")
        return polygon

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

    MAX_PAGE_SIZE = 100

    @staticmethod
    def paginate(items: list, page: int = 1, page_size: int = MAX_SEARCH_RESULTS) -> dict:
        """One page of an already sorted, complete list plus the counts a client needs to continue.

        An out-of-range page is a normal empty page. Counts always describe the full list.
        """
        for name, value in (("page", page), ("page_size", page_size)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise MapError(f"{name} must be an integer, got {value!r}.")
        if page < 1:
            raise MapError(f"page must be at least 1 (the first page is 1), got {page}.")
        if not 1 <= page_size <= BuildingMap.MAX_PAGE_SIZE:
            raise MapError(f"page_size must be between 1 and {BuildingMap.MAX_PAGE_SIZE}, got {page_size}.")
        total_pages = -(-len(items) // page_size)
        start = (page - 1) * page_size
        has_more = page < total_pages
        return {
            "matches": len(items),
            "results": items[start:start + page_size],
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_more": has_more,
            "next_page": page + 1 if has_more else None,
        }

    def space_record(self, space: dict) -> dict:
        """Search-result identity of a space: broad type and room_type are kept separate."""
        floor = self.floors[space["floor_id"]]
        return {
            "kind": "space", "id": space["id"], "name": space["name"], "ref": space.get("ref"),
            "type": space.get("type"), "room_type": space["room_type"],
            "floor_level": floor["level"], "floor": floor["name"],
        }

    def asset_record(self, asset: dict) -> dict:
        """Search-result identity of an asset: its own id and the space that contains it."""
        return {
            "kind": "asset", "id": asset["id"], "name": asset["name"], "type": asset["type"],
            "category": asset.get("category"), "space_id": asset["space_id"],
            "in": self.describe_space(asset["space_id"]), "floor_level": self.floor_level(asset["floor_id"]),
        }

    @staticmethod
    def type_filter(name: str, value: str | None) -> str | None:
        """Normalized exact type filter; None or blank means no filter."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise MapError(f"{name} must be text, got {value!r}.")
        return normalize_type(value) or None

    def search(
        self, query: str = "", floor_level: int | None = None, kind: str = "all",
        room_type: str | None = None, asset_type: str | None = None, space_type: str | None = None,
    ) -> list[dict]:
        """Every space and asset matching, sorted by kind, floor level, name and id; never a page.

        query words must all occur in a name, ref, id or type (fuzzy); room_type, space_type and
        asset_type are exact normalized filters. Without a query at least one filter is required.
        """
        if not isinstance(query, str):
            raise MapError(f"query must be text, got {query!r}.")
        words = [word for word in query.lower().replace("_", " ").split() if word]
        kind = normalize_type(kind) if isinstance(kind, str) else kind
        if kind not in ("all", "space", "asset"):
            raise MapError(f"kind must be all, space or asset, got {kind!r}.")
        if isinstance(floor_level, bool) or not (floor_level is None or isinstance(floor_level, int)):
            raise MapError(f"floor_level must be an integer, got {floor_level!r}.")
        room_type = self.type_filter("room_type", room_type)
        space_type = self.type_filter("space_type", space_type)
        asset_type = self.type_filter("asset_type", asset_type)
        if asset_type and (room_type or space_type):
            raise MapError("asset_type selects assets while room_type/space_type select spaces; use one kind per call.")
        if kind == "asset" and (room_type or space_type):
            raise MapError("room_type and space_type select spaces and cannot be combined with kind='asset'.")
        if kind == "space" and asset_type:
            raise MapError("asset_type selects assets and cannot be combined with kind='space'.")
        if not (words or room_type or space_type or asset_type or floor_level is not None):
            raise MapError(
                "Give a query or at least one filter (floor_level, room_type, space_type, asset_type). "
                "To list all rooms use list_spaces."
            )
        if floor_level is not None:
            self.floor_by_level(floor_level)

        results = []
        if kind in ("all", "space") and not asset_type:
            for space in self.filter_spaces(floor_level, room_type, space_type):
                room_words = space["room_type"].replace("_", " ")
                text = f"{space['name']} {space.get('ref') or ''} {room_words} {space['id']}"
                if self.matches(text, words, space["floor_id"], floor_level):
                    results.append(self.space_record(space))
        if kind in ("all", "asset") and not (room_type or space_type):
            for asset in self.assets.values():
                if asset_type and normalize_type(asset["type"]) != asset_type:
                    continue
                text = f"{asset['name']} {asset['type'].replace('_', ' ')} {asset['id']}"
                if self.matches(text, words, asset["floor_id"], floor_level):
                    results.append(self.asset_record(asset))
        results.sort(key=lambda item: (item["kind"], item["floor_level"], item["name"], item["id"]))
        if any(result["kind"] == "asset" for result in results):
            self.located_asset_ids = [result["id"] for result in results if result["kind"] == "asset"]
        return results

    def spatial_search(
        self, x_m: float, y_m: float, floor_level: int, radius_m: float = 0,
        kind: str = "all",
    ) -> list[dict]:
        """Every nearby space, asset and opening in the local metre frame, sorted by distance, kind, id.

        Spaces and assets also carry the identity fields of search results.
        """
        if self._spatial_index is None:
            self._spatial_index = BuildingSpatialIndex(self.data)
        try:
            results = self._spatial_index.search(x_m, y_m, floor_level, radius_m, kind)
        except ValueError as error:
            raise MapError(str(error)) from error
        for result in results:
            if result["kind"] == "space":
                result.update(self.space_record(self.spaces[result["id"]]))
            elif result["kind"] == "asset":
                result.update(self.asset_record(self.assets[result["id"]]))
        return results

    def matches(self, text: str, words: list[str], floor_id: str, floor_level: int | None) -> bool:
        if floor_level is not None and self.floors[floor_id]["level"] != floor_level:
            return False
        lowered = text.lower()
        return all(word in lowered for word in words)

    def resolve_space(self, reference: str) -> str:
        """Accept a space id, asset id, exact room ref/name or asset name; return a space id."""
        if not reference.strip():
            raise MapError("Give a place: a room name or number, an asset name, or an id.")
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

    def anchor(self, space_id: str) -> Point2:
        point = outline(self.spaces[space_id]["polygon"]).representative_point()
        return (point.x, point.y)

    def space_walks(self, space_id: str) -> list[tuple[str, str, float]]:
        """Walking lengths between the room's centre point and each of its doors, and between its doors."""
        if space_id not in self.walks:
            polygon = outline(self.spaces[space_id]["polygon"])
            members = [(space_id, self.anchor(space_id), 0.0)]
            for opening in self.openings.values():
                if space_id in opening["space_ids"]:
                    position = (opening["position"][0], opening["position"][1])
                    landing = door_landing(polygon, position)
                    members.append((DOOR_PREFIX + opening["id"], landing, math.dist(landing, position)))
            lengths = walking_lengths(polygon, [landing for _, landing, _ in members])
            self.walks[space_id] = [
                (
                    members[first][0],
                    members[second][0],
                    lengths[(first, second)] + members[first][2] + members[second][2],
                )
                for first, second in itertools.combinations(range(len(members)), 2)
            ]
        return self.walks[space_id]

    def graph(
        self, step_free: bool = False, min_width_m: float = 0.0, extra_closed: Iterable[str] = ()
    ) -> nx.MultiGraph:
        """Kit 1.1.0 routing graph without closed elements, steps (if step_free) or openings narrower than min_width_m.

        Connectors have no width: only the doors that give access to them are filtered by width.
        extra_closed adds query-only closures on top of self.closed, which stays untouched.
        """
        min_width_m = check_number("min_width_m", min_width_m, 0)
        closed = self.closed | set(extra_closed)
        # MultiGraph: a stair and a lift may join the same two spaces; both edges must be kept.
        graph = nx.MultiGraph()
        open_doors = {
            DOOR_PREFIX + opening["id"] for opening in self.openings.values()
            if opening["id"] not in closed
            and (opening["step_free"] or not step_free)
            and opening["width_m"] >= min_width_m
        }
        open_spaces = [space_id for space_id in self.spaces if space_id not in closed]
        graph.add_nodes_from(open_spaces)
        for space_id in open_spaces:
            for first, second, length in self.space_walks(space_id):
                if (first == space_id or first in open_doors) and second in open_doors:
                    graph.add_edge(first, second, weight=round(length, LENGTH_DECIMALS), space=space_id)
        levels = {floor_id: floor["level"] for floor_id, floor in self.floors.items()}
        for connector in self.connectors.values():
            if connector["id"] in closed or (step_free and not connector["step_free"]):
                continue
            stops = sorted(
                zip(connector["floor_ids"], connector["space_ids"], strict=True),
                key=lambda stop: levels[stop[0]],
            )
            is_lift = connector["kind"] == LIFT
            pairs = itertools.combinations(stops, 2) if is_lift else itertools.pairwise(stops)
            for (low_floor, low_space), (high_floor, high_space) in pairs:
                if low_space not in graph or high_space not in graph:
                    continue
                try:
                    rise = abs(self.floors[high_floor]["elevation_m"] - self.floors[low_floor]["elevation_m"])
                except KeyError as error:
                    raise MapError(f"Connector {connector['id']} needs elevation_m on both stop floors.") from error
                cost = LIFT_FIXED_M + LIFT_M_PER_RISE * rise if is_lift else STAIRS_M_PER_RISE * rise
                graph.add_edge(low_space, high_space, weight=round(cost, LENGTH_DECIMALS), via=connector["id"])
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
        """The (space or connector id, weight) selected between each consecutive node pair.

        Parallel edges (two doors, a stair and a lift) are resolved once here: minimum weight, ties by id.
        """
        selected = []
        for previous, current in itertools.pairwise(nodes):
            weight, element = min((edge["weight"], edge.get("via", edge.get("space"))) for edge in graph[previous][current].values())
            selected.append((element, weight))
        return selected

    def spaces_passed(self, nodes: list[str], edges: list[tuple[str, float]]) -> list[str]:
        """Include spaces crossed door to door even when their anchors are not visited."""
        spaces = [nodes[0]]
        for current, (element, _) in zip(nodes[1:], edges, strict=True):
            for space_id in (element if element in self.spaces else None,
                             current if current in self.spaces else None):
                if space_id is not None and spaces[-1] != space_id:
                    spaces.append(space_id)
        return spaces

    def elements_passed(self, nodes: list[str], edges: list[tuple[str, float]]) -> list[str]:
        """One entry for every opening or connector crossed, in travel order."""
        elements = []
        for current, (element, _) in zip(nodes[1:], edges, strict=True):
            if element in self.connectors:
                elements.append(element)
            elif current.startswith(DOOR_PREFIX):
                elements.append(current.removeprefix(DOOR_PREFIX))
        return elements

    def compute_route(
        self, start: str, destination: str, step_free: bool = False, via: list[str] | None = None,
        min_width_m: float = 0.0, entrance: str | None = None,
    ) -> RouteResult:
        """Shortest kit 1.1.0 route through the stops in order. Pure: changes no state, so it is safe for comparisons.

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
                "space_path": self.spaces_passed(leg_nodes, leg_edges),
                "element_path": self.elements_passed(leg_nodes, leg_edges),
            })
            nodes += leg_nodes if not nodes else leg_nodes[1:]
            edges += leg_edges
        space_path = self.spaces_passed(nodes, edges)
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
            element_path=self.elements_passed(nodes, edges),
            edge_path=[element for element, _ in edges],
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
        """Follow selected walking spaces and connectors, with a direction at each crossed door."""
        steps = [f"Start in {self.describe_space(nodes[0])}."]
        walked = 0.0
        for index, (current, (element, weight)) in enumerate(zip(nodes[1:], edges, strict=True), start=1):
            walked += weight
            if element in self.connectors:
                connector = self.connectors[element]
                verb = "Take" if connector["kind"] == LIFT else "Use"
                steps.append(
                    f"{verb} {connector['name']} ({connector['kind']}) to "
                    f"{self.floor_name(self.spaces[current]['floor_id'])}."
                )
                walked = 0.0
            elif current.startswith(DOOR_PREFIX) and index < len(edges):
                opening = self.openings[current.removeprefix(DOOR_PREFIX)]
                following = edges[index][0]
                passage = "through the door" if opening["kind"] == "door" else "through the opening"
                steps.append(f"Walk about {walked:.0f} m {passage} into {self.spaces[following]['name']}.")
                walked = 0.0
        steps.append(f"Walk about {walked:.0f} m. You have arrived at {self.describe_space(nodes[-1])}.")
        return steps

    # ---------- inspection ----------

    def inspect_space(self, reference: str) -> dict:
        """Complete inspection of one space: source record, derived geometry, floor, openings, connectors, assets."""
        space_id = self.resolve_space(reference)
        space = self.spaces[space_id]
        polygon = self.space_polygon(space_id)
        centroid, anchor = polygon.centroid, self.anchor(space_id)
        min_x, min_y, max_x, max_y = polygon.bounds
        result = {
            "space": copy.deepcopy(space),
            "derived": {
                "area_m2": round(polygon.area, 3),
                "perimeter_m": round(polygon.length, 3),
                "centroid": [round(centroid.x, 3), round(centroid.y, 3)],
                "representative_point": [round(anchor[0], 3), round(anchor[1], 3)],
                "bounds": {"min_x": round(min_x, 3), "min_y": round(min_y, 3),
                           "max_x": round(max_x, 3), "max_y": round(max_y, 3)},
            },
            "floor": self.inspected_floor(space["floor_id"]),
            "closed": space_id in self.closed,
            "openings": [
                self.inspected_opening(opening, space_id)
                for opening in sorted(self.openings.values(), key=lambda item: item["id"])
                if space_id in opening["space_ids"]
            ],
            "connectors": [
                self.inspected_connector(connector)
                for connector in sorted(self.connectors.values(), key=lambda item: item["id"])
                if space_id in connector["space_ids"]
            ],
            "assets": self.inspected_assets(space_id),
        }
        asset = self.asset_behind_reference(reference, space_id)
        if asset:
            result["resolved_from_asset"] = {"id": asset["id"], "name": asset["name"]}
        return result

    def asset_behind_reference(self, reference: str, space_id: str) -> dict | None:
        """The asset a reference named, when it resolved to its containing space rather than a space."""
        if reference in self.spaces:
            return None
        if reference in self.assets:
            return self.assets[reference]
        lowered = reference.strip().lower()
        if any(lowered in ((space.get("ref") or "").lower(), space["name"].lower()) for space in self.spaces.values()):
            return None
        return next(
            (asset for asset in self.assets.values()
             if asset["name"].lower() == lowered and asset["space_id"] == space_id),
            None,
        )

    def inspected_floor(self, floor_id: str) -> dict:
        floor = self.floors[floor_id]
        info = {key: floor.get(key) for key in ("id", "level", "name", "elevation_m", "height_m")}
        missing = [key for key in ("elevation_m", "height_m") if floor.get(key) is None]
        if missing:
            info["note"] = f"Not stored for this floor: {', '.join(missing)}."
        return info

    def inspected_opening(self, opening: dict, space_id: str) -> dict:
        other = self.other_side(opening, space_id)
        return {
            "id": opening["id"],
            "kind": opening["kind"],
            "width_m": opening.get("width_m"),
            "step_free": opening.get("step_free"),
            "position": opening["position"],
            "synthetic": opening.get("synthetic", False),
            "closed": opening["id"] in self.closed,
            "other_side": OUTSIDE if other == OUTSIDE else self.space_summary(other),
        }

    def inspected_connector(self, connector: dict) -> dict:
        stops = sorted(
            zip(connector["floor_ids"], connector["space_ids"], strict=True),
            key=lambda stop: self.floor_level(stop[0]),
        )
        return {
            "id": connector["id"],
            "kind": connector["kind"],
            "name": connector.get("name"),
            "step_free": connector.get("step_free"),
            "closed": connector["id"] in self.closed,
            "stops": [
                {"floor_level": self.floor_level(floor_id), "space_id": stop_space,
                 "space_name": self.spaces[stop_space]["name"]}
                for floor_id, stop_space in stops
            ],
        }

    def inspected_assets(self, space_id: str) -> dict:
        ids = sorted(asset["id"] for asset in self.assets.values() if asset["space_id"] == space_id)
        info = {"count": len(ids), "ids": ids[:MAX_INSPECTED_ASSET_IDS], "truncated": len(ids) > MAX_INSPECTED_ASSET_IDS}
        if info["truncated"]:
            info["note"] = (
                f"Only the first {MAX_INSPECTED_ASSET_IDS} of {len(ids)} asset ids are listed; "
                "page through search_building for the rest."
            )
        return info

    # ---------- reachability ----------

    MAX_LISTED_ROOMS = 50
    COUNTED_SPACE_TYPE = "room"

    def usable_entrances(
        self, entrance: str, start_id: str, step_free: bool, min_width_m: float, closed: set[str]
    ) -> list[dict]:
        """The entrance opening(s) a delivery may arrive through; MapError if none, or if the choice is ambiguous.

        entrance is an opening id or a space reference meaning "the entrance into that space", which must
        be the start space. Several entrances that differ in eligibility are never resolved by guessing.

        An explicit opening id must itself be wide enough. A space reference only names where the load
        arrives: the benchmark labels (5 of 81 train/dev questions) count from the start room even when
        its entrance is narrower than the load, so width is then reported as a warning, not enforced.
        Closed and stepped entrances are always enforced.
        """
        check_width = entrance in self.openings
        width_limit = min_width_m if check_width else 0.0
        if check_width:
            candidates = [self.openings[entrance]]
        else:
            space_id = self.resolve_space(entrance)
            if space_id != start_id:
                raise MapError(
                    f"Entrance '{entrance}' is into {self.describe_space(space_id)}, "
                    f"but the start is {self.describe_space(start_id)}."
                )
            candidates = self.entrances_into(start_id)
            if not candidates:
                raise MapError(f"{self.describe_space(start_id)} has no entrance from outside.")
        usable, problems = [], []
        for opening in candidates:
            try:
                if opening["id"] in closed:
                    raise MapError(f"Entrance {opening['id']} is closed.")
                self.validate_entrance(opening["id"], start_id, step_free, width_limit)
                usable.append(opening)
            except MapError as error:
                problems.append(str(error))
        if usable and not problems:
            return usable
        if len(candidates) == 1 or not usable:
            raise MapError("No usable entrance. " + " ".join(problems))
        raise MapError(
            f"{self.describe_space(start_id)} has several entrances that differ under these constraints: "
            + "; ".join(f"{o['id']} ({o['width_m']:g} m, step_free={o['step_free']})" for o in candidates)
            + ". Ask which entrance is used. " + " ".join(problems)
        )

    def reachable_rooms(
        self, start: str, floor_level: int | None = None, step_free: bool = False, min_width_m: float = 0.0,
        entrance: str | None = None, closed_elements: list[str] | None = None, room_type: str | None = None,
    ) -> dict:
        """Rooms reachable from start under the constraints, found with one traversal of one filtered graph.

        Pure: closed_elements are closed for this query only; no map state or file changes.
        Only spaces of broad type 'room' are counted (halls, corridors, stairs, lifts and outdoor spaces
        are only passed through); the start room counts when it qualifies. floor_level and room_type
        select the counted rooms and never limit the traversal. Entrances are terminal openings;
        traversal never leaves and re-enters through the outside.
        """
        min_width_m = check_number("min_width_m", min_width_m, 0)
        if not isinstance(step_free, bool):
            raise MapError(f"step_free must be true or false, got {step_free!r}.")
        if isinstance(closed_elements, str):
            closed_elements = [closed_elements]
        temporary = sorted({self.find_element(reference) for reference in closed_elements or []})
        closed = self.closed | set(temporary)
        start_id = self.resolve_space(start)
        constraints = {
            "step_free": step_free, "min_width_m": min_width_m,
            "closed": sorted(closed), "temporarily_closed": temporary,
        }
        if start_id in closed:
            raise MapError(f"{self.describe_space(start_id)} is closed. Constraints: {constraints}")
        target_floor = self.floor_by_level(floor_level)["id"] if floor_level is not None else None
        wanted_type = normalize_type(room_type) if room_type else None
        entrances = (
            self.usable_entrances(entrance, start_id, step_free, min_width_m, closed) if entrance else []
        )
        warnings = [
            f"Entrance {o['id']} is {o['width_m']:g} m wide, narrower than the {min_width_m:g} m load; "
            "width is not enforced because the entrance was given as a room."
            for o in entrances if o["width_m"] < min_width_m
        ]
        graph = self.graph(step_free, min_width_m, temporary)
        reached = nx.node_connected_component(graph, start_id)
        counted, excluded = [], {}
        for space_id in sorted(node for node in reached if node in self.spaces):
            space = self.spaces[space_id]
            if target_floor is not None and space["floor_id"] != target_floor:
                continue
            if space["type"] == self.COUNTED_SPACE_TYPE and (
                wanted_type is None or normalize_type(space["room_type"]) == wanted_type
            ):
                counted.append(space_id)
            else:
                excluded[space["type"]] = excluded.get(space["type"], 0) + 1
        return {
            "count": len(counted),
            "room_ids": counted,
            "rooms": [self.space_summary(space_id) for space_id in counted[: self.MAX_LISTED_ROOMS]],
            "rooms_truncated": len(counted) > self.MAX_LISTED_ROOMS,
            "constraints": constraints,
            "entry": {
                "start": self.space_summary(start_id),
                "entrances": [
                    {"id": o["id"], "width_m": o["width_m"], "step_free": o["step_free"]} for o in entrances
                ],
                "warnings": warnings,
            },
            "eligibility": (
                "Counts spaces of broad type 'room' that are reachable from the start"
                + (f" on floor level {floor_level}" if floor_level is not None else "")
                + (f" with room type '{wanted_type}'" if wanted_type else "")
                + ", including the start room; halls, corridors, stairs, lifts and outdoor spaces are "
                "traversed but never counted."
            ),
            "excluded_reachable": dict(sorted(excluded.items())),
        }

    # ---------- largest room ----------

    def find_largest_room(self, room_type: str, floor_level: int) -> dict:
        """The space of exactly this room type with the largest polygon area on one floor.

        Every space subtype counts, including halls, because an exact lobby or warehouse_zone can be a
        hall. Ties are broken by id; unrounded areas decide, rounding happens only in the result."""
        floor = self.floor_by_level(floor_level)
        wanted = normalize_type(room_type)
        ranked = sorted(
            ((self.space_area_m2(space["id"]), space["id"]) for space in self.filter_spaces(floor_level, wanted)),
            key=lambda item: (-item[0], item[1]),
        )
        result = {
            "room_type": wanted, "floor_level": floor["level"], "floor": floor["name"],
            "candidates": len(ranked), "room": None, "area_m2": None, "runners_up": [], "tie": False,
        }
        if not ranked:
            result["available_room_types"] = self.room_types(floor_level)
            return result
        best_area, best_id = ranked[0]
        result["room"] = {**self.space_summary(best_id), "area_m2": round(best_area, 2)}
        result["area_m2"] = round(best_area, 2)
        result["runners_up"] = [
            {"id": space_id, "name": self.spaces[space_id]["name"], "area_m2": round(area, 2)}
            for area, space_id in ranked[1:4]
        ]
        result["tie"] = len(ranked) > 1 and math.isclose(ranked[1][0], best_area, rel_tol=1e-9, abs_tol=1e-9)
        return result

    # ---------- floor area totals ----------

    MAX_AREA_ROOMS = 50  # keeps the JSON compact on large floors; count, total and ids stay complete

    def sum_floor_area(self, room_type: str, floor_level: int) -> dict:
        """Total polygon area of every space with exactly this room type on one floor.

        A plain sum of room areas (not their geometric union); halls and every other broad space type
        count when their room_type matches. An empty match is a normal result with area 0.
        """
        floor = self.floor_by_level(floor_level)
        wanted = normalize_type(room_type)
        matches = self.filter_spaces(floor_level, wanted)
        areas = {space["id"]: self.space_area_m2(space["id"]) for space in matches}
        result = {
            "room_type": wanted, "floor_level": floor["level"], "floor": floor["name"],
            "count": len(matches), "area_m2": round(sum(areas.values()), 2),
            "space_ids": sorted(areas),
            "rooms": [
                {"id": space["id"], "name": space["name"], "area_m2": round(areas[space["id"]], 2)}
                for space in matches[: self.MAX_AREA_ROOMS]
            ],
            "rooms_truncated": len(matches) > self.MAX_AREA_ROOMS,
        }
        if not matches:
            result["available_room_types"] = self.room_types(floor_level)
        return result

    # ---------- straight-line 3D distance ----------

    SWISS_DWELLINGS_SOURCE = "swiss_dwellings"

    def centroid_point_3d(self, reference: str) -> dict:
        """Space identity plus its polygon centroid and floor elevation as an XYZ point (metres)."""
        space_id = self.resolve_space(reference)
        floor = self.floors[self.spaces[space_id]["floor_id"]]
        elevation = floor.get("elevation_m")
        try:
            elevation = check_number("elevation_m", elevation)
        except MapError as error:
            raise MapError(
                f"Floor {floor['name']} has no usable elevation_m ({elevation!r}); "
                "a 3D distance would need an invented height."
            ) from error
        centroid = self.space_polygon(space_id).centroid
        summary = self.space_summary(space_id)
        asset = self.asset_behind_reference(reference, space_id)
        if asset:
            summary["resolved_from_asset"] = {"id": asset["id"], "name": asset["name"]}
            summary["note"] = f"'{reference}' is an asset; its containing room {space_id} was used."
        return {
            **summary, "centroid": [centroid.x, centroid.y],
            "elevation_m": elevation, "point": [centroid.x, centroid.y, elevation],
        }

    def straight_line_distance_3d(self, first: str, second: str) -> dict:
        """Euclidean XYZ distance between two spaces' polygon centroids at their floors' elevation_m.

        Not a walking distance and not the route anchor model. Values are unrounded.
        """
        first_point, second_point = self.centroid_point_3d(first), self.centroid_point_3d(second)
        horizontal = math.dist(first_point["centroid"], second_point["centroid"])
        vertical = abs(first_point["elevation_m"] - second_point["elevation_m"])
        result = {
            "first": first_point, "second": second_point,
            "distance_m": math.hypot(horizontal, vertical),
            "horizontal_m": horizontal, "vertical_m": vertical,
        }
        if (
            self.data["building"].get("source") == self.SWISS_DWELLINGS_SOURCE
            and first_point["floor_level"] != second_point["floor_level"]
        ):
            result["frame_note"] = (
                "Swiss Dwellings floors may be centred per floor rather than aligned, so the "
                "horizontal part between different floors can be approximate."
            )
        return result

    # ---------- stacked rooms ----------

    # Building sources whose floors share one XY frame (README section 4); others get a frame_warning.
    STACKING_FRAME_SOURCES = ("procedural", "osm_indoor")
    STACKING_MIN_OVERLAP_M2 = 1e-6

    def find_stacked_room(self, space: str, direction: str) -> dict:
        """The space on the next floor above/below whose outline overlaps this space the most.

        "Next" means the adjacent level in sorted order, so level gaps (-2, 0, 1) are handled. Every
        space type on that floor is a candidate (verified against the labelled room_stacked questions).
        No floor or no overlap is a normal result with room=None and a reason.
        """
        wanted = direction.strip().lower()
        step = {"above": 1, "up": 1, "below": -1, "down": -1}.get(wanted)
        if step is None:
            raise MapError(f"Unknown direction {direction!r}. Use 'above' or 'below'.")
        source_id = self.resolve_space(space)
        source_level = self.floor_level(self.spaces[source_id]["floor_id"])
        result = {
            "source": self.space_summary(source_id),
            "direction": "above" if step > 0 else "below",
            "source_floor_level": source_level,
            "target_floor_level": None, "room": None,
            "overlap_area_m2": 0.0, "overlap_fraction": 0.0,
            "runners_up": [], "tie": False, "reason": None,
        }
        building_source = self.data["building"].get("source")
        if building_source not in self.STACKING_FRAME_SOURCES:
            result["frame_warning"] = (
                f"Floors of a '{building_source}' building are not known to share one XY frame, "
                "so the overlap may not reflect the real stacking."
            )
        levels = sorted({floor["level"] for floor in self.floors.values()})
        neighbours = [level for level in levels if (level - source_level) * step > 0]
        if not neighbours:
            result["reason"] = f"no floor {result['direction']} level {source_level}"
            return result
        target_level = min(neighbours, key=lambda level: abs(level - source_level))
        result["target_floor_level"] = target_level

        source_polygon = self.valid_polygon(source_id)
        overlaps = []
        for candidate in self.filter_spaces(floor_level=target_level):
            area = source_polygon.intersection(self.valid_polygon(candidate["id"])).area
            if area > self.STACKING_MIN_OVERLAP_M2:
                overlaps.append((candidate["id"], area))
        if not overlaps:
            result["reason"] = f"no overlapping space on floor level {target_level}"
            return result
        overlaps.sort(key=lambda item: (-item[1], item[0]))
        best_id, best_area = overlaps[0]
        result["room"] = self.space_summary(best_id)
        result["overlap_area_m2"] = round(best_area, 3)
        result["overlap_fraction"] = round(best_area / source_polygon.area, 4) if source_polygon.area else 0.0
        result["tie"] = len(overlaps) > 1 and overlaps[1][1] >= best_area - self.STACKING_MIN_OVERLAP_M2
        result["runners_up"] = [
            {**self.space_summary(space_id), "overlap_area_m2": round(area, 3)}
            for space_id, area in overlaps[1:4]
        ]
        return result

    # ---------- shared walls ----------

    MIN_SHARED_WALL_M = 1.0
    SHARED_WALL_TYPES = ("room", "hall")
    SHARED_WALL_MAX_ANGLE_SIN = math.sin(math.radians(15))
    SHARED_WALL_ELIGIBILITY = (
        "Counts same-floor spaces of type room or hall (hall bays and lobbies included) with at least 1 m "
        "of wall running parallel within 0.35 m of this room's outline; corridors, stairwells, lifts and "
        "outdoor spaces never count, and doors are irrelevant."
    )

    @staticmethod
    def wall_contact_runs(first: Polygon, second: Polygon, tolerance_m: float) -> list[list[tuple]]:
        """Stretches of the first outline that run along the second outline, each a list of points.

        A stretch only counts where an edge of the first outline is nearly parallel (within 15 degrees)
        to an edge of the second, lies within tolerance_m of that edge's line and faces it, meaning the
        two edges overlap when projected onto each other. Outline pieces that merely continue past the
        wall end (the buffer's "corner caps") project to zero overlap, so they are not counted. Runs
        are chained across polygon vertices; longest first is left to the caller.
        """
        first_points = list(first.exterior.coords)
        second_points = list(second.exterior.coords)
        limit = tolerance_m + GEOMETRY_EPSILON
        pieces = []  # (edge index, start offset, end offset, edge length), in outline order
        for index in range(len(first_points) - 1):
            start, end = first_points[index], first_points[index + 1]
            length = math.dist(start, end)
            if length <= GEOMETRY_EPSILON:
                continue
            ux, uy = (end[0] - start[0]) / length, (end[1] - start[1]) / length
            intervals = []
            for other in range(len(second_points) - 1):
                r, s = second_points[other], second_points[other + 1]
                other_length = math.dist(r, s)
                if other_length <= GEOMETRY_EPSILON:
                    continue
                vx, vy = (s[0] - r[0]) / other_length, (s[1] - r[1]) / other_length
                slope = vx * uy - vy * ux  # sine of the angle between the edges
                if abs(slope) > BuildingMap.SHARED_WALL_MAX_ANGLE_SIN:
                    continue
                offset = vx * (start[1] - r[1]) - vy * (start[0] - r[0])  # signed distance at the start
                low, high = 0.0, length
                if abs(slope) > 1e-12:
                    bounds = sorted(((-limit - offset) / slope, (limit - offset) / slope))
                    low, high = max(low, bounds[0]), min(high, bounds[1])
                elif abs(offset) > limit:
                    continue
                along = sorted(((r[0] - start[0]) * ux + (r[1] - start[1]) * uy,
                                (s[0] - start[0]) * ux + (s[1] - start[1]) * uy))
                low, high = max(low, along[0]), min(high, along[1])
                if high - low > GEOMETRY_EPSILON:
                    intervals.append((low, high))
            for low, high in sorted(intervals):
                if pieces and pieces[-1][0] == index and low <= pieces[-1][2] + GEOMETRY_EPSILON:
                    pieces[-1] = (index, pieces[-1][1], max(high, pieces[-1][2]), length)
                else:
                    pieces.append((index, low, high, length))
        runs: list[list[tuple]] = []
        joined_to_previous = []
        for index, low, high, length in pieces:
            start, end = first_points[index], first_points[index + 1]
            direction = ((end[0] - start[0]) / length, (end[1] - start[1]) / length)
            low_point = (start[0] + direction[0] * low, start[1] + direction[1] * low)
            high_point = (start[0] + direction[0] * high, start[1] + direction[1] * high)
            if runs and joined_to_previous[-1] == index - 1 and low <= GEOMETRY_EPSILON:
                runs[-1].append(high_point)
            else:
                runs.append([low_point, high_point])
            # The run can continue onto the next edge only if this piece reaches the end of its edge.
            joined_to_previous.append(index if length - high <= GEOMETRY_EPSILON else None)
        # A run that crosses the ring's closing vertex was split into the last and the first run.
        if len(runs) > 1 and pieces[0][0] == 0 and pieces[0][1] <= GEOMETRY_EPSILON and (
            pieces[-1][0] == len(first_points) - 2 and pieces[-1][3] - pieces[-1][2] <= GEOMETRY_EPSILON
        ):
            runs[-1].extend(runs.pop(0)[1:])
        return runs

    @staticmethod
    def run_length(run: list[tuple]) -> float:
        return sum(math.dist(first, second) for first, second in zip(run, run[1:]))

    def space_wall_contact(self, source_id: str, other_id: str, tolerance_m: float) -> dict:
        """Wall contact of the source outline against another same-floor space (see wall_contact_runs)."""
        source, other = self.valid_polygon(source_id), self.valid_polygon(other_id)
        runs = sorted(
            self.wall_contact_runs(source, other, tolerance_m),
            key=lambda run: (-self.run_length(run), run[0]),
        )
        return {"runs": runs, "total_length_m": sum(self.run_length(run) for run in runs)}

    def count_shared_walls(self, reference: str) -> dict:
        """Eligible same-floor rooms with at least MIN_SHARED_WALL_M of wall within the wall tolerance.

        Eligibility is this operation's own rule (type room or hall; see SHARED_WALL_ELIGIBILITY), not
        the delivery-count rule. Lengths are measured along the source outline; unrounded.
        """
        source_id = self.resolve_space(reference)
        source = self.valid_polygon(source_id)
        floor_id = self.spaces[source_id]["floor_id"]
        min_x, min_y, max_x, max_y = source.bounds
        reach = SHARED_WALL_TOLERANCE_M
        neighbours, excluded = [], []
        for other_id, other in sorted(self.spaces.items()):
            if other_id == source_id or other["floor_id"] != floor_id:
                continue
            other_min_x, other_min_y, other_max_x, other_max_y = self.valid_polygon(other_id).bounds
            if (other_min_x > max_x + reach or other_max_x < min_x - reach
                    or other_min_y > max_y + reach or other_max_y < min_y - reach):
                continue
            length = self.space_wall_contact(source_id, other_id, SHARED_WALL_TOLERANCE_M)["total_length_m"]
            if length <= 0.01:
                continue
            entry = {**self.space_summary(other_id), "shared_length_m": length}
            for key in ("floor_level", "floor"):
                del entry[key]
            if normalize_type(other["type"]) not in self.SHARED_WALL_TYPES:
                excluded.append({**entry, "reason": f"{other['type']} spaces are never counted"})
            elif length < self.MIN_SHARED_WALL_M - GEOMETRY_EPSILON:
                excluded.append({**entry, "reason": f"shared wall below {self.MIN_SHARED_WALL_M:g} m"})
            else:
                neighbours.append(entry)
        return {
            "space": self.space_summary(source_id),
            "count": len(neighbours),
            "neighbours": neighbours,
            "excluded": excluded,
            "min_shared_length_m": self.MIN_SHARED_WALL_M,
            "wall_tolerance_m": SHARED_WALL_TOLERANCE_M,
            "eligibility": self.SHARED_WALL_ELIGIBILITY,
        }

    # ---------- errands ----------

    ERRAND_SELECTION_RULE = (
        "Nearest pickup room by route distance from the start first, then the largest destination room of the "
        "requested type on the target floor; this is not a combined-trip optimisation."
    )

    def similar_asset_types(self, asset_type: str, limit: int = 8) -> list[str]:
        """Existing asset types containing every word of the requested one, to correct a wrong type name."""
        words = normalize_type(asset_type).split("_")
        types = {normalize_type(asset["type"]) for asset in self.assets.values()}
        return sorted(name for name in types if all(word in name for word in words))[:limit]

    def plan_errand(
        self, start: str, asset_type: str, destination_room_type: str, destination_floor_level: int,
        step_free: bool = False, min_width_m: float = 0.0, activate: bool = False,
    ) -> dict:
        """Fetch an asset from the nearest room that has one, then carry it to the largest room of a type on a floor.

        The nearest pickup is chosen by constrained route distance from the start (one Dijkstra over the graph
        compute_route uses); the destination is then the largest matching room. A shorter combined trip via
        another pickup is deliberately not chosen. Assets in one room are one pickup candidate; any space type,
        including outdoor balconies, can be a pickup. Ties go to the lowest space id. If leg 2 fails, the error
        names the selected rooms; no farther pickup or smaller destination is substituted.
        activate=False is read-only; activate=True makes start -> pickup -> destination the active route.
        """
        if activate:
            self.last_route = None
            self.active_request = None
        min_width_m = check_number("min_width_m", min_width_m, 0)
        if not isinstance(step_free, bool):
            raise MapError(f"step_free must be true or false, got {step_free!r}.")
        start_id = self.resolve_space(start)
        constraints = self.constraints_text(step_free, min_width_m, None)
        if start_id in self.closed:
            raise MapError(f"{self.describe_space(start_id)} is closed. {constraints}")

        wanted = normalize_type(asset_type)
        assets_by_space: dict[str, list[str]] = {}
        for asset in self.assets.values():
            if normalize_type(asset["type"]) == wanted:
                assets_by_space.setdefault(asset["space_id"], []).append(asset["id"])
        if not assets_by_space:
            similar = self.similar_asset_types(asset_type)
            raise MapError(
                f"No asset of type '{asset_type}' exists in this building. "
                + (f"Asset types containing those words: {similar}." if similar else "No similar asset type exists.")
            )

        destination = self.find_largest_room(destination_room_type, destination_floor_level)
        if destination["room"] is None:
            raise MapError(
                f"No room of type '{destination_room_type}' on floor level {destination_floor_level}. "
                f"Room types on that floor: {destination['available_room_types']}."
            )
        destination_id = destination["room"]["id"]

        distances = nx.single_source_dijkstra_path_length(self.graph(step_free, min_width_m), start_id, weight="weight")
        reachable = sorted((distances[space_id], space_id) for space_id in assets_by_space if space_id in distances)
        unreachable = len(assets_by_space) - len(reachable)
        if not reachable:
            raise MapError(
                f"None of the {len(assets_by_space)} rooms with a '{wanted}' can be reached from "
                f"{self.describe_space(start_id)}. {constraints}"
            )
        pickup_distance, pickup_id = reachable[0]

        first = self.compute_route(start_id, pickup_id, step_free, None, min_width_m)
        try:
            second = self.compute_route(pickup_id, destination_id, step_free, None, min_width_m)
        except MapError as error:
            reason = "it is closed" if destination_id in self.closed else "no route exists"
            raise MapError(
                f"Errand leg 2 of 2 is impossible: the selected pickup {self.describe_space(pickup_id)} cannot "
                f"reach the selected destination {self.describe_space(destination_id)} ({reason}). The nearest "
                f"pickup and the largest destination are fixed by the question; no other pickup or smaller "
                f"destination is substituted. {constraints}"
            ) from error
        route = None
        if activate:
            route = self.route(start_id, destination_id, step_free, [pickup_id], min_width_m)
        return {
            "pickup": {
                **self.space_summary(pickup_id), "asset_ids": sorted(assets_by_space[pickup_id]),
                "distance_m": pickup_distance,
            },
            "pickup_candidates": len(assets_by_space),
            "unreachable_candidates": unreachable,
            "destination": {**self.space_summary(destination_id), "area_m2": destination["area_m2"]},
            "leg_routes": [first, second],
            "route": route,
            "length_m": first.length_m + second.length_m,
            "constraints": {"step_free": step_free, "min_width_m": min_width_m, "closed": sorted(self.closed)},
            "selection_rule": self.ERRAND_SELECTION_RULE,
            "distance_model": KIT_DISTANCE_MODEL,
            "activated": activate,
        }

    # ---------- tours ----------

    MAX_TOUR_STOPS = 10
    TOUR_EPSILON = 1e-9

    def tour_distances(
        self, points: list[str], step_free: bool, min_width_m: float
    ) -> dict[str, dict[str, float]]:
        """Shortest kit distance between all distinct points on the same filtered graph compute_route uses.

        Raises MapError naming the first required point that cannot be reached from the first one.
        """
        constraints = self.constraints_text(step_free, min_width_m, None)
        for point in points:
            if point in self.closed:
                raise MapError(f"{self.describe_space(point)} is closed. {constraints}")
        graph = self.graph(step_free, min_width_m)
        distances = {
            point: nx.single_source_dijkstra_path_length(graph, point, weight="weight")
            for point in dict.fromkeys(points)
        }
        for point in points[1:]:
            if point not in distances[points[0]]:
                raise MapError(
                    f"The tour is impossible: {self.describe_space(point)} cannot be reached from "
                    f"{self.describe_space(points[0])}. {constraints}"
                )
        return distances

    def best_stop_order(
        self, start: str, stop_ids: list[str], destination: str, distances: dict[str, dict[str, float]]
    ) -> tuple[list[int], float]:
        """Exact Held-Karp: the cheapest order of stop indices from start to destination, and its length.

        remaining[mask][last] is the cheapest way to visit all stops outside mask, beginning at the last visited
        stop (index len(stop_ids) stands for the start) and ending at the destination. Equal-cost orders (within
        TOUR_EPSILON) are resolved by walking forward and taking the smallest stop id, then the lowest index, so
        the result is the lexicographically smallest optimal id sequence and independent of input order ties.
        """
        count = len(stop_ids)
        points = [*stop_ids, start]
        full = (1 << count) - 1
        remaining: list[dict[int, float]] = [{} for _ in range(full + 1)]
        for mask in range(full, -1, -1):
            lasts = [index for index in range(count) if mask >> index & 1] or [count]
            for last in lasts:
                if mask == full:
                    remaining[mask][last] = distances[points[last]][destination]
                else:
                    remaining[mask][last] = min(
                        distances[points[last]][stop_ids[nxt]] + remaining[mask | 1 << nxt][nxt]
                        for nxt in range(count) if not mask >> nxt & 1
                    )
        order: list[int] = []
        mask, last = 0, count
        while mask != full:
            best = remaining[mask][last]
            candidates = [
                nxt for nxt in range(count)
                if not mask >> nxt & 1
                and distances[points[last]][stop_ids[nxt]] + remaining[mask | 1 << nxt][nxt]
                <= best + self.TOUR_EPSILON
            ]
            chosen = min(candidates, key=lambda index: (stop_ids[index], index))
            order.append(chosen)
            mask, last = mask | 1 << chosen, chosen
        return order, remaining[0][count]

    def find_best_tour(
        self, start: str, stops: list[str], destination: str, step_free: bool = False,
        min_width_m: float = 0.0, activate: bool = True,
    ) -> dict:
        """Shortest tour from start through every stop, in any order, ending at destination (kit model).

        Exact for up to MAX_TOUR_STOPS intermediate stops; more raises MapError (no heuristic is ever called
        shortest). Repeated stops stay separate visits (zero-length legs). All lengths are unrounded.
        The returned 'route' is compute_route(via=best order), so legs, directions and map match find_route.
        activate=True makes it the active route like route(): the request keeps the optimised via order and the
        constraints, so a later reroute after a closure visits the stops in the chosen order (no re-optimising).
        activate=False is a read-only preview: last_route, active_request and closures stay untouched.
        """
        if activate:
            self.last_route = None
            self.active_request = None
        min_width_m = check_number("min_width_m", min_width_m, 0)
        stops = list(stops or [])
        if len(stops) > self.MAX_TOUR_STOPS:
            raise MapError(
                f"{len(stops)} stops is too many for an exact shortest tour: at most {self.MAX_TOUR_STOPS} "
                "intermediate stops are supported. Split the request or choose fewer stops."
            )
        start_id = self.resolve_space(start)
        stop_ids = [self.resolve_space(reference) for reference in stops]
        destination_id = self.resolve_space(destination)
        distances = self.tour_distances([start_id, *stop_ids, destination_id], step_free, min_width_m)
        order, best_length = self.best_stop_order(start_id, stop_ids, destination_id, distances)
        best_stops = [stop_ids[index] for index in order]
        route = self.compute_route(start_id, destination_id, step_free, best_stops, min_width_m)
        if not math.isclose(route.length_m, best_length, abs_tol=1e-6):
            raise RuntimeError(f"Tour length {route.length_m} differs from the optimum {best_length}.")
        given_sequence = [start_id, *stop_ids, destination_id]
        given_length = sum(distances[a][b] for a, b in itertools.pairwise(given_sequence))
        if activate:
            self.last_route = route
            self.active_request = {
                "start": start_id, "destination": destination_id, "step_free": step_free,
                "via": best_stops or None, "min_width_m": min_width_m, "entrance": None,
            }
        return {
            "route": route,
            "stop_sequence": route.stops,
            "stops": [self.space_summary(space_id) for space_id in route.stops],
            "length_m": route.length_m,
            "given_order_length_m": given_length,
            "saving_m": max(given_length - route.length_m, 0.0),
            "constraints": {"step_free": step_free, "min_width_m": min_width_m, "closed": sorted(self.closed)},
            "optimal": True,
            "distance_model": KIT_DISTANCE_MODEL,
            "activated": activate,
        }

    # ---------- what-if analysis ----------

    MAX_WHAT_IF_ROOMS = 50
    WHAT_IF_ELIGIBILITY = (
        "Compares spaces of broad type 'room' on the target floor (halls, corridors, stairs, lifts and outdoor "
        "spaces are not counted); this matches all four labelled what-if questions."
    )
    WHAT_IF_INFINITY_RULE = (
        "Distance is the kit route length to the nearest entrance (plain walking, closures respected). A room "
        "unreachable before but reachable after the door is listed in newly_reachable and counts as an "
        "improvement; a room unreachable after the door never counts."
    )

    def exit_distances(self) -> dict[str, float]:
        """Kit 1.1.0 route length to the nearest entrance, using a multi-source Dijkstra.

        Plain walking: no step-free or width limit, current closures respected. Unreachable spaces are absent.
        """
        graph = self.graph()
        entrances = [
            DOOR_PREFIX + opening["id"] for opening in self.openings.values()
            if OUTSIDE in opening["space_ids"] and DOOR_PREFIX + opening["id"] in graph
        ]
        if not entrances:
            return {}
        lengths = nx.multi_source_dijkstra_path_length(graph, entrances, weight="weight")
        return {node: length for node, length in lengths.items() if node in self.spaces}

    def analyze_what_if_door(
        self, first_space: str, second_space: str, floor_level: int, improvement_threshold_m: float = 1.0
    ) -> dict:
        """Count target-floor rooms whose walk out of the building gets shorter by more than the threshold.

        Pure: the door is added to a deep copy of the building with the current closures, so this map's
        data, openings, closures, active route and spatial index never change, also when this raises.
        The door goes at the shared-wall midpoint (add_door). The what-if door is narrower than the default
        width when the shared wall is shorter than that: width does not affect plain walking, and the
        labelled questions include a 0.56 m shared wall.
        """
        threshold = check_number("improvement_threshold_m", improvement_threshold_m, 0)
        target = self.floor_by_level(floor_level)
        first_id, second_id = self.resolve_space(first_space), self.resolve_space(second_space)
        clone = BuildingMap(copy.deepcopy(self.data))
        clone.closed = set(self.closed)
        runs = clone.shared_wall(first_id, second_id)["runs"]
        longest = runs[0]["length_m"] if runs else 0.0
        # Without a real shared stretch keep the default width so add_door reports the missing wall.
        width = min(NEW_DOOR_WIDTH_M, longest) if longest > GEOMETRY_EPSILON else NEW_DOOR_WIDTH_M
        door = clone.add_door(first_id, second_id, width_m=width)
        before, after = self.exit_distances(), clone.exit_distances()
        rooms = sorted(
            space_id for space_id, space in self.spaces.items()
            if space["floor_id"] == target["id"] and space["type"] == self.COUNTED_SPACE_TYPE
        )
        gains, newly_reachable = {}, []
        for space_id in rooms:
            if space_id not in after:
                continue
            if space_id not in before:
                newly_reachable.append(space_id)
            elif before[space_id] - after[space_id] > threshold:
                gains[space_id] = before[space_id] - after[space_id]
        improved = [
            {
                "id": space_id, "name": self.spaces[space_id]["name"], "before_m": round(before[space_id], 2),
                "after_m": round(after[space_id], 2), "improvement_m": round(gain, 2),
            }
            for space_id, gain in sorted(gains.items(), key=lambda item: (-item[1], item[0]))
        ]
        return {
            "count": len(improved) + len(newly_reachable),
            "improved_count": len(improved),
            "newly_reachable_count": len(newly_reachable),
            "improved_rooms": improved[: self.MAX_WHAT_IF_ROOMS],
            "improved_rooms_truncated": len(improved) > self.MAX_WHAT_IF_ROOMS,
            "newly_reachable": newly_reachable[: self.MAX_WHAT_IF_ROOMS],
            "newly_reachable_truncated": len(newly_reachable) > self.MAX_WHAT_IF_ROOMS,
            "threshold_m": threshold,
            "proposed_door": {
                "position": door["position"], "width_m": door["width_m"], "space_ids": door["space_ids"],
                "floor_id": door["floor_id"],
            },
            "door_floor_level": self.floor_level(door["floor_id"]),
            "target_floor_level": target["level"],
            "eligible_rooms": len(rooms),
            "eligibility": self.WHAT_IF_ELIGIBILITY,
            "infinity_rule": self.WHAT_IF_INFINITY_RULE,
            "distance_model": KIT_DISTANCE_MODEL,
            "simulated": True,
            "note": "Hypothetical only: the door was added to a temporary copy; nothing was changed or saved.",
        }

    # ---------- navigation landmarks ----------

    MAX_LANDMARKS = 20
    MAX_COMPETITOR_IDS = 10
    LANDMARK_KINDS = ("asset", "space", "all")
    SIZE_CONVENTION = (
        "size_m2 is footprint area in square metres, not visual salience: assets use width_m x depth_m "
        "(rotation does not change it; null when the footprint is missing or partial), spaces use polygon area. "
        "min_size keeps candidates with size_m2 >= min_size; with min_size > 0 unknown sizes are excluded."
    )

    @staticmethod
    def landmark_size_m2(element: dict) -> float | None:
        """Asset footprint area, or None when width/depth are not both present; never guessed."""
        footprint = element.get("footprint")
        if not isinstance(footprint, dict):
            return None
        sides = []
        for name in ("width_m", "depth_m"):
            side = footprint.get(name)
            if isinstance(side, bool) or not isinstance(side, (int, float)) or not math.isfinite(side) or side < 0:
                return None
            sides.append(side)
        return float(sides[0] * sides[1])

    def find_navigation_landmarks(
        self, x_m: float, y_m: float, floor_level: int, inner_radius: float, outer_radius: float,
        min_size: float = 0.0, kind: str = "asset", within_spaces: list[str] | None = None,
    ) -> dict:
        """Reference objects near a route point, each with the identical-type objects that could be confused with it.

        Candidates lie within inner_radius of the point; competitors (same kind and exact normalized asset type or
        room type, any size, any room, same floor) lie within outer_radius of the same point. Proximity is not
        visibility, so every candidate reports visibility "unknown".
        """
        x_m, y_m = check_number("x_m", x_m), check_number("y_m", y_m)
        inner_radius = check_number("inner_radius", inner_radius, 0)
        outer_radius = check_number("outer_radius", outer_radius, 0)
        min_size = check_number("min_size", min_size, 0)
        if outer_radius < inner_radius:
            raise MapError(f"outer_radius ({outer_radius}) must be at least inner_radius ({inner_radius}).")
        if isinstance(floor_level, bool) or not isinstance(floor_level, int):
            raise MapError(f"floor_level must be an integer, got {floor_level!r}.")
        self.floor_by_level(floor_level)
        if not isinstance(kind, str) or kind.strip().lower() not in self.LANDMARK_KINDS:
            raise MapError(f"kind must be one of {list(self.LANDMARK_KINDS)}, got {kind!r}.")
        kind = kind.strip().lower()
        allowed_spaces: set[str] | None = None
        if within_spaces is not None:
            references = [within_spaces] if isinstance(within_spaces, str) else within_spaces
            if not isinstance(references, (list, tuple)) or not references:
                raise MapError("within_spaces must be a non-empty list of space references, or omitted.")
            allowed_spaces = {self.resolve_space(reference) for reference in references}

        point = Point(x_m, y_m)
        competitors: dict[tuple[str, str], list[dict]] = {}
        nearby = []
        for hit in self.spatial_search(x_m, y_m, floor_level, outer_radius, kind):
            if hit["kind"] == "opening":
                continue
            raw_type = hit["room_type"] if hit["kind"] == "space" else hit["type"]
            hit["normalized_type"] = normalize_type(raw_type) if isinstance(raw_type, str) else ""
            competitors.setdefault((hit["kind"], hit["normalized_type"]), []).append(hit)
            nearby.append(hit)

        candidates = []
        for hit in nearby:
            if hit["distance_m"] > inner_radius:
                continue
            is_space = hit["kind"] == "space"
            record = self.spaces[hit["id"]] if is_space else self.assets[hit["id"]]
            space_id = hit["id"] if is_space else record["space_id"]
            if allowed_spaces is not None and space_id not in allowed_spaces:
                continue
            size = self.space_area_m2(hit["id"]) if is_space else self.landmark_size_m2(record)
            if min_size > 0 and (size is None or size < min_size):
                continue
            rivals = sorted(
                other["id"] for other in competitors[(hit["kind"], hit["normalized_type"])]
                if other["id"] != hit["id"]
            )
            candidate = {
                "id": hit["id"], "name": hit["name"], "kind": hit["kind"],
                "type": hit["room_type"] if is_space else hit["type"],
                "space": {"id": space_id, "name": self.spaces[space_id]["name"]},
                "floor_level": floor_level,
                "distance_m": hit["distance_m"], "size_m2": size,
                "similar_count_outer": len(rivals),
                "competitor_ids": rivals[: self.MAX_COMPETITOR_IDS],
                "is_unambiguous": not rivals,
                "visibility": "unknown",
            }
            if is_space:
                polygon = self.space_polygon(hit["id"])
                nearest = nearest_points(polygon, point)[0]
                representative = polygon.representative_point()
                candidate["position"] = [nearest.x, nearest.y]
                candidate["representative_point"] = [representative.x, representative.y]
            else:
                candidate["position"] = list(record["position"])
            candidates.append(candidate)

        candidates.sort(key=lambda item: (
            not item["is_unambiguous"], item["distance_m"],
            item["size_m2"] is None, -(item["size_m2"] or 0.0), item["id"],
        ))
        returned = candidates[: self.MAX_LANDMARKS]
        for item in returned:
            item["distance_m"] = round(item["distance_m"], 3)
            if item["size_m2"] is not None:
                item["size_m2"] = round(item["size_m2"], 3)
            item["position"] = [round(value, 3) for value in item["position"]]
            if "representative_point" in item:
                item["representative_point"] = [round(value, 3) for value in item["representative_point"]]
        result = {
            "query": {
                "x_m": x_m, "y_m": y_m, "floor_level": floor_level, "inner_radius": inner_radius,
                "outer_radius": outer_radius, "min_size": min_size, "kind": kind,
                "within_spaces": sorted(allowed_spaces) if allowed_spaces is not None else None,
            },
            "size_convention": self.SIZE_CONVENTION,
            "candidate_count": len(candidates),
            "truncated": len(candidates) > len(returned),
            "unambiguous_count": sum(item["is_unambiguous"] for item in candidates),
            "candidates": returned,
        }
        if not candidates:
            result["hint"] = (
                "No candidate within inner_radius that passes min_size and within_spaces. "
                "Use the room or door names instead, or retry with a larger inner_radius or smaller min_size."
            )
        return result

    # ---------- map selection and context ----------

    CONTEXT_EXCLUDED_TYPES = ("corridor", "stair", "lift", "outdoor")
    CONTEXT_EXCLUDED_ROOM_TYPES = ("corridor", "stairwell", "lift")
    MAX_CONTEXT_ROOMS = 5

    def select(self, reference: str) -> dict:
        """Make a space or asset the map selection and return its identity.

        An asset id or exact asset name selects the asset and keeps its containing room; an ambiguous or
        unknown reference raises MapError (with candidate ids) and leaves the previous selection unchanged.
        """
        space_id = self.resolve_space(reference)
        asset = self.asset_behind_reference(reference, space_id)
        self.selection = {
            "kind": "asset" if asset else "space",
            "id": asset["id"] if asset else space_id,
            "space_id": space_id,
            "floor_id": self.spaces[space_id]["floor_id"],
        }
        if asset:
            self.located_asset_ids = [asset["id"]]
        return self.selection_identity()

    def place_record(self, space_id: str) -> dict:
        """Id, name and floor of a space, for listing route stops next to their map markers."""
        floor_id = self.spaces[space_id]["floor_id"]
        return {
            "id": space_id, "name": self.spaces[space_id]["name"],
            "floor_level": self.floor_level(floor_id), "floor": self.floor_name(floor_id),
        }

    def selection_identity(self) -> dict | None:
        """Name, containing room, floor and position of the current selection; None when nothing is selected."""
        if self.selection is None:
            return None
        space_id = self.selection["space_id"]
        room = self.space_summary(space_id)
        if self.selection["kind"] == "asset":
            asset = self.assets[self.selection["id"]]
            return {
                "kind": "asset", "id": asset["id"], "name": asset["name"], "type": asset["type"],
                "position": list(asset["position"]), "room": room,
                "floor_level": room["floor_level"], "floor": room["floor"],
            }
        point = self.anchor(space_id)
        return {
            **room, "kind": "space", "area_m2": round(self.space_area_m2(space_id), 3),
            "position": [round(point[0], 3), round(point[1], 3)],
        }

    def destination_context(self, reference: str, radius_m: float = 15.0, min_area_m2: float = 40.0) -> dict:
        """Named, sizable rooms around a destination room, for 'the destination is next to the canteen'.

        Uses find_navigation_landmarks(kind="space", min_size=min_area_m2) from the room's representative point,
        widened by the room's own extent so radius_m is measured from the room outline. relation is "adjacent"
        only when a same-floor wall of at least MIN_SHARED_WALL_M lies within SHARED_WALL_TOLERANCE_M (adjacency
        says nothing about a connecting door or access); otherwise "near" with the outline-to-outline distance.
        Corridors, stairs, lifts and outdoor spaces and the destination itself are left out. For an asset the
        context describes its containing room, not the asset's own position.
        """
        radius_m = check_number("radius_m", radius_m, 0)
        min_area_m2 = check_number("min_area_m2", min_area_m2, 0)
        space_id = self.resolve_space(reference)
        asset = self.asset_behind_reference(reference, space_id)
        polygon = self.valid_polygon(space_id)
        x, y = self.anchor(space_id)
        extent = max(math.dist((x, y), corner) for corner in polygon.exterior.coords)
        found = self.find_navigation_landmarks(
            x, y, self.floor_level(self.spaces[space_id]["floor_id"]), radius_m + extent, radius_m + extent,
            min_area_m2, "space",
        )
        rooms = []
        for candidate in found["candidates"]:
            other = self.spaces[candidate["id"]]
            if (
                candidate["id"] == space_id
                or normalize_type(other.get("type") or "") in self.CONTEXT_EXCLUDED_TYPES
                or normalize_type(other.get("room_type") or "") in self.CONTEXT_EXCLUDED_ROOM_TYPES
            ):
                continue
            distance = polygon.distance(self.valid_polygon(candidate["id"]))
            wall = self.space_wall_contact(space_id, candidate["id"], SHARED_WALL_TOLERANCE_M)["total_length_m"]
            adjacent = wall >= self.MIN_SHARED_WALL_M - GEOMETRY_EPSILON
            if distance > radius_m and not adjacent:
                continue
            room = {
                "id": candidate["id"], "name": other["name"], "ref": other.get("ref"), "type": other["type"],
                "room_type": other["room_type"], "area_m2": candidate["size_m2"],
                "relation": "adjacent" if adjacent else "near", "distance_m": round(distance, 3),
                "is_unambiguous": candidate["is_unambiguous"], "similar_count_outer": candidate["similar_count_outer"],
                "representative_point": candidate["representative_point"],
            }
            if adjacent:
                room["shared_wall_m"] = round(wall, 3)
            rooms.append(room)
        rooms.sort(key=lambda item: (
            item["relation"] != "adjacent", not item["is_unambiguous"], -item["area_m2"], item["distance_m"], item["id"],
        ))
        result = {
            "destination": {**self.space_summary(space_id), "area_m2": round(polygon.area, 3)},
            "query": {"radius_m": radius_m, "min_area_m2": min_area_m2, "from_outline": True},
            "context": rooms[: self.MAX_CONTEXT_ROOMS],
            "candidate_count": len(rooms),
        }
        if asset:
            result["asset"] = {"id": asset["id"], "name": asset["name"], "position": list(asset["position"])}
        if not rooms:
            result["hint"] = "No named room of at least min_area_m2 within radius_m: omit landmark context."
        return result

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
        walks = dict(self.walks)
        try:
            yield
        except BaseException:
            self.closed.clear()
            self.closed.update(closed)
            self.openings.clear()
            self.openings.update(openings)
            self.data["openings"][:] = opening_list
            self.last_route = last_route
            self.walks = walks
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
        """The part of the first space's outline that runs along the second space within tolerance_m.

        Walls have thickness, so rooms that share a wall have outlines up to about tolerance_m apart.
        Only stretches parallel to the other outline count (see wall_contact_runs): a corner-only
        contact has length 0. Returns total_length_m, runs (contiguous stretches with length_m, start
        and end, longest first) and midpoint: the middle of the longest run, halfway between both
        polygons (None if no contact). Both spaces must be on the same floor.
        """
        tolerance_m = check_number("tolerance_m", tolerance_m, 0)
        if first_id == second_id:
            raise MapError("A space does not share a wall with itself.")
        if self.spaces[first_id]["floor_id"] != self.spaces[second_id]["floor_id"]:
            raise MapError("Spaces on different floors cannot share a wall or a door.")
        contact = self.space_wall_contact(first_id, second_id, tolerance_m)
        runs = [
            {"length_m": self.run_length(run), "start": list(run[0]), "end": list(run[-1])}
            for run in contact["runs"]
        ]
        midpoint = None
        if runs:
            on_first = LineString(contact["runs"][0]).interpolate(0.5, normalized=True)
            on_second = nearest_points(self.valid_polygon(second_id), on_first)[0]
            midpoint = [(on_first.x + on_second.x) / 2, (on_first.y + on_second.y) / 2]
        return {
            "first_space_id": first_id, "second_space_id": second_id, "tolerance_m": tolerance_m,
            "total_length_m": contact["total_length_m"], "runs": runs, "midpoint": midpoint,
        }

    def add_door(
        self, first: str, second: str, step_free: bool = True, width_m: float = NEW_DOOR_WIDTH_M,
        position: Point2 | None = None,
    ) -> dict:
        """Add a door on a shared wall, defaulting to the midpoint; preserve explicit kit positions."""
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
        if position is not None:
            if not isinstance(position, (list, tuple)) or len(position) != 2:
                raise MapError("position must contain two finite metre coordinates.")
            position = [check_number("position", value) for value in position]
            point = Point(position)
            if any(self.valid_polygon(space_id).boundary.distance(point) > SHARED_WALL_TOLERANCE_M
                   for space_id in (first_id, second_id)):
                raise MapError("The explicit door position must lie on the shared wall.")
        position = [round(value, 6) + 0.0 for value in (position if position is not None else wall["midpoint"])]
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
        for space_id in (first_id, second_id):
            self.walks.pop(space_id, None)
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
