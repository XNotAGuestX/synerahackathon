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

    def page_json(items: list[dict], page: int, page_size: int, empty_hint: str) -> str:
        paged = building_map.paginate(items, page, page_size)
        if not items:
            paged["hint"] = empty_hint
        return as_json(paged)

    @register
    def search_building(
        query: str = "", floor_level: int | None = None, kind: str = "all",
        room_type: str | None = None, asset_type: str | None = None, space_type: str | None = None,
        page: int = 1, page_size: int = MAX_SEARCH_RESULTS,
    ) -> str:
        """Find rooms and things (furniture, machines, equipment) by name/number/type, or count and list them exactly.

        `matches` is the exact number of hits over the whole building (or floor), not just this page. Results
        are sorted (assets, then spaces; by floor, name, id). If has_more is true, call again with page=next_page
        and the same arguments to see the rest. A map edit can change the inventory: restart at page 1 afterwards.
        Exact filters (case, spaces, hyphens and underscores are ignored; never partial matches) are separate
        from the fuzzy `query`; an empty query is allowed when a filter is given, e.g. query="",
        asset_type="chair", floor_level=2 gives the exact number of chairs on floor 2 in `matches`.

        Args:
            query: Words that must all appear in a name, room number or type, e.g. "3d printer", "2.03",
                "lecture hall". May be empty if a filter is given.
            floor_level: Only this floor (0 = ground floor, -1 = basement). Omit to search all floors.
            kind: "all" (default), "space" (rooms, halls, corridors, stairs, ...) or "asset" (things in rooms).
            room_type: Exact room subtype of a space, e.g. "office", "lobby", "warehouse_zone". Returns spaces only.
            asset_type: Exact asset type, e.g. "chair", "desk", "printer". Returns assets only.
            space_type: Exact broad space type: room, hall, corridor, stair, lift or outdoor. Returns spaces only.
            page: Page number, starting at 1.
            page_size: Results per page, 1 to 100 (default 15).
        """
        try:
            results = building_map.search(query, floor_level, kind, room_type, asset_type, space_type)
            return page_json(
                results, page, page_size,
                "Nothing matches. Check the spelling, drop a filter, or use a shorter, more general query.",
            )
        except MapError as error:
            raise ToolError(str(error)) from error

    @register
    def list_spaces(
        floor_level: int | None = None, room_type: str | None = None, space_type: str | None = None,
        page: int = 1, page_size: int = MAX_SEARCH_RESULTS,
    ) -> str:
        """List every space (rooms, halls, corridors, stairs, lifts, outdoor areas; never assets) completely.

        `matches` is the exact number of spaces with these filters, not just this page. Sorted by floor, name,
        id. If has_more is true, call again with page=next_page and the same arguments. A map edit can change
        the inventory: restart at page 1 afterwards. With no filters every space type is included.

        Args:
            floor_level: Only this floor (0 = ground floor, -1 = basement). Omit for all floors.
            room_type: Exact room subtype, e.g. "office", "toilet", "warehouse_zone" (case, spaces and
                hyphens are ignored; never partial matches).
            space_type: Exact broad type: room, hall, corridor, stair, lift or outdoor.
            page: Page number, starting at 1.
            page_size: Results per page, 1 to 100 (default 15).
        """
        try:
            spaces = [
                building_map.space_record(space)
                for space in building_map.filter_spaces(floor_level, room_type, space_type)
            ]
            return page_json(
                spaces, page, page_size,
                f"No spaces match. Room types here: {building_map.room_types(floor_level)}.",
            )
        except MapError as error:
            raise ToolError(str(error)) from error

    @register
    def spatial_search(
        x_m: float, y_m: float, floor_level: int, radius_m: float = 0,
        kind: str = "all", page: int = 1, page_size: int = MAX_SEARCH_RESULTS,
    ) -> str:
        """Find rooms, assets and doors near a point using a per-floor spatial index.

        `matches` is the exact number of hits within the radius, not just this page. Sorted by distance, then
        kind and id. If has_more is true, call again with page=next_page and the same arguments. A map edit
        can change the inventory: restart at page 1 afterwards.

        Args:
            x_m: X coordinate in the building's local metre frame.
            y_m: Y coordinate in the same frame.
            floor_level: Floor to search (0 = ground floor, -1 = basement).
            radius_m: Maximum distance in metres; 0 finds rooms covering the point.
            kind: all, space, asset or opening. Rooms use polygons; other kinds use positions.
            page: Page number, starting at 1.
            page_size: Results per page, 1 to 100 (default 15).
        """
        try:
            results = building_map.spatial_search(x_m, y_m, floor_level, radius_m, kind)
            return page_json(results, page, page_size, "Nothing within that radius. Try a larger radius_m.")
        except MapError as error:
            raise ToolError(str(error)) from error
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
