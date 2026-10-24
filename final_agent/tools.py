"""Tools the agent can call. Each one is a thin, typed wrapper around BuildingMap that returns JSON."""

import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from anthropic import beta_tool
from anthropic.lib.tools import ToolError

from .building_map import MAX_SEARCH_RESULTS, BuildingMap, MapError
from .viewer import draw_route

JSON_INDENT = 1


def as_json(value: object) -> str:
    return json.dumps(value, indent=JSON_INDENT, ensure_ascii=False)


def make_tools(building_map: BuildingMap, output_directory: Path) -> list:
    """Build the tool list bound to one building. Errors become is_error tool results via ToolError.

    Tools are registered in definition order; each topic section adds its own tools.
    """
    tools = []

    def register(function: Callable[..., str]) -> object:
        tool = beta_tool(function)
        tools.append(tool)
        return tool

    # ---------- overview and search ----------

    @register
    def building_overview() -> str:
        """Floors, stairs and lifts, entrances and current closures of the building. Call this first."""
        return as_json(building_map.overview())

    @register
    def search_building(query: str, floor_level: int | None = None) -> str:
        """Find rooms and things (furniture, machines, equipment) by name, room number or type.

        Args:
            query: Words to look for, e.g. "3d printer", "2.03", "toilet", "cnc mill", "lecture hall".
            floor_level: Only search this floor (0 = ground floor, -1 = basement). Omit to search all floors.
        """
        results = building_map.search(query, floor_level)
        if not results:
            raise ToolError(f"Nothing matches '{query}'. Try a shorter or more general query.")
        return as_json({"matches": len(results), "results": results[:MAX_SEARCH_RESULTS]})

    @register
    def spatial_search(
        x_m: float, y_m: float, floor_level: int, radius_m: float = 0,
        kind: str = "all",
    ) -> str:
        """Find rooms, assets and doors near a point using a per-floor spatial index.

        Args:
            x_m: X coordinate in the building's local metre frame.
            y_m: Y coordinate in the same frame.
            floor_level: Floor to search (0 = ground floor, -1 = basement).
            radius_m: Maximum distance in metres; 0 finds rooms covering the point.
            kind: all, space, asset or opening. Rooms use polygons; other kinds use positions.
        """
        try:
            results = building_map.spatial_search(x_m, y_m, floor_level, radius_m, kind)
        except MapError as error:
            raise ToolError(str(error)) from error
        return as_json({"matches": len(results), "results": results[:MAX_SEARCH_RESULTS]})

    # ---------- inspection ----------

    @register
    def inspect_space(space: str) -> str:
        """Complete inspection of one room: original record, area and geometry, floor, doors with widths and
        step-free flags, lifts and stairs, and the assets inside. Ambiguous names return candidate ids.

        Args:
            space: Space id, asset id (inspects the room containing it), or exact room number/name.
        """
        try:
            return as_json(building_map.inspect_space(space))
        except MapError as error:
            raise ToolError(str(error)) from error

    # ---------- routing ----------

    @register
    def find_route(
        start: str, destination: str, step_free: bool = False, via: list[str] | None = None
    ) -> str:
        """Shortest walking route between two places, with step-by-step directions and length in metres.

        Args:
            start: Space id, asset id, or exact room number/name of where the person is.
            destination: Space id, asset id, or exact room number/name of where they want to go.
            step_free: True to avoid stairs and steps (wheelchair, trolley, pram).
            via: Optional list of places to visit in order between start and destination (multi-stop tour).
        """
        try:
            result = building_map.route(start, destination, step_free, via)
        except MapError as error:
            raise ToolError(str(error)) from error
        return as_json(asdict(result))

    # ---------- reachability ----------

    # ---------- largest room ----------

    @register
    def find_largest_room(room_type: str, floor_level: int) -> str:
        """Find the largest room of an exact room type on one floor, ranked by polygon area.

        The scored answer names the selected room first and then its area in m². An empty match is a
        normal result (room is null); check available_room_types for the correct type name.

        Args:
            room_type: Exact room type, e.g. "office", "meeting_room", "lobby", "warehouse_zone".
            floor_level: Floor to search (0 = ground floor, -1 = basement).
        """
        try:
            return as_json(building_map.find_largest_room(room_type, floor_level))
        except MapError as error:
            raise ToolError(str(error)) from error

    # ---------- floor area totals ----------

    @register
    def sum_floor_area(room_type: str, floor_level: int) -> str:
        """Total floor area in m² of all rooms of one exact room type on one floor (sum of room areas).

        Includes every matching space, also halls such as warehouse zones. No matches gives count 0 and
        area 0 with the room types that exist on that floor. For a scored answer, the Answer line must
        contain exactly one number: the total area_m2 in m², with no room references or floor numbers.

        Args:
            room_type: Exact room type, e.g. "office", "toilet", "warehouse_zone" (not a substring match).
            floor_level: Floor level (0 = ground floor, -1 = basement).
        """
        try:
            result = building_map.sum_floor_area(room_type, floor_level)
        except MapError as error:
            raise ToolError(str(error)) from error
        return as_json(result)

    # ---------- straight-line 3D distance ----------

    def round_numbers(value: object, decimals: int) -> object:
        """Round every float in nested JSON-like data; used only for presentation."""
        if isinstance(value, float):
            return round(value, decimals)
        if isinstance(value, list):
            return [round_numbers(item, decimals) for item in value]
        if isinstance(value, dict):
            return {key: round_numbers(item, decimals) for key, item in value.items()}
        return value

    @register
    def straight_line_distance_3d(first: str, second: str) -> str:
        """Straight-line (through-the-air) distance in metres between two places, across floors if needed.

        Uses each room's polygon centroid and its floor's elevation, not walking routes. For a scored
        "Answer:" line give exactly one number: distance_m in metres. Do not use for walking distance.

        Args:
            first: Space id, asset id (its containing room is used), or exact room number/name.
            second: Space id, asset id (its containing room is used), or exact room number/name.
        """
        try:
            result = building_map.straight_line_distance_3d(first, second)
        except MapError as error:
            raise ToolError(str(error)) from error
        return as_json(round_numbers(result, 3))

    # ---------- stacked rooms ----------

    # ---------- shared walls ----------

    # ---------- errands ----------

    # ---------- tours ----------

    # ---------- what-if analysis ----------

    # ---------- navigation landmarks ----------

    # ---------- changes ----------

    @register
    def set_closed(element: str, closed: bool) -> str:
        """Close or reopen a lift, staircase, door or room, e.g. for maintenance. Affects all later routes.

        Args:
            element: Name or id of a lift/staircase ("Lift 1"), a door/opening id, or a room.
            closed: True to close it, False to reopen it.
        """
        try:
            element_id = building_map.set_closed(element, closed)
        except MapError as error:
            raise ToolError(str(error)) from error
        saved_path = output_directory / "building_edited.json"
        building_map.save(saved_path)
        return as_json({
            "element_id": element_id, "closed": closed,
            "all_closed": sorted(building_map.closed), "saved_to": str(saved_path),
        })

    @register
    def add_door(first_space: str, second_space: str, step_free: bool = True) -> str:
        """Add a door between two neighbouring rooms on the same floor (edits the building).

        Args:
            first_space: Space id or exact room number/name.
            second_space: Space id or exact room number/name.
            step_free: Whether the new door has no step.
        """
        try:
            opening = building_map.add_door(first_space, second_space, step_free)
        except MapError as error:
            raise ToolError(str(error)) from error
        building_map.save(output_directory / "building_edited.json")
        return as_json({"added": opening, "saved_to": str(output_directory / "building_edited.json")})

    # ---------- map display ----------

    @register
    def show_route() -> str:
        """Draw the most recent route on the floor plans and save the images; returns the file paths."""
        if building_map.last_route is None:
            raise ToolError("No route yet. Call find_route first.")
        return as_json({"images": [str(path) for path in draw_route(building_map, output_directory)]})

    return tools
