"""Tools the agent can call. Each one is a thin, typed wrapper around BuildingMap that returns JSON."""

import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from anthropic import beta_tool
from anthropic.lib.tools import ToolError

from .building_map import MAX_SEARCH_RESULTS, NEW_DOOR_WIDTH_M, BuildingMap, MapError, RouteResult
from .viewer import draw_route

JSON_INDENT = 1


def as_json(value: object) -> str:
    return json.dumps(value, indent=JSON_INDENT, ensure_ascii=False)


def route_json(route: RouteResult) -> dict:
    """Route as a plain dict for tool output; lengths are rounded only here."""
    result = asdict(route)
    result["length_m"] = round(route.length_m, 2)
    result["legs"] = [{**leg, "length_m": round(leg["length_m"], 2)} for leg in route.legs]
    return result


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
        start: str, destination: str, step_free: bool = False, via: list[str] | None = None,
        min_width_m: float = 0.0, entrance: str | None = None,
    ) -> str:
        """Shortest walking route between two places, with step-by-step directions and length in metres.

        The result lists the doors and lifts/stairs used (element_path), each leg between stops and the
        floor segments. It becomes the route that show_route draws.

        Args:
            start: Space id, asset id, or exact room number/name of where the person is.
            destination: Space id, asset id, or exact room number/name of where they want to go.
            step_free: True to avoid stairs and steps (wheelchair, trolley, pram).
            via: Optional list of places to visit in order between start and destination (multi-stop tour).
            min_width_m: Only use doors at least this wide in metres (e.g. a 1.1 m wide trolley). 0 = any.
            entrance: Optional entrance opening id the person came in through; it must open into the start
                room and itself satisfy step_free and min_width_m.
        """
        try:
            result = building_map.route(start, destination, step_free, via, min_width_m, entrance)
        except MapError as error:
            raise ToolError(str(error)) from error
        return as_json(route_json(result))

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

    def apply_edit(edit: Callable[[], Any]) -> tuple[Any, Path]:
        """Run an edit and save it; if saving fails the map is restored and the change reported as not applied."""
        saved_path = output_directory / "building_edited.json"
        try:
            with building_map.transaction():
                result = edit()
                building_map.save(saved_path)
        except MapError as error:
            raise ToolError(str(error)) from error
        except (OSError, TypeError, ValueError) as error:
            raise ToolError(f"The change was NOT applied: saving {saved_path} failed ({error}).") from error
        return result, saved_path

    def active_route_update() -> dict:
        """After an edit: the recomputed active route, or why it is gone. Empty when no route is active."""
        if building_map.active_request is None:
            return {}
        try:
            return {"active_route": route_json(building_map.recompute_active_route())}
        except MapError as error:
            return {"active_route_error": str(error)}

    @register
    def set_closed(element: str, closed: bool) -> str:
        """Close or reopen a lift, staircase, door or room, e.g. for maintenance. Affects all later routes.

        If a route is active it is recomputed with its original constraints: the result contains
        active_route (the new route) or active_route_error (why it is no longer possible).

        Args:
            element: Name or id of a lift/staircase ("Lift 1"), a door/opening id, or a room.
            closed: True to close it, False to reopen it.
        """
        element_id, saved_path = apply_edit(lambda: building_map.set_closed(element, closed))
        return as_json({
            "element_id": element_id, "closed": closed,
            "all_closed": sorted(building_map.closed), "saved_to": str(saved_path),
            **active_route_update(),
        })

    @register
    def add_door(
        first_space: str, second_space: str, step_free: bool = True, width_m: float = NEW_DOOR_WIDTH_M
    ) -> str:
        """Add a door in the middle of the wall two neighbouring rooms on the same floor share (edits the building).

        If a route is active it is recomputed: the result contains active_route or active_route_error.

        Args:
            first_space: Space id or exact room number/name.
            second_space: Space id or exact room number/name.
            step_free: Whether the new door has no step.
            width_m: Door width in metres; the shared wall must be at least this long.
        """
        opening, saved_path = apply_edit(
            lambda: building_map.add_door(first_space, second_space, step_free, width_m)
        )
        shown = {**opening, "position": [round(value, 3) for value in opening["position"]]}
        return as_json({"added": shown, "saved_to": str(saved_path), **active_route_update()})

    # ---------- map display ----------

    @register
    def show_route() -> str:
        """Draw the most recent route on the floor plans and save the images; returns the file paths."""
        if building_map.last_route is None:
            raise ToolError("No route yet. Call find_route first.")
        return as_json({"images": [str(path) for path in draw_route(building_map, output_directory)]})

    return tools
