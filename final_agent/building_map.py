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
SHARED_WALL_GAP_M = 0.35
SHARED_WALL_MIN_M = 1.0
NON_ROOM_TYPES = {"corridor", "stairwell", "stairs", "stair", "lift", "outdoor", "balcony"}


class MapError(ValueError):
    """Raised for anything the user should be told about (unknown place, no route, ...)."""


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

    def graph(self, step_free: bool, min_width_m: float = 0.0) -> nx.MultiGraph:
        # MultiGraph: a stair and a lift may join the same two spaces; both edges must be kept.
        graph = nx.MultiGraph()
        anchors = {space_id: self.anchor(space_id) for space_id in self.spaces if space_id not in self.closed}
        graph.add_nodes_from(anchors)
        for opening in self.openings.values():
            if opening["id"] in self.closed or (step_free and not opening["step_free"]):
                continue
            if float(opening.get("width_m", 0)) < min_width_m:
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

    def polygon_of(self, space_id: str) -> Polygon:
        shape = Polygon(self.spaces[space_id]["polygon"])
        return shape if shape.is_valid else shape.buffer(0)

    def area_m2(self, space_id: str) -> float:
        return float(self.polygon_of(space_id).area)

    def centroid_xy(self, space_id: str) -> tuple[float, float]:
        point = self.polygon_of(space_id).centroid
        return (point.x, point.y)

    def resolve_floor(self, reference: str | int) -> str:
        text = str(reference)
        if text in self.floors:
            return text
        lowered = text.strip().lower()
        named = [floor["id"] for floor in self.floors.values() if floor["name"].lower() == lowered]
        if len(named) == 1:
            return named[0]
        try:
            level = int(text)
        except ValueError as error:
            raise MapError(f"No floor matches '{reference}'.") from error
        matched = [floor["id"] for floor in self.floors.values() if floor["level"] == level]
        if len(matched) == 1:
            return matched[0]
        raise MapError(f"No floor matches '{reference}'.")

    def matching_spaces(self, floor_id: str, room_type: str | None = None) -> list[dict]:
        floor_id = self.resolve_floor(floor_id)
        spaces = [space for space in self.spaces.values() if space["floor_id"] == floor_id]
        if room_type:
            spaces = [space for space in spaces if space.get("room_type") == room_type]
        return spaces

    def largest_room(self, floor_id: str, room_type: str) -> dict:
        spaces = self.matching_spaces(floor_id, room_type)
        if not spaces:
            raise MapError(f"No {room_type} on {floor_id}.")
        space = max(spaces, key=lambda item: self.area_m2(item["id"]))
        return self._room_record(space)

    def floor_area_total(self, floor_id: str, room_type: str) -> dict:
        spaces = self.matching_spaces(floor_id, room_type)
        area = sum(self.area_m2(space["id"]) for space in spaces)
        return {"floor_id": self.resolve_floor(floor_id), "room_type": room_type, "count": len(spaces), "area_m2": round(area, 2)}

    def straight_line_3d(self, first: str, second: str) -> dict:
        first_id, second_id = self.resolve_space(first), self.resolve_space(second)
        first_xyz = (*self.centroid_xy(first_id), self.floors[self.spaces[first_id]["floor_id"]]["elevation_m"])
        second_xyz = (*self.centroid_xy(second_id), self.floors[self.spaces[second_id]["floor_id"]]["elevation_m"])
        return {
            "first": first_id,
            "second": second_id,
            "distance_m": round(math.dist(first_xyz, second_xyz), 2),
        }

    def room_stacked(self, start: str, direction: str) -> dict:
        source_id = self.resolve_space(start)
        source = self.spaces[source_id]
        current = self.floors[source["floor_id"]]["level"]
        ordered = sorted(self.floors.values(), key=lambda floor: floor["level"])
        if direction == "above":
            neighbours = [floor for floor in ordered if floor["level"] > current]
            target = neighbours[0] if neighbours else None
        elif direction == "below":
            neighbours = [floor for floor in ordered if floor["level"] < current]
            target = neighbours[-1] if neighbours else None
        else:
            raise MapError("direction must be above or below.")
        if target is None:
            raise MapError(f"No floor {direction} {source['name']}.")
        source_shape = self.polygon_of(source_id)
        best = None
        best_overlap = 0.0
        for space in self.spaces.values():
            if space["floor_id"] != target["id"]:
                continue
            overlap = source_shape.intersection(self.polygon_of(space["id"])).area
            if overlap > best_overlap:
                best = space
                best_overlap = overlap
        if best is None or best_overlap <= 0:
            raise MapError(f"No room {direction} {source['name']} overlaps it.")
        record = self._room_record(best)
        record["overlap_m2"] = round(best_overlap, 2)
        return record

    def shared_walls_count(self, start: str) -> dict:
        source_id = self.resolve_space(start)
        source = self.spaces[source_id]
        neighbours = [
            space["id"]
            for space in self.spaces.values()
            if space["floor_id"] == source["floor_id"]
            and space["id"] != source_id
            and not self._non_room(space)
            and self._shares_wall(source_id, space["id"])
        ]
        return {"space_id": source_id, "count": len(neighbours), "neighbours": neighbours}

    def wide_delivery_count(self, start: str, floor_id: str, min_width_m: float) -> dict:
        return self._reachable_room_count(start, floor_id, step_free=True, min_width_m=min_width_m, require_type="room")

    def step_free_reachable_count(self, start: str, floor_id: str, closed: str | None = None) -> dict:
        clone = self.clone()
        if closed:
            clone.set_closed(closed, True)
        return clone._reachable_room_count(start, floor_id, step_free=True)

    def errand(self, start: str, asset_type: str, floor_id: str, room_type: str, step_free: bool = False) -> dict:
        start_id = self.resolve_space(start)
        pickups = sorted({asset["space_id"] for asset in self.assets.values() if asset["type"] == asset_type})
        if not pickups:
            raise MapError(f"No {asset_type} in this building.")
        graph = self.graph(step_free)
        nearest = None
        nearest_length = None
        for pickup in pickups:
            length = self._path_length(graph, start_id, pickup)
            if length is None:
                continue
            if nearest_length is None or length < nearest_length:
                nearest = pickup
                nearest_length = length
        if nearest is None or nearest_length is None:
            raise MapError(f"No reachable {asset_type} from {self.describe_space(start_id)}.")
        target = self.largest_room(floor_id, room_type)
        second = self._path_length(graph, nearest, target["space_id"])
        if second is None:
            raise MapError(f"No route from the pickup to {target['name']}.")
        return {
            "start": start_id,
            "pickup": nearest,
            "destination": target["space_id"],
            "length_m": round(nearest_length + second, 2),
            "step_free": step_free,
        }

    def what_if_door(self, first: str, second: str, floor_id: str) -> dict:
        floor_id = self.resolve_floor(floor_id)
        rooms = [space["id"] for space in self.matching_spaces(floor_id) if not self._non_room(space)]
        before = {space_id: self._exit_distance(space_id) for space_id in rooms}
        clone = self.clone()
        clone.add_door(first, second)
        improved = []
        for space_id, old in before.items():
            new = clone._exit_distance(space_id)
            old_distance = math.inf if old is None else old
            new_distance = math.inf if new is None else new
            if old_distance - new_distance > 1.0:
                improved.append(space_id)
        return {"floor_id": floor_id, "count": len(improved), "improved": improved}

    def clone(self) -> "BuildingMap":
        import copy
        return BuildingMap(copy.deepcopy(self.data))

    def _room_record(self, space: dict) -> dict:
        return {
            "space_id": space["id"],
            "name": space["name"],
            "ref": space.get("ref"),
            "room_type": space.get("room_type"),
            "floor_id": space["floor_id"],
            "area_m2": round(self.area_m2(space["id"]), 2),
        }

    def _non_room(self, space: dict) -> bool:
        return space.get("type") in NON_ROOM_TYPES or space.get("room_type") in NON_ROOM_TYPES

    def _shares_wall(self, first_id: str, second_id: str) -> bool:
        near = self.polygon_of(second_id).buffer(SHARED_WALL_GAP_M)
        shared = self.polygon_of(first_id).boundary.intersection(near)
        return shared.length >= SHARED_WALL_MIN_M

    def _path_length(self, graph: nx.MultiGraph, start: str, destination: str) -> float | None:
        try:
            length, _nodes = nx.single_source_dijkstra(graph, start, destination, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None
        return float(length)

    def _exit_distance(self, space_id: str) -> float | None:
        if OUTSIDE not in self.graph(False):
            return None
        return self._path_length(self.graph(False), self.resolve_space(space_id), OUTSIDE)

    def _reachable_room_count(
        self,
        start: str,
        floor_id: str,
        step_free: bool,
        min_width_m: float = 0.0,
        require_type: str | None = None,
    ) -> dict:
        start_id = self.resolve_space(start)
        floor_id = self.resolve_floor(floor_id)
        graph = self.graph(step_free, min_width_m)
        try:
            lengths = nx.single_source_dijkstra_path_length(graph, start_id, weight="weight")
        except nx.NodeNotFound:
            lengths = {}
        rooms = [
            space["id"]
            for space in self.matching_spaces(floor_id)
            if space["id"] in lengths
            and not self._non_room(space)
            and (require_type is None or space.get("type") == require_type)
        ]
        return {"start": start_id, "floor_id": floor_id, "count": len(rooms), "rooms": rooms}

    def save(self, path: Path) -> None:
        snapshot = {
            **self.data,
            "navigation_state": {
                **self.data.get("navigation_state", {}), "closed": sorted(self.closed)
            },
        }
        JsonBuildingStore.save(path, snapshot)
