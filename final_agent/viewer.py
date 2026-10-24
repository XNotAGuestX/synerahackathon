"""Flat 2D route view: one PNG per floor the latest route passes through."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as PolygonPatch

from .building_map import DOOR_PREFIX, OUTSIDE, BuildingMap, RouteResult

ROOM_COLOUR = "#f3efe6"
CLOSED_COLOUR = "#f4cccc"
ROUTE_COLOUR = "#d32f2f"
OUTLINE_COLOUR = "#555555"
FIGURE_INCHES = 9
ROUTE_LINE_WIDTH = 2.5
MARKER_SIZE = 9


def node_location(building_map: BuildingMap, node: str) -> tuple[str, tuple[float, float]] | None:
    """Floor id and plan position of a route node; None for 'outside', which has no place on any plan."""
    if node == OUTSIDE:
        return None
    if node.startswith(DOOR_PREFIX):
        opening = building_map.openings[node.removeprefix(DOOR_PREFIX)]
        return opening["floor_id"], tuple(opening["position"])
    return building_map.spaces[node]["floor_id"], building_map.anchor(node)


def route_polylines(
    building_map: BuildingMap, route: RouteResult
) -> list[tuple[str, list[tuple[float, float]]]]:
    """The route's recorded nodes (room anchors and the doors actually used) as one polyline per floor run.

    A new polyline starts at every floor change, outside transition or revisit of a floor, so no line is
    drawn across stairs, lifts or the outside.
    """
    polylines: list[tuple[str, list[tuple[float, float]]]] = []
    previous_floor = None
    for node in route.node_path:
        location = node_location(building_map, node)
        if location is None:
            previous_floor = None
            continue
        floor_id, point = location
        if floor_id != previous_floor:
            polylines.append((floor_id, []))
        polylines[-1][1].append(point)
        previous_floor = floor_id
    return polylines


def draw_route(building_map: BuildingMap, output_directory: Path) -> list[Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    route = building_map.last_route
    polylines = route_polylines(building_map, route)
    floor_ids = list(dict.fromkeys(floor_id for floor_id, _ in polylines))
    written = []
    for floor_id in floor_ids:
        figure, axes = plt.subplots(figsize=(FIGURE_INCHES, FIGURE_INCHES))
        try:
            for space in building_map.spaces.values():
                if space["floor_id"] != floor_id:
                    continue
                colour = CLOSED_COLOUR if space["id"] in building_map.closed else ROOM_COLOUR
                axes.add_patch(
                    PolygonPatch(space["polygon"], facecolor=colour, edgecolor=OUTLINE_COLOUR, linewidth=0.5)
                )
            for floor_run, points in polylines:
                if floor_run == floor_id:
                    xs, ys = zip(*points, strict=True)
                    marker = "o" if len(points) == 1 else None  # a lone stair/lift node still shows
                    axes.plot(xs, ys, color=ROUTE_COLOUR, linewidth=ROUTE_LINE_WIDTH, marker=marker)
            start_floor, start_points = polylines[0]
            end_floor, end_points = polylines[-1]
            if start_floor == floor_id:
                axes.plot(*start_points[0], "o", color=ROUTE_COLOUR, markersize=MARKER_SIZE)
            if end_floor == floor_id:
                axes.plot(*end_points[-1], "*", color=ROUTE_COLOUR, markersize=MARKER_SIZE * 1.5)
            axes.autoscale_view()
            axes.set_aspect("equal")
            axes.axis("off")
            axes.set_title(f"{building_map.data['building']['name']} — {building_map.floor_name(floor_id)}")
            path = output_directory / f"route_{building_map.floors[floor_id]['level']}.png"
            figure.savefig(path, bbox_inches="tight")
            written.append(path)
        finally:
            plt.close(figure)
    return written
