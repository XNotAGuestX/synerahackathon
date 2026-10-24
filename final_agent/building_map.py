"""Deterministic core of the project agent: load a building.json, search it, route through it, edit it.

The agent (agent.py) is only the conversation layer; every fact it states comes from this module.
The route cost model matches the one used to compute the dataset's expected answers."""

import itertools
import math
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
from shapely.geometry import Polygon
from shapely.ops import nearest_points

from .storage import BuildingSpatialIndex, JsonBuildingStore

OUTSIDE = "outside"
DOOR_PREFIX = "door:"
LIFT = "lift"
STAIRS_COST_PER_FLOOR_M = 12.0
LIFT_WAIT_COST_M = 15.0
LIFT_COST_PER_FLOOR_M = 6.0
MAX_SEARCH_RESULTS = 15
ADJACENT_DISTANCE_M = 0.6
NEW_DOOR_WIDTH_M = 0.9


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
    start_space_id: str
    destination_space_id: str
    length_m: float
    space_path: list[str]
    steps: list[str]
    step_free: bool
    closed: list[str] = field(default_factory=list)


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

    def graph(self, step_free: bool) -> nx.MultiGraph:
        # MultiGraph: a stair and a lift may join the same two spaces; both edges must be kept.
        graph = nx.MultiGraph()
        anchors = {space_id: self.anchor(space_id) for space_id in self.spaces if space_id not in self.closed}
        graph.add_nodes_from(anchors)
        for opening in self.openings.values():
            if opening["id"] in self.closed or (step_free and not opening["step_free"]):
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

    def route(
        self, start: str, destination: str, step_free: bool = False, via: list[str] | None = None
    ) -> RouteResult:
        stops = [
            self.resolve_space(start),
            *[self.resolve_space(stop) for stop in via or []],
            self.resolve_space(destination),
        ]
        graph = self.graph(step_free)
        nodes: list[str] = []
        length = 0.0
        for leg_start, leg_end in itertools.pairwise(stops):
            try:
                leg_length, leg_nodes = nx.single_source_dijkstra(graph, leg_start, leg_end, weight="weight")
            except (nx.NetworkXNoPath, nx.NodeNotFound) as error:
                reason = "step-free " if step_free else ""
                raise MapError(
                    f"No {reason}route from {self.describe_space(leg_start)} to "
                    f"{self.describe_space(leg_end)} with the current closures {sorted(self.closed)}."
                ) from error
            length += leg_length
            nodes += leg_nodes if not nodes else leg_nodes[1:]
        result = RouteResult(
            start_space_id=stops[0],
            destination_space_id=stops[-1],
            length_m=round(length, 2),
            space_path=[node for node in nodes if not node.startswith(DOOR_PREFIX)],
            steps=self.directions(graph, nodes),
            step_free=step_free,
            closed=sorted(self.closed),
        )
        self.last_route = result
        return result

    def directions(self, graph: nx.MultiGraph, nodes: list[str]) -> list[str]:
        """Turn a node path into followable steps: one line per room change or floor change."""
        steps = [f"Start in {self.describe_space(nodes[0])}."]
        walked = 0.0
        for previous, current in itertools.pairwise(nodes):
            edge = min(graph[previous][current].values(), key=lambda candidate: candidate["weight"])
            walked += edge["weight"]
            element = edge["via"]
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

    def set_closed(self, reference: str, closed: bool) -> str:
        element = self.find_element(reference)
        if closed:
            self.closed.add(element)
        else:
            self.closed.discard(element)
        return element

    def add_door(self, first: str, second: str, step_free: bool = True) -> dict:
        first_id, second_id = self.resolve_space(first), self.resolve_space(second)
        first_space, second_space = self.spaces[first_id], self.spaces[second_id]
        if first_space["floor_id"] != second_space["floor_id"]:
            raise MapError("A door can only join two spaces on the same floor.")
        first_polygon, second_polygon = Polygon(first_space["polygon"]), Polygon(second_space["polygon"])
        if first_polygon.distance(second_polygon) > ADJACENT_DISTANCE_M:
            raise MapError(f"{first_space['name']} and {second_space['name']} do not share a wall.")
        point_a, point_b = nearest_points(first_polygon, second_polygon)
        opening = {
            "id": f"{first_space['floor_id']}-O-new{len(self.openings) + 1}",
            "floor_id": first_space["floor_id"],
            "space_ids": [first_id, second_id],
            "kind": "door",
            "position": [round((point_a.x + point_b.x) / 2, 3), round((point_a.y + point_b.y) / 2, 3)],
            "width_m": NEW_DOOR_WIDTH_M,
            "step_free": step_free,
            "synthetic": True,
        }
        self.openings[opening["id"]] = opening
        self.data["openings"].append(opening)
        self._spatial_index = None
        return opening

    def save(self, path: Path) -> None:
        snapshot = {
            **self.data,
            "navigation_state": {
                **self.data.get("navigation_state", {}), "closed": sorted(self.closed)
            },
        }
        JsonBuildingStore.save(path, snapshot)
