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

    @register
    def reachable_rooms(
        start: str, floor_level: int | None = None, step_free: bool = False, min_width_m: float = 0.0,
        entrance: str | None = None, closed_elements: list[str] | None = None, room_type: str | None = None,
    ) -> str:
        """Count and list the rooms a person or delivery can reach from a start room under constraints.

        Answers "how many rooms can X reach?" and "into how many rooms can it be delivered?". The scored
        answer line is exactly one integer: the `count`. The result also gives sorted `room_ids`, compact
        `rooms`, the applied `constraints`, the `entry` used and `excluded_reachable` (reachable spaces
        that are not counted, by type). Only spaces of type "room" count; halls, corridors, stairs and
        lifts are passed through but not counted. The start room counts. Nothing is changed or saved.

        Args:
            start: Space id, asset id, or exact room number/name where the person or load starts.
            floor_level: Count only rooms on this floor (0 = ground floor). Omit for all floors.
            step_free: True for "no stairs or steps (lifts are fine)", wheelchairs and trolleys.
            min_width_m: Every door passed must be at least this wide, e.g. a 1.1 m trolley -> 1.1.
            entrance: Entrance opening id (must satisfy step_free and min_width_m, else an error), or the
                start room itself for "it arrives through the entrance into <room>". For a room, a closed
                or stepped entrance is an error; a too-narrow one only adds a warning (benchmark convention).
            closed_elements: Extra closures for this query only (lift/stair names, door or room ids),
                e.g. ["Lift 1"] for "Lift 1 is out of service".
            room_type: Optional exact room type (office, meeting_room, ...) to count only those rooms.
        """
        try:
            return as_json(building_map.reachable_rooms(
                start, floor_level, step_free, min_width_m, entrance, closed_elements, room_type
            ))
        except MapError as error:
            raise ToolError(str(error)) from error

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

    @register
    def find_navigation_landmarks(
        x_m: float, y_m: float, floor_level: int, inner_radius: float, outer_radius: float,
        min_size: float = 0.0, kind: str = "asset", within_spaces: list[str] | None = None,
    ) -> str:
        """Find reference objects near a route step and check that they are not confusable with similar ones.

        Use the x/y of the actual step or arrival point of a computed route. Candidates lie within
        `inner_radius` metres of that point. Competitors are objects of the same kind and exact type (asset
        type or room type; numbering in names is ignored) within `outer_radius` of the same point, on the
        same floor, in any room, of any size, including those inside the inner circle. A cue such as "the
        fire extinguisher" is only safe when its `is_unambiguous` is true (similar_count_outer is 0).
        Unambiguous candidates are listed first. If none is unambiguous, do not say "the extinguisher":
        use room or door names, or an explicitly qualified cue. Nearby does not mean visible: every
        candidate has visibility "unknown" and may be behind a wall, so pass `within_spaces` (the route's
        current and next rooms) to drop cues in unrelated rooms. This tool gives no heading: never invent
        a left or right turn. `min_size` is a footprint area in m2 (not salience); with min_size > 0
        objects of unknown size are excluded. An empty result is normal.

        Args:
            x_m: X coordinate of the route point in the building's local metre frame.
            y_m: Y coordinate in the same frame.
            floor_level: Floor of the point (0 = ground floor, -1 = basement).
            inner_radius: Maximum distance in metres of a candidate cue from the point (>= 0).
            outer_radius: Radius in metres in which identical-type objects count as competitors (>= inner_radius).
            min_size: Minimum footprint area in m2 for a candidate (default 0 = any, unknown size allowed).
            kind: "asset" (step cues, default), "space" (larger destination context) or "all".
            within_spaces: Optional space ids/names; only assets inside or spaces equal to these are candidates.
        """
        try:
            result = building_map.find_navigation_landmarks(
                x_m, y_m, floor_level, inner_radius, outer_radius, min_size, kind, within_spaces
            )
        except MapError as error:
            raise ToolError(str(error)) from error
        return as_json(result)

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
