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

    # ---------- floor area totals ----------

    # ---------- straight-line 3D distance ----------

    # ---------- stacked rooms ----------

    @register
    def find_stacked_room(space: str, direction: str) -> str:
        """The room directly above or below a room: the space on the next floor whose outline overlaps most.

        In the final answer name `room` first (use its `ref` when it has one, since names can repeat);
        mention runners_up only afterwards. If `room` is null, say why from `reason`. If
        `frame_warning` is present, tell the user the floors may not align.

        Args:
            space: Space id, asset id, or exact room number/name of the source room.
            direction: "above" (the floor over it) or "below" (the floor under it).
        """
        try:
            return as_json(building_map.find_stacked_room(space, direction))
        except MapError as error:
            raise ToolError(str(error)) from error

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
